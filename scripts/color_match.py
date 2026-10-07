#!/usr/bin/env python3
"""Undo the colour drift that image *edits* introduce (nano-banana / Gemini).

Banana edits re-render the whole frame: unchanged areas come back slightly
magenta (a* up, b* down, R/B up and G down), often with a luminance-dependent
tone shift, a 1-2 px shift and a ~0.2 % rescale. This tool:

  1. registers the source onto the edit (ECC, translation -> affine);
  2. finds the areas the edit did NOT change (local structure match);
  3. robustly fits a colour mapping edit -> source on those areas only
     (per-channel monotone tone curves, then a shrunk 3D LUT for hue-dependent
     residuals, then an optional low-frequency spatial field), choosing the
     model level by cross-validation so it never over-fits;
  4. applies the mapping to the full-resolution edit. Pixels the edit really
     changed (new sky, new product colour) are outliers and do not steer the
     fit, so intentional edits survive; they only lose the global cast.

Optional --paste-back composites the edited region into the original frame
so every unchanged pixel is bit-identical to the source.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    comparison_board,
    delta_e2000,
    lab_to_rgb,
    load_image,
    luma,
    rgb_to_lab,
    save_image,
    to_pil,
)

import cv2  # noqa: E402

ANALYSIS_SIDE = 1024
LUT_N = 17


# ---------------------------------------------------------------- geometry

def _resize(rgb, size):
    w, h = size
    interp = cv2.INTER_AREA if w < rgb.shape[1] else cv2.INTER_LINEAR
    return cv2.resize(rgb, (w, h), interpolation=interp)


def _analysis_size(shape, side=ANALYSIS_SIDE):
    h, w = shape[:2]
    s = min(1.0, side / max(h, w))
    return max(16, int(round(w * s))), max(16, int(round(h * s)))


def _grad_mag(g):
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    return np.hypot(gx, gy)


def _warp_score(src_g, edit_g, warp):
    h, w = edit_g.shape
    ws = cv2.warpAffine(src_g, warp, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                        borderMode=cv2.BORDER_REFLECT)
    a, b = _grad_mag(ws), _grad_mag(edit_g)
    m = 8
    a, b = a[m:-m, m:-m].ravel(), b[m:-m, m:-m].ravel()
    if a.std() < 1e-6 or b.std() < 1e-6:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def register(src_a, edit_a):
    """Return 2x3 warp mapping edit-analysis coords -> source-analysis coords."""
    g1 = cv2.GaussianBlur(luma(src_a).astype(np.float32), (0, 0), 1.2)
    g2 = cv2.GaussianBlur(luma(edit_a).astype(np.float32), (0, 0), 1.2)
    ident = np.eye(2, 3, dtype=np.float32)
    best_w, best_s, kind = ident, _warp_score(g1, g2, ident), "identity"
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 120, 1e-6)
    warp = ident.copy()
    for motion, name in ((cv2.MOTION_TRANSLATION, "translation"), (cv2.MOTION_AFFINE, "affine")):
        try:
            _, warp = cv2.findTransformECC(g2, g1, warp.copy(), motion, crit, None, 5)
        except cv2.error:
            continue
        s = _warp_score(g1, g2, warp)
        # an affine must buy real alignment to be trusted
        if s > best_s + (0.002 if name == "affine" else 0.0):
            best_w, best_s, kind = warp.copy(), s, name
    return best_w, best_s, kind


def register_features(src_a, edit_a):
    """Similarity transform from feature matches - handles crops, outpaint and
    aspect changes that ECC (identity start, same size) cannot."""
    g1 = np.clip(luma(src_a) * 255, 0, 255).astype(np.uint8)
    g2 = np.clip(luma(edit_a) * 255, 0, 255).astype(np.uint8)
    try:
        det = cv2.SIFT_create(4000)
        norm = cv2.NORM_L2
    except AttributeError:
        det = cv2.ORB_create(5000)
        norm = cv2.NORM_HAMMING
    k1, d1 = det.detectAndCompute(g1, None)
    k2, d2 = det.detectAndCompute(g2, None)
    if d1 is None or d2 is None or len(k1) < 12 or len(k2) < 12:
        return None, 0.0
    matches = cv2.BFMatcher(norm).knnMatch(d2, d1, k=2)
    good = [m[0] for m in matches if len(m) == 2 and m[0].distance < 0.75 * m[1].distance]
    if len(good) < 12:
        return None, 0.0
    pe = np.float32([k2[m.queryIdx].pt for m in good])
    ps = np.float32([k1[m.trainIdx].pt for m in good])
    M, inl = cv2.estimateAffinePartial2D(pe, ps, method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if M is None or inl is None or inl.sum() < 12:
        return None, 0.0
    return M.astype(np.float32), float(inl.mean())


def warp_to_edit(src_a, warp, size):
    w, h = size
    out = cv2.warpAffine(src_a, warp, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=(-1, -1, -1))
    valid = out[..., 0] >= 0
    valid = cv2.erode(valid.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    return np.clip(out, 0, 1), valid


# ---------------------------------------------------------------- masks

RAW_DE_MAX = 8.0     # cast-compensated dE00 above this is a real edit, not drift
LUMA_JUMP_MAX = 10.0  # banana brightens ~0.5 L* per round; a bigger jump is new content or misalignment
COARSE_SIGMA = 6.0    # analysis px: banana re-renders texture but keeps its local mean colour
# a*b* change left once the cast is removed: banana can push a colour further along
# (jeans bluer, skin redder) and tints a wall unevenly (+-1.5 a* across the frame),
# but cannot turn a neutral into a colour (recoloured_backdrops handles regions)
CHROMA_RESID_BASE = 6.0
CHROMA_RESID_PER_C = 0.35
CHROMA_RESID_CAP = 10.0


def structure_mask(src_w, edit, valid, raw_de, box=15):
    """Pixels whose local structure AND rough colour match (cast tolerant)."""
    gs = luma(src_w).astype(np.float32) * 255.0
    ge = luma(edit).astype(np.float32) * 255.0
    k = (box, box)
    ms, me = cv2.blur(gs, k), cv2.blur(ge, k)
    vs = np.maximum(cv2.blur(gs * gs, k) - ms * ms, 0)
    ve = np.maximum(cv2.blur(ge * ge, k) - me * me, 0)
    cov = cv2.blur(gs * ge, k) - ms * me
    ncc = cov / np.sqrt(np.maximum(vs * ve, 1e-6))
    flat = (vs < 6.0) & (ve < 6.0)
    near = np.abs(ms - me) < 20.0
    ok = ((ncc > 0.80) & ~flat) | (flat & near)
    # a recoloured region keeps its structure (e.g. grey sky -> blue sky),
    # so the colour difference itself must also be cast-sized
    ok &= raw_de < RAW_DE_MAX
    changed = valid & ~ok          # what the edit really changed (for paste-back)
    # strong edges amplify residual misregistration: leave them out
    gm = _grad_mag(cv2.GaussianBlur(gs, (0, 0), 1.0))
    edges = gm > np.percentile(gm, 92)
    edges = cv2.dilate(edges.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    ok &= valid & ~edges
    ok = cv2.erode(ok.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    textured = (vs >= 6.0) & (ve >= 6.0)
    return ok, changed, textured


def coarse_structure_mask(src_w, edit, valid, gate_de, sigma=COARSE_SIGMA, box=41, ncc_min=0.85):
    """Areas whose LOCAL MEAN colour can be compared although banana re-rendered
    the texture (skin pores, hair strands, knit, velvet, foliage): the pixel-level
    test above rejects them, but after a strong blur their shading still matches.
    Without them a portrait is fitted on its background wall alone."""
    gs = cv2.GaussianBlur(luma(src_w).astype(np.float32) * 255.0, (0, 0), sigma)
    ge = cv2.GaussianBlur(luma(edit).astype(np.float32) * 255.0, (0, 0), sigma)
    k = (box, box)
    ms, me = cv2.blur(gs, k), cv2.blur(ge, k)
    vs = np.maximum(cv2.blur(gs * gs, k) - ms * ms, 0)
    ve = np.maximum(cv2.blur(ge * ge, k) - me * me, 0)
    ncc = (cv2.blur(gs * ge, k) - ms * me) / np.sqrt(np.maximum(vs * ve, 1e-6))
    flat = (vs < 6.0) & (ve < 6.0)
    ok = ((ncc > ncc_min) & ~flat) | (flat & (np.abs(ms - me) < 20.0))
    ok &= gate_de < RAW_DE_MAX
    # object outlines: a blurred pair mixes both sides of the edge
    gm = _grad_mag(cv2.GaussianBlur(gs, (0, 0), 5.3))
    if valid.any():
        edges = cv2.dilate((gm > np.percentile(gm[valid], 95)).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        ok &= ~edges
    ok &= valid
    ok = cv2.erode(ok.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    return ok, ~flat


# ---------------------------------------------------------------- models

def _pava(y, w):
    """Weighted isotonic (non-decreasing) regression."""
    y = list(map(float, y))
    w = list(map(float, w))
    blocks = []  # [value, weight, count]
    for yi, wi in zip(y, w):
        blocks.append([yi, wi, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            v2, w2, c2 = blocks.pop()
            v1, w1, c1 = blocks.pop()
            wt = w1 + w2
            blocks.append([(v1 * w1 + v2 * w2) / wt, wt, c1 + c2])
    out = []
    for v, _, c in blocks:
        out.extend([v] * c)
    return np.array(out, np.float64)


class Curves:
    """Per-channel monotone tone curves, stored as 1024-entry tables."""

    def __init__(self, tables):
        self.tables = tables  # (3, 1024)

    @staticmethod
    def identity():
        x = np.linspace(0, 1, 1024)
        return Curves(np.stack([x, x, x]))

    @staticmethod
    def fit(X, Y, bins=64, min_count=12):
        xs = np.linspace(0, 1, 1024)
        tables = []
        for c in range(3):
            x, y = X[:, c], Y[:, c]
            idx = np.clip((x * bins).astype(np.int32), 0, bins - 1)
            order = np.argsort(idx, kind="stable")
            idx_s, x_s, y_s = idx[order], x[order], y[order]
            starts = np.searchsorted(idx_s, np.arange(bins))
            ends = np.searchsorted(idx_s, np.arange(bins), side="right")
            px, py, pw = [], [], []
            for b in range(bins):
                n = ends[b] - starts[b]
                if n >= min_count:
                    px.append(float(np.median(x_s[starts[b]:ends[b]])))
                    py.append(float(np.median(y_s[starts[b]:ends[b]])))
                    pw.append(float(n))
            if len(px) < 3:
                tables.append(xs.copy())
                continue
            px, py, pw = np.array(px), _pava(py, pw), np.array(pw)
            t = np.interp(xs, px, py)
            lo, hi = xs < px[0], xs > px[-1]
            t[lo] = py[0] + (xs[lo] - px[0])      # slope-1 extrapolation keeps contrast
            t[hi] = py[-1] + (xs[hi] - px[-1])
            t = cv2.GaussianBlur(t.reshape(1, -1).astype(np.float32), (0, 0), 6).ravel()
            t = np.maximum.accumulate(np.clip(t, 0, 1))
            tables.append(t.astype(np.float64))
        return Curves(np.stack(tables))

    def apply(self, rgb):
        out = np.empty_like(rgb, dtype=np.float32)
        n = self.tables.shape[1] - 1
        for c in range(3):
            t = np.clip(rgb[..., c], 0, 1) * n
            i = np.minimum(t.astype(np.int32), n - 1)
            f = (t - i).astype(np.float32)
            tab = self.tables[c].astype(np.float32)
            out[..., c] = tab[i] * (1 - f) + tab[i + 1] * f
        return out


def _blur3(B, grid):
    """Separable blur of an (n,n,n[,c]) grid along its first three axes."""
    g = np.tensordot(B, grid, axes=(1, 0))
    g = np.moveaxis(np.tensordot(B, g, axes=(1, 1)), 0, 1)
    return np.moveaxis(np.tensordot(B, g, axes=(1, 2)), 0, 2)


def _blur_matrix(n, sigma):
    i = np.arange(n)
    m = np.exp(-((i[:, None] - i[None, :]) ** 2) / (2 * sigma * sigma))
    return m / m.sum(1, keepdims=True)


def _trilinear(coords, n):
    g = np.clip(coords, 0, 1) * (n - 1)
    i0 = np.minimum(np.floor(g).astype(np.int32), n - 2)
    f = g - i0
    return i0, f


class Lut3D:
    """Residual 3D LUT (17^3), splatted, smoothed and shrunk toward zero."""

    def __init__(self, table):
        self.table = table  # (n,n,n,3)

    @staticmethod
    def fit(X, R, n=LUT_N, sigma=0.7, shrink=5.0):
        i0, f = _trilinear(X, n)
        num = np.zeros((n, n, n, 3), np.float64)
        den = np.zeros((n, n, n), np.float64)
        for dz in (0, 1):
            wz = f[:, 0] if dz else 1 - f[:, 0]
            for dy in (0, 1):
                wy = f[:, 1] if dy else 1 - f[:, 1]
                for dx in (0, 1):
                    wx = f[:, 2] if dx else 1 - f[:, 2]
                    w = wz * wy * wx
                    a, b, c = i0[:, 0] + dz, i0[:, 1] + dy, i0[:, 2] + dx
                    np.add.at(den, (a, b, c), w)
                    for ch in range(3):
                        np.add.at(num[..., ch], (a, b, c), w * R[:, ch])
        B = _blur_matrix(n, sigma)
        num = _blur3(B, num)
        den = _blur3(B, den)
        return Lut3D((num / (den[..., None] + shrink)).astype(np.float32))

    def apply(self, rgb, chunk=1 << 20):
        n = self.table.shape[0]
        flat = rgb.reshape(-1, 3)
        out = np.empty_like(flat)
        for s in range(0, flat.shape[0], chunk):
            c = flat[s:s + chunk]
            i0, f = _trilinear(c, n)
            acc = np.zeros_like(c)
            for dz in (0, 1):
                wz = f[:, 0] if dz else 1 - f[:, 0]
                for dy in (0, 1):
                    wy = f[:, 1] if dy else 1 - f[:, 1]
                    for dx in (0, 1):
                        wx = f[:, 2] if dx else 1 - f[:, 2]
                        acc += (wz * wy * wx)[:, None] * self.table[i0[:, 0] + dz, i0[:, 1] + dy, i0[:, 2] + dx]
            out[s:s + chunk] = c + acc
        return np.clip(out.reshape(rgb.shape), 0, 1)


def _splat_counts(X, n):
    i0, f = _trilinear(X, n)
    den = np.zeros((n, n, n), np.float64)
    for dz in (0, 1):
        wz = f[:, 0] if dz else 1 - f[:, 0]
        for dy in (0, 1):
            wy = f[:, 1] if dy else 1 - f[:, 1]
            for dx in (0, 1):
                wx = f[:, 2] if dx else 1 - f[:, 2]
                np.add.at(den, (i0[:, 0] + dz, i0[:, 1] + dy, i0[:, 2] + dx), wz * wy * wx)
    return den


def _interp3(grid, rgb, chunk=1 << 20):
    n = grid.shape[0]
    flat = rgb.reshape(-1, 3)
    out = np.empty(flat.shape[0], np.float32)
    for s in range(0, flat.shape[0], chunk):
        i0, f = _trilinear(flat[s:s + chunk], n)
        acc = np.zeros(i0.shape[0], np.float32)
        for dz in (0, 1):
            wz = f[:, 0] if dz else 1 - f[:, 0]
            for dy in (0, 1):
                wy = f[:, 1] if dy else 1 - f[:, 1]
                for dx in (0, 1):
                    wx = f[:, 2] if dx else 1 - f[:, 2]
                    acc += wz * wy * wx * grid[i0[:, 0] + dz, i0[:, 1] + dy, i0[:, 2] + dx]
        out[s:s + chunk] = acc
    return out.reshape(rgb.shape[:-1])


class LightnessProfile:
    """Median Lab shift (edit - source) as a function of lightness.

    banana's cast is strongly lightness dependent (a* +8 in shadows can come
    with a* +1 in highlights), so one global offset over-corrects whatever
    lightness range it was not measured in. The profile is measured only where
    unchanged pixels exist and decays to zero away from them: a cast seen in
    shadows is never extrapolated into highlights, and vice versa.

    Pixels are binned by the pair's MEAN L* ((L_edit + L_source) / 2). Binning by
    the edit's own L* biases the difference wherever banana re-rendered texture
    (regression to the mean turned a +3.5 L* brightening of a velvet pillow into
    a "-16 L*" cast)."""

    STEP = 5.0

    def __init__(self, centers, shift, support):
        self.centers, self.shift, self.support = centers, shift, support

    @staticmethod
    def fit(Le, Ls, min_count=150, decay=8.0):
        centers = np.arange(0.0, 100.0 + 1e-6, LightnessProfile.STEP)
        n = len(centers)
        prof = np.zeros((n, 3), np.float32)
        ok = np.zeros(n, bool)
        cnt = np.zeros(n)
        if Le.shape[0]:
            L = 0.5 * (Le[:, 0] + Ls[:, 0])
            d = Le - Ls
            for i, c in enumerate(centers):
                sel = np.abs(L - c) <= LightnessProfile.STEP
                cnt[i] = sel.sum()
                if cnt[i] >= min_count:
                    prof[i] = np.median(d[sel], 0)
                    ok[i] = True
        out = np.zeros_like(prof)
        if ok.any():
            idx = np.flatnonzero(ok)
            for i, c in enumerate(centers):
                if ok[i]:
                    out[i] = prof[i]
                else:
                    j = idx[np.argmin(np.abs(centers[idx] - c))]
                    out[i] = prof[j] * np.exp(-0.5 * ((centers[j] - c) / decay) ** 2)
            sm = out.copy()
            sm[1:-1] = 0.25 * out[:-2] + 0.5 * out[1:-1] + 0.25 * out[2:]
            out = sm
            # the L part also reaches colours the fit never saw: it may bend the tone
            # scale only gently (slope 0.85-1.15), never stretch texture contrast
            lim = 0.15 * LightnessProfile.STEP
            anchor = int(idx[np.argmax(cnt[idx])])
            cum = np.concatenate([[0.0], np.cumsum(np.clip(np.diff(out[:, 0]), -lim, lim))])
            out[:, 0] = cum - cum[anchor] + out[anchor, 0]
        return LightnessProfile(centers, out.astype(np.float32), ok)

    def _lookup(self, L):
        return np.stack([np.interp(L, self.centers, self.shift[:, c]) for c in range(3)], -1).astype(np.float32)

    def __call__(self, L_edit):
        """Shift for edit pixels of lightness L_edit, looked up at the pair's mean L*."""
        sh = self._lookup(L_edit)
        for _ in range(2):
            sh = self._lookup(L_edit - 0.5 * sh[..., 0])
        return sh

    def compensate(self, lab):
        """Lab with the measured cast removed (as a function of each pixel's L*)."""
        return lab - self(lab[..., 0])

    def summary(self):
        return {f"L{int(c)}": [round(float(v), 2) for v in self.shift[i]]
                for i, c in enumerate(self.centers) if self.support[i] and int(c) % 20 == 0}


