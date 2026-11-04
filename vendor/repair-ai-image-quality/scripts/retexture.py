#!/usr/bin/env python3
"""Fuse a regenerated ("washed") image back into the original GPT render.

An image-edit model (e.g. Nano Banana 2, "keep everything, re-render the fabric
clean") draws real fine texture where GPT drew the maze, but it also adds a
colour cast and may move or redraw small details. This module keeps only what
the wash is good for:

  * colour and everything coarser than ~10 px come from the ORIGINAL
    (Gaussian low-pass, sigma 4 px at 2K: below the maze band);
  * fine luminance detail inside the maze region comes from the WASH, aligned
    to the original frame;
  * wherever the wash changed structure (low-pass luminance differs after
    alignment: a moved button, a redrawn label) the wash is not used and the
    local maze filter fills in;
  * outside the maze region the original is untouched.
"""

import sys
from pathlib import Path

import numpy as np
import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import color_match as cm  # noqa: E402
import gpt_demaze as gd  # noqa: E402
from common import luma  # noqa: E402

LOW_SIGMA = 8.0        # px at full res: crossover below the maze band; close-ups draw worms 10-20 px long
STRUCT_BAND = (3.0, 16.0)  # px: band-pass that sees seams, edges and details but not shading or texture
STRUCT_TOL = 1.6       # band-pass difference, in units of the original's local structure contrast
FLOW_MAX = 24.0        # px: larger local motion means the wash redrew the place, not shifted it
FEATHER = 6.0          # px: soften every mask edge


def _band(L, lo=STRUCT_BAND[0], hi=STRUCT_BAND[1]):
    return cv2.GaussianBlur(L, (0, 0), lo) - cv2.GaussianBlur(L, (0, 0), hi)


def flow_refine(orig, aligned, valid):
    """Dense optical flow (DIS) on low-passed luminance, original -> wash, at half
    resolution: banana shifts seams and shading by a few to tens of pixels."""
    H, W = orig.shape[:2]
    s = 0.5
    def prep(a):
        L = cv2.GaussianBlur(luma(a).astype(np.float32), (0, 0), 2.5)
        L = cv2.resize(L, (int(W * s), int(H * s)), interpolation=cv2.INTER_AREA)
        return np.clip(L * 255, 0, 255).astype(np.uint8)
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    f = dis.calc(prep(orig), prep(aligned), None)
    f = cv2.resize(f, (W, H), interpolation=cv2.INTER_LINEAR) / s
    # flat velvet gives the flow nothing to hold on to: clamp and smooth hard
    mag0 = np.hypot(f[..., 0], f[..., 1])
    f *= np.minimum(1.0, FLOW_MAX / np.maximum(mag0, 1e-6))[..., None]
    f = cv2.GaussianBlur(f, (0, 0), 16.0)
    gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    warped = cv2.remap(aligned.astype(np.float32), gx + f[..., 0], gy + f[..., 1], cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_REPLICATE)
    vmap = cv2.remap(valid.astype(np.float32), gx + f[..., 0], gy + f[..., 1], cv2.INTER_NEAREST, borderValue=0) > 0.5
    mag = np.hypot(f[..., 0], f[..., 1])
    return np.clip(warped, 0, 1), vmap & valid, mag