class CastModel:
    """Expected drift of a pixel given its source colour: one lightness profile
    for near-neutral colours and one for coloured ones, blended by the source
    chroma. At the same L*, banana drifts skin and hair about twice as far as a
    grey wall (+5.4 vs +2.8 a* after five Banana 2 rounds), so a single profile
    leaves walls looking 'recoloured' and faces under-explained."""

    def __init__(self, neutral, chroma):
        self.neutral, self.chroma = neutral, chroma

    @staticmethod
    def _merge(primary, fallback):
        sh = np.where(primary.support[:, None], primary.shift, fallback.shift).astype(np.float32)
        return LightnessProfile(primary.centers, sh, primary.support | fallback.support)

    @staticmethod
    def fit(Le, Ls, min_count=2000):
        allp = LightnessProfile.fit(Le, Ls)
        c = np.hypot(Ls[:, 1], Ls[:, 2])
        parts = []
        for m in (c < 8.0, c >= 8.0):
            parts.append(CastModel._merge(LightnessProfile.fit(Le[m], Ls[m]), allp) if m.sum() >= min_count else allp)
        return CastModel(*parts)

    def shift(self, lab_e, lab_s):
        w = np.clip((np.hypot(lab_s[..., 1], lab_s[..., 2]) - 4.0) / 8.0, 0, 1)[..., None]
        return w * self.chroma(lab_e[..., 0]) + (1 - w) * self.neutral(lab_e[..., 0])

    def compensate(self, lab_e, lab_s):
        """lab_e with the drift expected for its source colour removed."""
        return lab_e - self.shift(lab_e, lab_s)


SUPPORT_K = 20.0   # training samples near a colour before the fit is trusted half-way


class Support:
    """How well each colour was represented in the unchanged area (0..1).

    Colours the fit never saw (a new blue sky, a recoloured product, a new
    object) must not receive extrapolated curve corrections; they only get the
    cast measured on unchanged pixels of their kind - neutral or coloured - at
    their own lightness (CastModel).

    The threshold is an absolute sample count. One proportional to the training
    set left small but important regions (a face, a plant) half on the
    lightness-average cast: faces kept their magenta, greens went green."""

    def __init__(self, grid, cast):
        self.grid = grid
        self.cast = cast

    @staticmethod
    def fit(X, Y, n=LUT_N, sigma=0.0):
        if X.shape[0] == 0:
            z = LightnessProfile.fit(np.zeros((0, 3)), np.zeros((0, 3)))
            return Support(np.zeros((n, n, n), np.float32), CastModel(z, z))
        # counts within one LUT cell only: with blurred counts, a big population of
        # light neutrals made a new blue sky two cells away look "seen"
        den = _splat_counts(X, n)
        if sigma > 0:
            B = _blur_matrix(n, sigma)
            den = _blur3(B, den)
        cast = CastModel.fit(rgb_to_lab(X), rgb_to_lab(Y))
        return Support((den / (den + SUPPORT_K)).astype(np.float32), cast)

    def weight(self, rgb):
        return np.clip(_interp3(self.grid, rgb), 0, 1)

    keep_new = False

    def fallback(self, rgb):
        if self.keep_new:
            return rgb
        lab = rgb_to_lab(rgb)
        # the source colour is unknown: the pixel's own chroma picks the neutral or
        # the coloured drift (new objects get the neutral guard in protect_new_neutrals)
        return lab_to_rgb(lab - self.cast.shift(lab, lab))