def align(orig, washed):
    """Warp `washed` into the original's frame. Returns (aligned, valid mask, info)."""
    H, W = orig.shape[:2]
    size_a = cm._analysis_size(orig.shape)
    o_a = cm._resize(orig, size_a)
    w_full = washed
    ar = abs((washed.shape[1] / washed.shape[0]) / (W / H) - 1)
    if ar <= 0.03:
        w_full = cv2.resize(washed, (W, H), interpolation=cv2.INTER_LANCZOS4)
    w_a = cm._resize(w_full, size_a) if ar <= 0.03 else cm._resize(w_full, cm._analysis_size(w_full.shape))
    warp, score, kind = (cm.register(w_a, o_a) if ar <= 0.03 else (None, 0.0, "none"))
    if True:  # banana may zoom or shift the shot: always try feature matching too, keep the better
        fw, _ = cm.register_features(w_a, o_a)
        if fw is not None:
            fs = cm._warp_score(cv2.GaussianBlur(luma(w_a).astype(np.float32), (0, 0), 1.2),
                                cv2.GaussianBlur(luma(o_a).astype(np.float32), (0, 0), 1.2), fw)
            if fs > score:
                warp, score, kind = fw, fs, "features"
    # regenerated texture spoils fine-scale matching: coarse-to-fine ECC on blurred luminance
    if ar <= 0.03:
        cw, cs = coarse_register(w_a, o_a)
        if cw is not None and cs > _blur_score(w_a, o_a, warp if warp is not None else np.eye(2, 3, dtype=np.float32)) + 0.01:
            warp, score, kind = cw, cs, "coarse-ecc"
    if warp is None:
        warp, kind = np.eye(2, 3, dtype=np.float32), "identity"
    # warp maps original-analysis -> wash-analysis coords; lift to full resolution
    Hw, Ww = w_full.shape[:2]
    S_o = cm._scale(size_a[0] / W, size_a[1] / H)
    S_w = cm._scale(w_a.shape[1] / Ww, w_a.shape[0] / Hw)
    M = np.linalg.inv(S_w) @ np.vstack([warp.astype(np.float64), [0, 0, 1]]) @ S_o
    aligned = cv2.warpAffine(w_full.astype(np.float32), M[:2], (W, H),
                             flags=cv2.INTER_LANCZOS4 | cv2.WARP_INVERSE_MAP,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=(-1, -1, -1))
    valid = aligned[..., 0] >= 0
    valid = cv2.erode(valid.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    return np.clip(aligned, 0, 1), valid, {"kind": kind, "score": round(float(score), 4)}


def _blurred(a, sigma=4.0):
    return cv2.GaussianBlur(luma(a).astype(np.float32), (0, 0), sigma)


def _blur_score(w_a, o_a, warp):
    return cm._warp_score(_blurred(w_a), _blurred(o_a), warp)


def coarse_register(w_a, o_a):
    """Affine warp (original-analysis -> wash-analysis) from ECC on a blurred pyramid."""
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-6)
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        for f in (0.25, 0.5, 1.0):
            g1 = cv2.resize(_blurred(w_a, 4.0 / f * 0.5), None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
            g2 = cv2.resize(_blurred(o_a, 4.0 / f * 0.5), None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
            w = warp.copy(); w[:, 2] *= f
            _, w = cv2.findTransformECC(g2, g1, w, cv2.MOTION_AFFINE, crit, None, 5)
            warp = w.copy(); warp[:, 2] /= f
    except cv2.error:
        return None, 0.0
    return warp, _blur_score(w_a, o_a, warp)


def detail_mask(orig, sigma=1.5, win=5.0):
    """Product details to keep from the ORIGINAL: stitching, seams, outlines, buttons,
    lettering. They are oriented (coherent structure tensor) and high-contrast; the maze
    is isotropic, so it does not qualify. Returns a soft 0..1 map."""
    L = cv2.GaussianBlur(luma(orig).astype(np.float32), (0, 0), sigma)
    gx = cv2.Sobel(L, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(L, cv2.CV_32F, 0, 1, ksize=3)
    jxx = cv2.GaussianBlur(gx * gx, (0, 0), win)
    jyy = cv2.GaussianBlur(gy * gy, (0, 0), win)
    jxy = cv2.GaussianBlur(gx * gy, (0, 0), win)
    tr = jxx + jyy
    disc = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2)
    coherence = disc / np.maximum(tr, 1e-8)                    # 1 = one orientation, 0 = isotropic
    energy = np.sqrt(tr)
    # contrast relative to the surface around it: a seam stands out of the velvet
    ref = np.sqrt(cv2.GaussianBlur(tr, (0, 0), 24.0)) + 1e-4
    strong = energy / ref
    m = np.clip((coherence - 0.55) / 0.2, 0, 1) * np.clip((strong - 1.3) / 0.7, 0, 1)
    m = cv2.dilate(m, np.ones((5, 5), np.uint8))
    return np.clip(cv2.GaussianBlur(m, (0, 0), 2.0) * 1.5, 0, 1).astype(np.float32)


def crossover_sigma(orig, aligned, region, lo=LOW_SIGMA, hi=12.0):
    """Low-pass radius that removes the maze AS DRAWN IN THIS IMAGE. The worms are
    4-6 px wide on a full product shot but twice that on a close-up, where a 4 px
    low-pass would hand the original's worms straight back. Measured from what the
    wash removed: the peak wavelength of (original - wash) inside the maze region."""
    d = (luma(orig) - luma(aligned)).astype(np.float32)
    ys, xs = np.nonzero(region)
    if len(ys) < 256 * 256:
        return lo
    cy, cx = int(np.median(ys)), int(np.median(xs))
    H, W = d.shape
    n = 512 if min(H, W) >= 512 else 256
    y0, x0 = int(np.clip(cy - n // 2, 0, H - n)), int(np.clip(cx - n // 2, 0, W - n))
    t = d[y0:y0 + n, x0:x0 + n]
    t = (t - t.mean()) * np.outer(np.hanning(n), np.hanning(n))
    P = np.abs(np.fft.fft2(t)) ** 2
    r = np.hypot(*np.meshgrid(np.fft.fftfreq(n), np.fft.fftfreq(n), indexing="ij"))
    bins = np.linspace(0.02, 0.5, 49)
    idx = np.digitize(r.ravel(), bins)
    prof = np.bincount(idx, P.ravel(), minlength=len(bins) + 1)[1:len(bins)] / np.maximum(np.bincount(idx, minlength=len(bins) + 1)[1:len(bins)], 1)
    f = 0.5 * (bins[:-1] + bins[1:])[int(np.argmax(prof * (0.5 * (bins[:-1] + bins[1:]))))]   # weight away the DC tail
    # a Gaussian of sigma 0.4 / f leaves < 5 % of that wavelength
    return float(np.clip(0.4 / max(f, 1e-3), lo, hi))


def _feather(m, sigma=FEATHER):
    return np.clip(cv2.GaussianBlur(m.astype(np.float32), (0, 0), sigma), 0, 1)


def fuse(orig, washed, info=None, src_path="", strength=60, local=None):
    """orig, washed: float32 RGB 0..1. Returns (output, report).

    local: optional precomputed local-filter output (same shape as orig) used where
    the wash cannot be trusted; computed with gpt_demaze.process when None."""
    info = info or {}
    Y = luma(orig).astype(np.float32) * 255.0
    conf, dinfo = gd.maze_detect(Y)
    pres = gd.presence_map(conf, Y.shape, k=0.25)          # a little wider than the local filter
    aligned0, valid0, reg = align(orig, washed)
    aligned1, valid1, _ = flow_refine(orig, aligned0, valid0)
    Lo_full = luma(orig).astype(np.float32)
    Bo = _band(Lo_full)
    contrast = np.sqrt(cv2.GaussianBlur(Bo * Bo, (0, 0), 24.0)) + 0.006

    def score(al, va):
        Lw = luma(al).astype(np.float32)
        sel = va & (pres > 0.5)
        gain = float(np.median(Lo_full[sel]) / max(np.median(Lw[sel]), 1e-3)) if sel.any() else 1.0
        Bw = _band(Lw * gain)
        return np.abs(Bw - Bo) / contrast, Bw, gain
    d0, B0, g0 = score(aligned0, valid0)
    d1, B1, g1 = score(aligned1, valid1)
    # per region, keep whichever alignment agrees better with the original's structure
    use_flow = cv2.GaussianBlur((d1 < d0).astype(np.float32), (0, 0), 24.0) > 0.5
    aligned = np.where(use_flow[..., None], aligned1, aligned0)
    valid = np.where(use_flow, valid1, valid0)
    diff = np.where(use_flow, d1, d0)
    Bw = np.where(use_flow, B1, B0)
    gain = g1 if use_flow.mean() > 0.5 else g0
    # structural agreement: seams, edges, buttons, lettering (band-pass), not shading or texture
    changed = (diff > STRUCT_TOL) & (np.maximum(np.abs(Bo), np.abs(Bw)) > 0.012)
    changed = cv2.morphologyEx(changed.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    changed = (cv2.dilate(changed, np.ones((21, 21), np.uint8)) > 0) & valid
    trust = valid & ~changed
    keep = detail_mask(orig)                                   # details stay as in the original
    alpha = _feather(pres * trust) * (1.0 - keep)
    # fine luminance detail from the wash, everything coarser (and all colour) from the original
    sig = LOW_SIGMA   # crossover_sigma() kept for diagnostics; a fixed 8 px proved more reliable
    lo_o = cv2.GaussianBlur(orig.astype(np.float32), (0, 0), sig)
    Yw = luma(aligned).astype(np.float32) * gain
    hp_w = Yw - cv2.GaussianBlur(Yw, (0, 0), sig)
    fused = np.clip(lo_o + hp_w[..., None], 0, 1)
    out = alpha[..., None] * fused + (1 - alpha[..., None]) * orig
    # inside the maze region where the wash was rejected: local maze filter
    fallback = _feather(pres * ~trust) * (1.0 - keep)
    if fallback.max() > 0.05:
        if local is None:
            local, _, _ = gd.process(orig, info, src_path or "x_gpt-image.png", strength, force=False, model="gpt")
        out = fallback[..., None] * local + (1 - fallback[..., None]) * out
    out = np.clip(out, 0, 1).astype(np.float32)
    # report
    Yo = luma(out).astype(np.float32) * 255.0
    f0, c0 = gd.maze_index(Y)
    f1, _ = gd.maze_index(Yo)
    m = c0 > 0.5
    in_maze = pres > 0.5
    rep = {"maze_score": dinfo["maze_score"], "registration": reg, "crossover_sigma": round(sig, 2),
           "maze_region_fraction": round(float(in_maze.mean()), 4),
           "detail_kept_fraction": round(float((keep > 0.5)[in_maze].mean()) if in_maze.any() else 0.0, 4),
           "wash_used_fraction": round(float((alpha > 0.5)[in_maze].mean()) if in_maze.any() else 0.0, 4),
           "wash_rejected_fraction": round(float((~trust)[in_maze].mean()) if in_maze.any() else 0.0, 4),
           "maze_bump_before": round(float(np.median(f0["m"][m])), 2) if m.any() else None,
           "maze_bump_after": round(float(np.median(f1["m"][m])), 2) if m.any() else None,
           "colour_shift_255": round(float(np.abs(cv2.GaussianBlur(out, (0, 0), 8) - cv2.GaussianBlur(orig, (0, 0), 8)).mean() * 255), 3),
           "outside_change_255": round(float(np.abs(out - orig)[~in_maze].mean() * 255), 3) if (~in_maze).any() else 0.0}
    return out, rep