def _toward_neutral(lab, shift, v_full=6.0, v_none=12.0):
    """lab - shift, but where a* (or b*) is near zero the correction may move it
    toward zero, never across: a cast is removed, not inverted.

    New objects do not reliably carry the cast: a daisy banana drew at a* -0.4,
    or a grey scarf it added two rounds ago (+2.8 while the wall drifted +3.6).
    Removing the full cast of the scene turned such whites and greys green
    (a* -1.6 ... -2.0); a yellow object would go yellow-green the same way.
    Judged per channel, so a bluish-grey scarf (b* -7) is still protected in a*.
    Strongly coloured channels (|value| >= v_none) get the plain shift."""
    out = lab - shift
    for k in (1, 2):
        v, s = lab[..., k], shift[..., k]
        w = np.clip((v_none - np.abs(v)) / (v_none - v_full), 0, 1)
        lim = np.where(s > 0, np.minimum(v, 0), np.maximum(v, 0))
        clipped = np.where(s > 0, np.maximum(v - s, lim), np.minimum(v - s, lim))
        out[..., k] = w * clipped + (1 - w) * out[..., k]
    return out


class SpatialField:
    """Low-frequency per-channel offset field (analysis resolution)."""

    def __init__(self, field):
        self.field = field  # (h,w,3)

    @staticmethod
    def fit(resid_img, mask, sigma_frac=0.12, shrink=0.05):
        h, w = mask.shape
        sigma = sigma_frac * min(h, w)
        m = mask.astype(np.float32)
        den = cv2.GaussianBlur(m, (0, 0), sigma)
        field = np.zeros((h, w, 3), np.float32)
        for c in range(3):
            num = cv2.GaussianBlur(resid_img[..., c] * m, (0, 0), sigma)
            field[..., c] = num / (den + shrink)
        return SpatialField(field)

    def apply(self, rgb):
        h, w = rgb.shape[:2]
        f = cv2.resize(self.field, (w, h), interpolation=cv2.INTER_LINEAR)
        return np.clip(rgb + f, 0, 1)


class ColorModel:
    LEVELS = ("identity", "curves", "curves+lut", "curves+lut+spatial")

    def __init__(self, level, curves=None, lut=None, spatial=None, support=None):
        self.level, self.curves, self.lut, self.spatial = level, curves, lut, spatial
        self.support = support

    def apply(self, rgb, return_weight=False):
        src = rgb.astype(np.float32)
        out = src
        if self.curves is not None:
            out = self.curves.apply(out)
        if self.lut is not None:
            out = self.lut.apply(out)
        if self.spatial is not None:
            out = self.spatial.apply(out)
        w = None
        if self.support is not None:
            w = self.support.weight(src)
            out = w[..., None] * out + (1 - w[..., None]) * self.support.fallback(src)
        return (out, w) if return_weight else out


def fit_model(level, E, S, mask, cast_mask=None, support_mask=None):
    """E, S: (h,w,3) analysis images; mask: pixels used for fitting;
    cast_mask: pixels that estimate the global cast for unseen colours;
    support_mask: pixels that count as 'seen' (default: mask). Pass all inliers
    there - counted on a subsample, a small textured region (denim, 1 % of the
    frame) spread over many colour cells looks only partly seen."""
    if level == "identity":
        return ColorModel(level)
    X, Y = E[mask], S[mask]
    sm = mask if support_mask is None else support_mask
    support = Support.fit(E[sm], S[sm])
    if cast_mask is not None and cast_mask.sum() >= 500:
        support.cast = CastModel.fit(rgb_to_lab(E[cast_mask]), rgb_to_lab(S[cast_mask]))
    curves = Curves.fit(X, Y)
    if level == "curves":
        return ColorModel(level, curves, support=support)
    Xc = curves.apply(X)
    lut = Lut3D.fit(Xc, Y - Xc)
    if level == "curves+lut":
        return ColorModel(level, curves, lut, support=support)
    pred = lut.apply(curves.apply(E))
    spatial = SpatialField.fit(S - pred, mask)
    return ColorModel(level, curves, lut, spatial, support=support)


def _de(a, b):
    return delta_e2000(rgb_to_lab(a).astype(np.float64), rgb_to_lab(b).astype(np.float64))


def _subsample_mask(mask, limit=250_000, seed=0):
    idx = np.flatnonzero(mask)
    if idx.size > limit:
        idx = np.random.RandomState(seed).choice(idx, limit, replace=False)
    m = np.zeros(mask.size, bool)
    m[idx] = True
    return m.reshape(mask.shape)


def drift_like_map(E, S, cand, sig, cast_ab=None, angle=30.0):
    """Regions whose colour moved the way the cast moves: same a*b* direction,
    up to about twice as far (banana drifts skin, wood and hair up to 2x more
    than neutrals, greens less). They are drift even though one global curve
    cannot explain them. An intentional recolour (bluer sky, new shirt colour)
    moves in another direction and stays excluded.

    cast_ab must come from pixels that are certainly unchanged (identical fine
    structure). Measured over all candidates, a large intentional edit (a new
    blue sky over half the frame) drags the "cast" toward itself and then looks
    drift-like."""
    d = rgb_to_lab(E)[..., 1:] - rgb_to_lab(S)[..., 1:]
    g = np.asarray(cast_ab, np.float64) if cast_ab is not None else np.median(d[cand], 0)
    gn = float(np.hypot(g[0], g[1]))
    den = cv2.GaussianBlur(cand.astype(np.float32), (0, 0), sig) + 1e-6
    va = cv2.GaussianBlur(np.where(cand, d[..., 0], 0).astype(np.float32), (0, 0), sig) / den
    vb = cv2.GaussianBlur(np.where(cand, d[..., 1], 0).astype(np.float32), (0, 0), sig) / den
    vn = np.hypot(va, vb)
    near = np.hypot(va - g[0], vb - g[1]) < 2.0
    if gn < 1.0:
        return near | (vn < 2.0)
    cos = (va * g[0] + vb * g[1]) / np.maximum(vn * gn, 1e-6)
    aligned = (cos > np.cos(np.radians(angle))) & (vn < 2.0 * gn + 3.0)
    return aligned | near | (vn < 1.5)


def robust_inliers(E, S, cand, iterations=4, cast_ab=None):
    """Iteratively drop pixels - and coherent regions - that the colour mapping
    cannot explain. Regional exclusion is what protects intentional recolours
    (a bluer sky, a new shirt colour) that are still cast-sized; regions that
    merely drifted more or less than average (drift_like_map) are kept, or the
    face of a portrait would be dropped for being more magenta than the wall."""
    if cand.sum() < 500:
        return cand.copy()
    h, w = cand.shape
    sig = max(2.0, 0.02 * min(h, w))
    m = cand.astype(np.float32)
    den = cv2.GaussianBlur(m, (0, 0), sig) + 1e-6
    drift = drift_like_map(E, S, cand, sig, cast_ab)
    inl = cand.copy()
    for it in range(iterations):
        # later passes add the colour LUT, so colour-specific drift stops looking like an outlier
        model = fit_model("curves" if it == 0 else "curves+lut", E, S, _subsample_mask(inl))
        de = _de(model.apply(E), S)
        med = float(np.median(de[inl])) if inl.any() else 0.0
        regional = cv2.GaussianBlur(np.where(cand, de, 0).astype(np.float32), (0, 0), sig) / den
        thr = max(3.0, 3.0 * med)
        # inside drift-like regions a pixel is judged against its neighbourhood
        pix_ok = (de < thr) | (drift & (de < thr + regional))
        new = cand & pix_ok & ((regional < max(2.0, 1.8 * med)) | drift)
        if new.sum() < 500:
            break
        inl = new
    return inl


def cross_validate(E, S, inl, blocks=6):
    h, w = inl.shape
    yy, xx = np.mgrid[0:h, 0:w]
    fold = ((yy * blocks // h) + (xx * blocks // w)) % 2 == 0
    scores = {}
    for level in ColorModel.LEVELS:
        errs = []
        for k in (True, False):
            train = inl & (fold == k)
            test = inl & (fold != k)
            if train.sum() < 2000 or test.sum() < 2000:
                continue
            m = fit_model(level, E, S, _subsample_mask(train))
            errs.append(float(_de(m.apply(E), S)[test].mean()))
        if errs:
            scores[level] = float(np.mean(errs))
    chosen = "identity"
    for level in ColorModel.LEVELS[1:]:
        if level in scores and scores[level] < scores[chosen] * 0.97:
            chosen = level
    return chosen, scores


def lab_shift(a, b, mask):
    la, lb = rgb_to_lab(a)[mask], rgb_to_lab(b)[mask]
    d = np.median(la - lb, 0)
    return {"dL": round(float(d[0]), 2), "da": round(float(d[1]), 2), "db": round(float(d[2]), 2)}


def _chroma_resid(cast, lab_e, lab_s):
    """|a*b* change| left after removing the expected cast, and the limit a
    drifted pixel of that source colour may reach."""
    r = cast.compensate(lab_e, lab_s)[..., 1:] - lab_s[..., 1:]
    c_src = np.hypot(lab_s[..., 1], lab_s[..., 2])
    limit = np.minimum(CHROMA_RESID_BASE + CHROMA_RESID_PER_C * c_src, CHROMA_RESID_CAP)
    return np.hypot(r[..., 0], r[..., 1]), limit, c_src


def recoloured_backdrops(resid_c, gate_c, c_src, c_src_f, l_src_f, valid):
    """Bright neutral areas of the source (overcast sky, wall, backdrop) that the
    edit turned into a colour, as whole regions. banana's drift cannot give a
    truly neutral source a colour, so where a quarter of such a region clearly
    gained one, the rest of it - the faint fringe, e.g. the pale haze of a new
    blue sky, which pixel by pixel still looks cast-sized - is the edit too.
    Regions are traced on sharp colours (c_src_f, l_src_f) so the haze between
    grass blades stays connected to its sky; the evidence uses the blurred pair."""
    area = valid & (c_src_f < 8.0) & (l_src_f > 55.0)
    strong = area & (c_src < 4.0) & ((gate_c >= RAW_DE_MAX) | (resid_c >= 6.0))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(area.astype(np.uint8), 8)
    if n <= 1 or not strong.any():
        return np.zeros(valid.shape, bool)
    strong_n = np.bincount(lab[strong], minlength=n)
    size = stats[:, cv2.CC_STAT_AREA].astype(np.float64)
    keep = (strong_n >= 0.25 * size) & (size >= 0.005 * valid.size)
    keep[0] = False
    found = keep[lab]
    if found.any():
        # its pieces cut off by foreground (haze between grass blades) count if they
        # are close by, neutral in the source and visibly changed too
        r = max(3, int(0.03 * min(valid.shape)))
        near = cv2.dilate(found.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0
        found |= near & area & (resid_c >= 1.5)
    return found


def _seed_cast(lab_e, lab_s, seed):
    """CastModel and a*b* cast of certainly-unchanged pixels (two passes)."""
    if seed.sum() < 500:
        z = LightnessProfile.fit(np.zeros((0, 3)), np.zeros((0, 3)))
        return CastModel(z, z), None
    cast = CastModel.fit(lab_e[seed], lab_s[seed])
    # second pass without seed pixels the first cast cannot explain
    de = delta_e2000(cast.compensate(lab_e[seed], lab_s[seed]).astype(np.float64), lab_s[seed].astype(np.float64))
    sel = seed.copy()
    if (de < 6.0).sum() >= 500:
        sel[seed] = de < 6.0
        cast = CastModel.fit(lab_e[sel], lab_s[sel])
    return cast, np.median((lab_e - lab_s)[sel][:, 1:], 0)


def fit_pairs(src_w, edit_a, valid, keep=None):
    """Colour pairs to fit on and the pixels that may be used.

    Returns a dict: E, S (one edit/source colour pair per pixel), cand (usable
    pixels), inl (robust inliers), struct_ok / struct_changed / textured (pixel-
    level structure test), cast_ab / cast_dl (a*b* cast and typical L* shift of
    unchanged pixels), chroma95 (95th-percentile chroma of source / edit where the
    structure matches, recoloured backdrops left out), backdrop_share (part of
    the matching structure that is a recoloured backdrop), and
    for inspection resid_c / limit_c (coarse chroma residual and its limit) and
    backdrop (neutral areas the edit recoloured), new_content (no counterpart in
    the source at either scale: new objects)."""
    E1 = cv2.GaussianBlur(edit_a, (0, 0), 1.0)
    S1 = cv2.GaussianBlur(src_w, (0, 0), 1.0)
    e2, s2 = cv2.GaussianBlur(edit_a, (0, 0), 2.0), cv2.GaussianBlur(src_w, (0, 0), 2.0)
    Ec, Sc = cv2.GaussianBlur(edit_a, (0, 0), COARSE_SIGMA), cv2.GaussianBlur(src_w, (0, 0), COARSE_SIGMA)
    lab_e2, lab_s2 = rgb_to_lab(e2), rgb_to_lab(s2)
    lab_ec, lab_sc = rgb_to_lab(Ec), rgb_to_lab(Sc)
    ok0, _, tex0 = structure_mask(src_w, edit_a, valid, np.zeros(valid.shape, np.float32))
    # banana shifts lightness by a few L* at most; a bigger jump is new content or a
    # misaligned outline (and would poison the cast estimate below)
    typ_dl = float(np.median((lab_e2[..., 0] - lab_s2[..., 0])[ok0])) if ok0.any() else 0.0
    jump2 = np.abs(lab_e2[..., 0] - lab_s2[..., 0] - typ_dl) > LUMA_JUMP_MAX
    jumpc = np.abs(lab_ec[..., 0] - lab_sc[..., 0] - typ_dl) > LUMA_JUMP_MAX
    # the cast is measured on textured, structurally identical pixels
    seed = ok0 & ~jump2
    seed = seed & tex0 if (seed & tex0).sum() >= 2000 else seed
    prof0, cast_ab = _seed_cast(lab_e2, lab_s2, seed)
    # an edited backdrop must not take part in the cast estimate either: grass tips
    # in front of a replaced sky make its haze look like textured, unchanged pixels
    c_src_f = np.hypot(lab_s2[..., 1], lab_s2[..., 2])
    backdrop = np.zeros(valid.shape, bool)
    for _ in range(2):
        resid_c, limit_c, c_src = _chroma_resid(prof0, lab_ec, lab_sc)
        gate_c = delta_e2000(prof0.compensate(lab_ec, lab_sc).astype(np.float64), lab_sc.astype(np.float64))
        found = recoloured_backdrops(resid_c, gate_c, c_src, c_src_f, lab_s2[..., 0], valid)
        if not (found & ~backdrop).any():
            break
        backdrop |= found
        prof0, cast_ab = _seed_cast(lab_e2, lab_s2, seed & ~backdrop)
    # Colour gate relative to the cast, not to zero: after several rounds the cast
    # itself reaches dE00 7-9, and an absolute gate would keep only the least drifted
    # pixels (=> under-correction).
    resid_c, limit_c, c_src = _chroma_resid(prof0, lab_ec, lab_sc)
    gate_c = delta_e2000(prof0.compensate(lab_ec, lab_sc).astype(np.float64), lab_sc.astype(np.float64))
    gate_f = delta_e2000(prof0.compensate(lab_e2, lab_s2).astype(np.float64), lab_s2.astype(np.float64))
    struct_ok, struct_changed, textured = structure_mask(src_w, edit_a, valid, gate_f)
    # Chroma gate: removed of its (lightness dependent) cast, banana drift leaves a
    # small a*b* residual - larger only on colours it pushes further (bluer jeans,
    # redder skin). A recolour leaves a big one, even where dE00, which discounts
    # chroma changes of near-greys, still looks cast-sized (pale haze of a new sky).
    resid_f, limit_f, _ = _chroma_resid(prof0, lab_e2, lab_s2)
    coarse_ok, textured_c = coarse_structure_mask(src_w, edit_a, valid, gate_c)
    recoloured = (struct_ok & (resid_f >= limit_f)) | backdrop
    struct_ok &= ~jump2 & ~recoloured
    struct_changed = struct_changed | recoloured
    coarse_ok &= ~jumpc & ~struct_ok & (resid_c < limit_c) & ~backdrop
    if keep is not None:
        struct_ok &= keep
        coarse_ok &= keep
    # one colour pair per pixel: the sharp pair where the structure is identical;
    # where banana re-rendered the texture (faces, hair, denim) the pixel's own
    # colour with the LOCAL MEAN shift as target - training on the means alone
    # never shows the model the light and dark threads it is later applied to
    E = E1
    S = np.where(struct_ok[..., None], S1, np.clip(E1 + (Sc - Ec), 0, 1))
    textured = np.where(struct_ok, textured, textured_c)
    cand = struct_ok | coarse_ok
    inl = robust_inliers(E, S, cand, cast_ab=cast_ab)
    # saturation where the structure matches (new colourful objects do not count),
    # apart from recoloured backdrops (a new blue sky is an edit, not a grey source)
    same = ok0 & valid & ~jump2
    if same.sum() < 2000:
        same = valid
    backdrop_share = float((same & backdrop).sum() / max(1, same.sum()))
    rest = same & ~backdrop
    if rest.sum() < 2000:
        rest = same
    chroma95 = (float(np.percentile(c_src_f[rest], 95)) if rest.any() else 0.0,
                float(np.percentile(np.hypot(lab_e2[..., 1], lab_e2[..., 2])[rest], 95)) if rest.any() else 0.0)
    # content with no counterpart in the source at either scale: new objects
    coarse_same, _ = coarse_structure_mask(src_w, edit_a, valid, np.zeros(valid.shape, np.float32))
    new_content = valid & ~ok0 & ~coarse_same
    new_content = cv2.morphologyEx(new_content.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
    return {"E": E, "S": S, "cand": cand, "inl": inl, "struct_ok": struct_ok, "new_content": new_content,
            "struct_changed": struct_changed, "textured": textured, "cast_ab": cast_ab,
            "cast_dl": typ_dl, "chroma95": chroma95, "backdrop_share": backdrop_share,
            "resid_c": resid_c, "limit_c": limit_c, "backdrop": backdrop}


def protect_new_neutrals(edit, corrected, new_a):
    """Where the edit has content the source lacks (new_a, analysis resolution),
    a near-neutral colour is corrected toward neutral but never past it.

    The colour model works per colour, not per place: a white daisy drawn
    without the cast (a* -0.4) received the correction learned from the
    drifted white T-shirt (a* +2.5) and turned green; a grey scarf added two
    rounds earlier got the stronger drift of the jacket and shadows. Unchanged
    pixels keep the exact model output - the source's own greys may be greenish."""
    h, w = edit.shape[:2]
    a = cv2.GaussianBlur(new_a.astype(np.float32), (0, 0), 2.0)
    if a.max() < 0.01:
        return corrected
    a = np.clip(cv2.resize(a, (w, h), interpolation=cv2.INTER_LINEAR), 0, 1)
    lab_e, lab_c = rgb_to_lab(edit), rgb_to_lab(corrected)
    guarded = _toward_neutral(lab_e, lab_e - lab_c)
    return np.clip(lab_to_rgb(lab_c + a[..., None] * (guarded - lab_c)), 0, 1).astype(np.float32)


# ---------------------------------------------------------------- paste-back

def changed_alpha(changed, de_after, valid):
    """Soft mask (analysis res, edit frame) of regions the edit really changed."""
    h, w = changed.shape
    changed = ((changed | (de_after > 6.0)) & valid).astype(np.uint8)
    k = max(3, int(min(h, w) * 0.004) | 1)
    changed = cv2.morphologyEx(changed, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    changed = cv2.morphologyEx(changed, cv2.MORPH_CLOSE, np.ones((3 * k, 3 * k), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(changed, 8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= 0.0008 * h * w
    changed = keep[lab].astype(np.uint8)
    grow = max(3, int(min(h, w) * 0.015))
    changed = cv2.dilate(changed, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))
    alpha = cv2.GaussianBlur(changed.astype(np.float32), (0, 0), max(1.0, grow * 0.6))
    return np.clip(alpha, 0, 1)


def _scale(sx, sy):
    return np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1]], np.float64)


def source_in_edit_frame(src_full, warp_a, edit_a_size, src_a_size, edit_shape):
    """Warp the (possibly downscaled) source into the full edit frame - for viewing."""
    Hs, Ws = src_full.shape[:2]
    He, We = edit_shape[:2]
    wa, ha = edit_a_size
    sw, sh = src_a_size
    W = np.vstack([warp_a.astype(np.float64), [0, 0, 1]])
    M = np.linalg.inv(_scale(sw / Ws, sh / Hs)) @ W @ _scale(wa / We, ha / He)  # edit full -> source full
    return cv2.warpAffine(src_full.astype(np.float32), M[:2], (We, He),
                          flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)


def paste_back(src_full, edit_corr_full, warp_a, edit_a_size, src_a_size, alpha_a):
    """Composite the edited region into the source frame at source resolution."""
    Hs, Ws = src_full.shape[:2]
    He, We = edit_corr_full.shape[:2]
    wa, ha = edit_a_size
    sw, sh = src_a_size
    S_e = _scale(wa / We, ha / He)             # edit full -> edit analysis
    S_s = _scale(sw / Ws, sh / Hs)             # source full -> source analysis
    W = np.vstack([warp_a.astype(np.float64), [0, 0, 1]])  # edit analysis -> source analysis
    M = np.linalg.inv(S_s) @ W @ S_e            # edit full -> source full
    warped = cv2.warpAffine(edit_corr_full.astype(np.float32), M[:2], (Ws, Hs), flags=cv2.INTER_LANCZOS4,
                            borderMode=cv2.BORDER_REPLICATE)
    Ma = np.linalg.inv(S_s) @ W                  # edit analysis -> source full
    alpha = cv2.warpAffine(alpha_a, Ma[:2], (Ws, Hs), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    alpha = np.clip(alpha, 0, 1)[..., None]
    return np.clip(alpha * warped + (1 - alpha) * src_full, 0, 1), float(alpha.mean())


# ---------------------------------------------------------------- driver

def pick_crops(de_before, inl, size_a, full_shape, count=2):
    """Crops where the UNCHANGED area drifted most (that is what we fix)."""
    h, w = inl.shape
    H, W = full_shape[:2]
    side = int(min(H, W) * 0.22)
    win = max(9, int(side / W * w) | 1)
    dens = cv2.blur(inl.astype(np.float32), (win, win))
    drift = cv2.blur(np.where(inl, de_before, 0).astype(np.float32), (win, win)) / np.maximum(dens, 1e-6)
    # only windows that are mostly unchanged area
    score = np.where(dens >= 0.55, drift * dens, 0).astype(np.float32)
    boxes = []
    for _ in range(count):
        idx = int(np.argmax(score))
        cy, cx = divmod(idx, w)
        if score[cy, cx] <= 0:
            break
        x = int(cx / w * W)
        y = int(cy / h * H)
        x0 = int(np.clip(x - side // 2, 0, W - side))
        y0 = int(np.clip(y - side // 2, 0, H - side))
        boxes.append((x0, y0, x0 + side, y0 + side))
        r = int(0.25 * min(h, w))
        score[max(0, cy - r):cy + r, max(0, cx - r):cx + r] = 0
    return boxes


def match(source_path, edit_path, output_path, strength=100, paste=False, report=None,
          comparison=None, mask_out=None, min_unchanged=0.10, ignore_mask=None, keep_new_colors=False,
          edit_image=None, return_views=False, force_color=False):
    """edit_image: optional (rgb, info) already in memory (e.g. after demaze).
    force_color: correct even when the unchanged area differs far more than any
    banana cast (normally treated as an intentional regrade).
    output_path may be None (nothing written). return_views adds a dict with
    the aligned source / output arrays and crop boxes for custom boards."""
    t0 = time.time()
    edit_full, edit_info = edit_image if edit_image is not None else load_image(edit_path)
    # the source is only needed at full size for --paste-back (it can be 100 MP)
    src_full, src_info = load_image(source_path, max_side=None if paste else 2 * ANALYSIS_SIDE)
    size_a = _analysis_size(edit_full.shape)
    edit_a = _resize(edit_full, size_a)
    res = {"route": "banana-color", "source": str(Path(source_path).resolve()),
           "edit": str(Path(edit_path).resolve())}
    ar_e = edit_full.shape[1] / edit_full.shape[0]
    ar_s = src_full.shape[1] / src_full.shape[0]
    res["aspect_mismatch"] = round(abs(ar_e / ar_s - 1), 4)
    warp, reg_score, reg_kind = None, 0.0, "none"
    if res["aspect_mismatch"] <= 0.03:
        src_a = _resize(src_full, size_a)
        warp, reg_score, reg_kind = register(src_a, edit_a)
    if warp is None or reg_score < 0.6:
        # different framing (crop / outpaint / new aspect): match features instead
        src_a2 = _resize(src_full, _analysis_size(src_full.shape))
        fw, frac_inl = register_features(src_a2, edit_a)
        if fw is not None:
            fscore = _warp_score(cv2.GaussianBlur(luma(src_a2).astype(np.float32), (0, 0), 1.2),
                                 cv2.GaussianBlur(luma(edit_a).astype(np.float32), (0, 0), 1.2), fw)
            if fscore > reg_score:
                warp, reg_score, reg_kind, src_a = fw, fscore, "features", src_a2
    if warp is None:
        src_a = _resize(src_full, size_a)
        warp = np.eye(2, 3, dtype=np.float32)
    src_w, valid = warp_to_edit(src_a, warp, size_a)
    res["registration"] = {
        "kind": reg_kind, "score": round(reg_score, 4),
        "shift_px_analysis": [round(float(warp[0, 2]), 2), round(float(warp[1, 2]), 2)],
        "scale": round(float(np.sqrt(abs(np.linalg.det(warp[:, :2])))), 5),
    }
    keep = None
    if ignore_mask:
        from PIL import Image
        ig = Image.open(ignore_mask).convert("L").resize(size_a, Image.Resampling.NEAREST)
        keep = np.asarray(ig) < 128
    fp = fit_pairs(src_w, edit_a, valid, keep)
    E, S, cand, inl, new_content = fp["E"], fp["S"], fp["cand"], fp["inl"], fp["new_content"]
    struct_ok, struct_changed, textured = fp["struct_ok"], fp["struct_changed"], fp["textured"]
    frac = float(inl.mean())
    res["unchanged_fraction"] = round(frac, 4)
    res["unchanged_rerendered_fraction"] = round(float((inl & ~struct_ok).mean()), 4)
    de_before = _de(E, S)
    res["before"] = {"deltaE00_mean": round(float(de_before[inl].mean()), 3) if inl.any() else None,
                     "deltaE00_p90": round(float(np.percentile(de_before[inl], 90)), 3) if inl.any() else None,
                     "lab_shift_edit_minus_source": lab_shift(E, S, inl) if inl.any() else None}
    tex_area = float((inl & textured).mean())
    lab_s = rgb_to_lab(S)
    neutral = np.hypot(lab_s[..., 1], lab_s[..., 2]) < 15.0
    flat_in = inl & ~textured
    sat_flat = float((flat_in & ~neutral).sum())
    res["unchanged_textured_fraction"] = round(tex_area, 4)
    reason = None
    if frac < min_unchanged or reg_score < 0.3:
        reason = (f"可对照的未改动区域太少（{frac:.0%}）或对齐失败（score={reg_score:.2f}）："
                  "改图与原图构图差异太大，无法可靠估计偏色")
    elif tex_area < 0.03 and sat_flat > float((flat_in & neutral).sum()):
        # a new pose on the same green/magenta screen: only the coloured backdrop
        # "matches", and its shade changes between generations by more than any cast
        reason = (f"对得上的几乎只有彩色纯色背景（如绿幕/品红幕，有纹理部分仅 {tex_area:.0%}）："
                  "更像重新生成而不是局部修改，背景深浅差异不能当作偏色")
    # evidence for the global cast that unseen colours receive: textured content and
    # near-neutral areas (white/grey backdrops, overcast sky), never coloured screens
    cast_mask = inl & (textured | neutral)
    if cast_mask.sum() < 2000:
        cast_mask = inl
    if not reason:
        # a white model / grey render / sketch / desaturated reference carries no colour
        # truth; compared where the structure matches, so new colourful objects do not count
        chroma_s, chroma_e = fp["chroma95"]
        if chroma_e > 15.0 and (chroma_s < 8.0 or chroma_s < 0.6 * chroma_e):
            reason = (f"原图比改图灰得多（结构相同处饱和度 {chroma_s:.0f} 对 {chroma_e:.0f}）："
                      "像白模/灰模/线稿或去色参考，不能作为颜色参考；请用带真实颜色的原图作 --source")
    if not reason and not force_color and fp["cast_ab"] is not None:
        # banana drifts a few units per round (five rounds: a* +8.5); an unchanged area
        # that moved much further was regraded, relit or got a new backdrop on purpose
        dl, ab = fp["cast_dl"], fp["cast_ab"]
        if abs(dl) > 8.0 or float(np.hypot(ab[0], ab[1])) > 12.0:
            reason = (f"未改动区域与原图差得太多（L* {dl:+.1f}，a* {ab[0]:+.1f}，b* {ab[1]:+.1f}），"
                      "远超 banana 的正常偏色，更像有意的整体调色、重新打光或换了背景色；"
                      "确认只是偏色时加 --force-color")
    if reason:
        res["action"] = "no-op"
        res["reason"] = reason
        if output_path:
            save_image(output_path, edit_full, edit_info)
            res["output"] = str(Path(output_path).resolve())
        _write(report, res)
        if return_views:
            return res, {"output": edit_full, "info": edit_info, "src_view": None, "crops": []}
        return res
    if min(inl.shape) >= 256:   # ranking the model levels does not need full analysis size
        half = (inl.shape[1] // 2, inl.shape[0] // 2)
        chosen, cv_scores = cross_validate(cv2.resize(E, half, interpolation=cv2.INTER_AREA),
                                           cv2.resize(S, half, interpolation=cv2.INTER_AREA),
                                           cv2.resize(inl.astype(np.uint8), half, interpolation=cv2.INTER_NEAREST) > 0)
    else:
        chosen, cv_scores = cross_validate(E, S, inl)
    res["model"] = chosen
    res["cv_deltaE00"] = {k: round(v, 3) for k, v in cv_scores.items()}
    if chosen == "identity" or res["before"]["deltaE00_mean"] < 0.5:
        res["action"] = "no-op"
        res["reason"] = "未改动区域的色差已经很小，无需校色"
        out_full = edit_full
        model = ColorModel("identity")
    else:
        model = fit_model(chosen, E, S, _subsample_mask(inl), cast_mask=_subsample_mask(cast_mask), support_mask=inl)
        if model.support is not None:
            model.support.keep_new = keep_new_colors
        corrected = model.apply(edit_full)
        if not keep_new_colors:
            # new objects and recoloured backdrops (a replaced sky) are the edit itself
            corrected = protect_new_neutrals(edit_full, corrected, new_content | fp["backdrop"])
        k = float(np.clip(strength, 0, 100)) / 100.0
        out_full = edit_full + (corrected - edit_full) * k
        res["action"] = "color-match"
        res["strength"] = strength
    after_a = model.apply(E)
    if res["action"] == "color-match" and strength < 100:
        after_a = E + (after_a - E) * (strength / 100.0)
    de_after = _de(after_a, S)
    res["after"] = {"deltaE00_mean": round(float(de_after[inl].mean()), 3),
                    "deltaE00_p90": round(float(np.percentile(de_after[inl], 90)), 3),
                    "lab_shift_edit_minus_source": lab_shift(after_a, S, inl)}
    final_info = edit_info
    if paste and res["action"] == "color-match":
        # changed = structural/colour change + coherent regions the fit rejected
        regional = cand & ~inl
        regional = cv2.morphologyEx(regional.astype(np.uint8), cv2.MORPH_OPEN, np.ones((7, 7), np.uint8)) > 0
        alpha_a = changed_alpha(struct_changed | regional, de_after, valid)
        out_full, edited_share = paste_back(src_full, out_full, warp, size_a,
                                            (src_a.shape[1], src_a.shape[0]), alpha_a)
        res["paste_back"] = {"edited_area_share": round(edited_share, 4),
                             "output_frame": "source", "size": [src_full.shape[1], src_full.shape[0]]}
        final_info = src_info
    if output_path:
        save_image(output_path, out_full, final_info)
        res["output"] = str(Path(output_path).resolve())
    if mask_out:
        vis = np.zeros(inl.shape + (3,), np.float32)
        vis[..., 1] = inl                      # green: used for colour fit
        vis[..., 0] = (~inl) & valid           # red: changed by the edit / excluded
        save_image(mask_out, 0.35 * edit_a + 0.65 * vis, None)
        res["mask"] = str(Path(mask_out).resolve())
    views = None
    if comparison or return_views:
        crops = pick_crops(de_before, inl, size_a, edit_full.shape)
        src_arr = source_in_edit_frame(src_full, warp, size_a, (src_a.shape[1], src_a.shape[0]), edit_full.shape)
        # paste-back output lives in the source frame: bring it into the edit frame like the source
        out_arr = out_full if "paste_back" not in res else source_in_edit_frame(
            out_full, warp, size_a, (src_a.shape[1], src_a.shape[0]), edit_full.shape)
        views = {"output": out_full, "info": final_info, "src_view": src_arr, "out_view": out_arr, "crops": crops}
    if comparison:
        src_view, out_view = to_pil(views["src_view"]), to_pil(views["out_view"])
        b, a = res["before"], res["after"]
        comparison_board(
            comparison,
            "banana 改图偏色校正",
            f"未改动区域 {frac:.0%} · 平均色差 ΔE00 {b['deltaE00_mean']}→{a['deltaE00_mean']} · "
            f"a* 偏移 {b['lab_shift_edit_minus_source']['da']:+.2f}→{a['lab_shift_edit_minus_source']['da']:+.2f}"
            f"（正=偏洋红/红） · 模型 {chosen}",
            [("原图（已对齐）", src_view), ("banana 改图", to_pil(edit_full)), ("校色后", out_view)],
            crops=crops,
        )
        res["comparison"] = str(Path(comparison).resolve())
    res["seconds"] = round(time.time() - t0, 2)
    _write(report, res)
    if return_views:
        return res, views
    return res


def _write(report, res):
    if report:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        Path(report).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Match an edited image's colours back to its source (banana magenta cast).")
    ap.add_argument("source", help="original image the edit was made from")
    ap.add_argument("edit", help="edited image (e.g. nano-banana output)")
    ap.add_argument("output")
    ap.add_argument("--strength", type=float, default=100, help="0-100 blend of the correction (default 100)")
    ap.add_argument("--paste-back", action="store_true",
                    help="output in the source frame: only the edited region comes from the edit")
    ap.add_argument("--report")
    ap.add_argument("--comparison")
    ap.add_argument("--mask-out", help="debug view: green = used for fit, red = changed by edit")
    ap.add_argument("--ignore-mask", help="white = region you edited on purpose; never used for the fit")
    ap.add_argument("--keep-new-colors", action="store_true",
                    help="leave colours that only exist in the edited region exactly as rendered")
    ap.add_argument("--force-color", action="store_true",
                    help="correct even when the difference is far beyond a banana cast (an intentional regrade?)")
    a = ap.parse_args()
    r = match(a.source, a.edit, a.output, a.strength, a.paste_back, a.report, a.comparison, a.mask_out,
              ignore_mask=a.ignore_mask, keep_new_colors=a.keep_new_colors, force_color=a.force_color)
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
