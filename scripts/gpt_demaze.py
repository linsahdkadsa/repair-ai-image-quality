#!/usr/bin/env python3
"""Remove the GPT-image "maze / worm" texture noise.

GPT image models (gpt-image-1 / 2 / 2.5) often render surfaces such as velvet,
knitwear, foam, skin and walls with an isotropic labyrinth pattern whose
wavelength is 4-10 px. In the spectrum it is a bump at 0.2-0.5 x Nyquist
followed by a cliff (almost no energy above ~0.55 x Nyquist).

Detection works on overlapping 32x32 luminance tiles: measure each tile's
radial power spectrum and score how much it looks like the GPT maze (mid-band
bump + cliff + isotropy). Real textures with energy above the cliff or with a
dominant orientation (weave, knit, hair, text) score low.

Removal (luminance only - colour is kept):
  * default: a small U-Net trained on real GPT maze (models/gpt_maze_unet.onnx,
    run by OpenCV's DNN module) predicts the maze and subtracts it, inside a
    smoothed map of where the maze was detected (training/ has the recipe);
  * fallback when the model cannot run: per-tile spectral subtraction of the
    bump power with a floor, keeping strong oriented coefficients (edges,
    lines), weighted overlap-add back.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import comparison_board, load_image, luma, save_image, to_pil  # noqa: E402

try:
    import cv2
except ImportError:  # pragma: no cover - cv2 is in requirements, keep a slow fallback
    cv2 = None

TILE = 32
HOP = 8
# Averaged maze power profile per integer ring k (r = k / 16 of Nyquist),
# measured on gpt-image-2.5 velvet/knit renders. Used as a prior.
DEFAULT_PROFILE = {2: 0.03, 3: 0.18, 4: 0.42, 5: 0.68, 6: 0.97, 7: 0.93, 8: 0.62, 9: 0.17}
BAND_RINGS = range(2, 11)
HARMONIC_TAPER = {10: 0.0, 11: 0.1, 12: 0.3, 13: 0.55, 14: 0.8}


def _blur(a, sigma):
    if sigma <= 0:
        return a
    if cv2 is not None:
        return cv2.GaussianBlur(a.astype(np.float32), (0, 0), sigma, borderType=cv2.BORDER_REFLECT)
    from PIL import Image, ImageFilter  # fallback, 8-bit precision is fine for maps
    lo, hi = float(a.min()), float(a.max())
    if hi - lo < 1e-12:
        return a
    im = Image.fromarray(np.uint8(np.clip((a - lo) / (hi - lo) * 255, 0, 255)))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(sigma)), np.float32) / 255 * (hi - lo) + lo


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


class _Grid:
    """Tiling geometry: 16 interleaved phases of non-overlapping tiles."""

    def __init__(self, shape, tile=TILE, hop=HOP):
        self.tile, self.hop, self.n = tile, hop, tile // hop
        self.H, self.W = shape
        self.pad = tile
        self.Hp = self.H + 3 * tile
        self.Wp = self.W + 3 * tile
        w1 = np.sin(np.pi * (np.arange(tile) + 0.5) / tile).astype(np.float32)
        self.win = np.outer(w1, w1)
        fy = np.fft.fftfreq(tile)[:, None]
        fx = np.fft.rfftfreq(tile)[None, :]
        r = np.hypot(fy, fx) / 0.5
        self.ring = np.rint(r * (tile / 2)).astype(np.int32)
        self.K = int(self.ring.max()) + 1
        ang = np.mod(np.arctan2(fy, fx), np.pi)
        sector = np.minimum((ang / np.pi * 8).astype(np.int32), 7)
        mid = (r >= 0.25) & (r <= 0.5)
        # sorted index tables for fast per-ring / per-sector means
        flat_ring = self.ring.ravel()
        self.ring_order = np.argsort(flat_ring, kind="stable")
        counts = np.bincount(flat_ring, minlength=self.K)
        self.ring_starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
        self.ring_counts = np.maximum(counts, 1).astype(np.float32)
        sec_flat = np.where(mid.ravel(), sector.ravel(), -1)
        sel = np.nonzero(sec_flat >= 0)[0]
        self.sec_order = sel[np.argsort(sec_flat[sel], kind="stable")]
        sc = np.bincount(sec_flat[sel], minlength=8)
        self.sec_starts = np.concatenate([[0], np.cumsum(sc)[:-1]])
        self.sec_counts = np.maximum(sc, 1).astype(np.float32)
        phases = []
        for py in range(self.n):
            for px in range(self.n):
                y0, x0 = py * hop, px * hop
                phases.append((py, px, y0, x0, (self.Hp - y0) // tile, (self.Wp - x0) // tile))
        self.phases = phases
        self.NY = max(p[4] for p in phases) * self.n
        self.NX = max(p[5] for p in phases) * self.n

    def padded(self, Y):
        p = self.pad
        return np.pad(Y, ((p, 2 * p), (p, 2 * p)), mode="reflect").astype(np.float32)

    def tiles(self, Yp, y0, x0, ny, nx):
        t = self.tile
        return Yp[y0:y0 + ny * t, x0:x0 + nx * t].reshape(ny, t, nx, t).transpose(0, 2, 1, 3)

    def ring_means(self, P):
        flat = P.reshape(P.shape[:2] + (-1,))[..., self.ring_order]
        return np.add.reduceat(flat, self.ring_starts, axis=-1) / self.ring_counts

    def sector_means(self, P):
        flat = P.reshape(P.shape[:2] + (-1,))[..., self.sec_order]
        return np.add.reduceat(flat, self.sec_starts, axis=-1) / self.sec_counts


def _spectra(grid, Yp):
    RP = np.zeros((grid.NY, grid.NX, grid.K), np.float32)
    SEC = np.zeros((grid.NY, grid.NX, 8), np.float32)
    n = grid.n
    for py, px, y0, x0, ny, nx in grid.phases:
        tl = grid.tiles(Yp, y0, x0, ny, nx)
        F = np.fft.rfft2((tl - tl.mean((-1, -2), keepdims=True)) * grid.win)
        P = F.real ** 2 + F.imag ** 2
        RP[py::n, px::n][:ny, :nx] = grid.ring_means(P)
        SEC[py::n, px::n][:ny, :nx] = grid.sector_means(P)
    return RP, SEC


def _features(grid, RP, SEC):
    k = np.arange(grid.K, dtype=np.float32)
    nat = np.zeros(grid.K, np.float32)
    nat[1:] = (k[1:] / (grid.tile / 2)) ** -2.0
    A = RP[..., 1] / nat[1]
    mid = [k_ for k_ in range(grid.K) if 0.25 <= k_ / 16 <= 0.47]
    hi = [k_ for k_ in range(grid.K) if 0.56 <= k_ / 16 <= 0.70]
    up = [k_ for k_ in range(grid.K) if 0.37 <= k_ / 16 <= 0.50]
    e_mid = RP[..., mid].mean(-1)
    m = e_mid / np.maximum(A * nat[mid].mean(), 1e-6)
    c = RP[..., hi].mean(-1) / np.maximum(RP[..., up].mean(-1), 1e-6)
    an = SEC.max(-1) / np.maximum(SEC.mean(-1), 1e-6)
    # peak position: the maze keeps rising up to ~0.4 x Nyquist, natural
    # texture (even sharp camera texture) already falls steeply there
    q = RP[..., 6:8].mean(-1) / np.maximum(RP[..., 3:5].mean(-1), 1e-6)
    return {"A": A, "nat": nat, "m": m, "c": c, "an": an, "e": e_mid, "q": q}


def maze_confidence(f):
    """Soft per-tile probability that the mid-band energy is GPT maze texture."""
    bump = _sigmoid((np.log(np.maximum(f["m"], 1e-6)) - np.log(2.5)) / 0.35)
    cliff = _sigmoid((0.18 - f["c"]) / 0.025)
    iso = _sigmoid((3.3 - f["an"]) / 0.35)
    peak = _sigmoid((f["q"] - 0.38) / 0.06)
    active = np.clip((f["e"] - 100.0) / 300.0, 0.0, 1.0)
    return bump * cliff * iso * peak * active


def _profile(grid, RP, f, conf):
    prior = np.zeros(grid.K, np.float32)
    for k, v in DEFAULT_PROFILE.items():
        prior[k] = v
    sel = conf > 0.6
    if sel.sum() < 50:
        return prior, "default"
    ratio = RP[sel] / np.maximum(f["A"][sel, None] * f["nat"][None, :], 1e-6)
    measured = np.maximum(np.median(ratio, 0) - 1.0, 0.0)
    keep = np.zeros(grid.K, bool)
    keep[list(BAND_RINGS)] = True
    measured = np.where(keep, measured, 0.0)
    if measured.max() <= 0:
        return prior, "default"
    measured = measured / measured.max()
    return (0.5 * measured + 0.5 * prior).astype(np.float32), "image+prior"


def strength_params(strength):
    s = float(np.clip(strength, 0, 100))
    alpha = s / 30.0                     # 60 -> 2.0 over-subtraction
    gmin = max(0.08, 0.30 - s / 400.0)   # 60 -> 0.15 floor
    return alpha, gmin


def demaze_luma(Y, strength=60, mask=None):
    """Y: float32 luminance in 0..255. mask: optional protect map (1 = keep)."""
    grid = _Grid(Y.shape)
    Yp = grid.padded(Y)
    RP, SEC = _spectra(grid, Yp)
    f = _features(grid, RP, SEC)
    conf = maze_confidence(f)
    S, profile_source = _profile(grid, RP, f, conf)
    resid = RP - f["A"][..., None] * f["nat"][None, None, :]
    B = np.maximum((resid * S).sum(-1) / max(float((S * S).sum()), 1e-6), 0.0)
    drive = _blur(conf * B, grid.n)
    alpha, gmin = strength_params(strength)
    maze_power = drive[..., None] * S[None, None, :]
    g_ring = np.sqrt(np.clip(1.0 - alpha * maze_power / np.maximum(RP, 1e-6), gmin * gmin, 1.0))
    # Harmonics: the maze has sharp-walled cells, so its 2nd harmonic sits just
    # above the cliff (0.62-0.8 x Nyquist). Once the fundamental is gone it would
    # show up as a fine cross-hatch, so attenuate it in step with the fundamental.
    g_fund = g_ring[..., 5:9].mean(-1)
    conf_s = _blur(conf, grid.n)
    for k, taper in HARMONIC_TAPER.items():
        if k < grid.K:
            gh = g_fund + (1.0 - g_fund) * taper
            g_ring[..., k] = np.minimum(g_ring[..., k], 1.0 - conf_s * (1.0 - gh))
    # protection threshold per tile: oriented tiles protect strong coefficients
    an = f["an"]
    prot = np.interp(an, [2.5, 3.5], [30.0, 6.0]).astype(np.float32)

    out = np.zeros_like(Yp)
    norm = np.zeros_like(Yp)
    t, n = grid.tile, grid.n
    w2 = grid.win * grid.win
    for py, px, y0, x0, ny, nx in grid.phases:
        tl = grid.tiles(Yp, y0, x0, ny, nx)
        mean = tl.mean((-1, -2), keepdims=True)
        F = np.fft.rfft2((tl - mean) * grid.win)
        g = g_ring[py::n, px::n][:ny, :nx]
        if np.all(g >= 0.999):
            back = (tl - mean) * grid.win
        else:
            P = F.real ** 2 + F.imag ** 2
            ring_mean = RP[py::n, px::n][:ny, :nx][..., grid.ring]
            thr = prot[py::n, px::n][:ny, :nx][..., None, None]
            G = g[..., grid.ring]
            over = np.clip((P / np.maximum(ring_mean, 1e-6) - thr) / thr, 0.0, 1.0)
            G = G + (1.0 - G) * over
            back = np.fft.irfft2(F * G, s=(t, t))
        back = (back + mean * grid.win) * grid.win
        out[y0:y0 + ny * t, x0:x0 + nx * t] += back.transpose(0, 2, 1, 3).reshape(ny * t, nx * t)
        norm[y0:y0 + ny * t, x0:x0 + nx * t] += np.tile(w2, (ny, nx))
    res = (out / np.maximum(norm, 1e-6))[grid.pad:grid.pad + grid.H, grid.pad:grid.pad + grid.W]
    if mask is not None:
        res = res * (1.0 - mask) + Y * mask
    active = f["e"] > 250
    info = {
        "maze_score": float((conf[active] > 0.5).mean()) if active.any() else 0.0,
        "maze_area_fraction": float((conf > 0.5).mean()),
        "profile_source": profile_source,
        "over_subtraction": round(alpha, 3),
        "gain_floor": round(gmin, 3),
    }
    return res.astype(np.float32), conf, info


def maze_detect(Y):
    """Detection only (no filtering): per-tile confidence and the summary numbers."""
    grid = _Grid(Y.shape)
    RP, SEC = _spectra(grid, grid.padded(Y))
    f = _features(grid, RP, SEC)
    conf = maze_confidence(f)
    active = f["e"] > 250
    return conf, {
        "maze_score": float((conf[active] > 0.5).mean()) if active.any() else 0.0,
        "maze_area_fraction": float((conf > 0.5).mean()),
    }


def maze_index(Y):
    """Median mid-band bump of maze-like tiles; ~1 means natural spectrum."""
    grid = _Grid(Y.shape, hop=16)
    RP, SEC = _spectra(grid, grid.padded(Y))
    f = _features(grid, RP, SEC)
    conf = maze_confidence(f)
    return f, conf


def edge_preservation(Y0, Y1):
    """Correlation of strong-edge gradient magnitude at object scale.

    sigma=3 averages the 4-10 px maze out, so the metric watches silhouettes,
    seams and lettering rather than the texture we deliberately remove."""
    if cv2 is None:
        return None
    a = cv2.GaussianBlur(Y0, (0, 0), 3.0)
    b = cv2.GaussianBlur(Y1, (0, 0), 3.0)
    ga = np.hypot(cv2.Sobel(a, cv2.CV_32F, 1, 0), cv2.Sobel(a, cv2.CV_32F, 0, 1))
    gb = np.hypot(cv2.Sobel(b, cv2.CV_32F, 1, 0), cv2.Sobel(b, cv2.CV_32F, 0, 1))
    m = ga >= np.percentile(ga, 90)
    if m.sum() < 100:
        return 1.0
    return float(np.corrcoef(ga[m], gb[m])[0, 1])


def pick_crops(conf_map, shape, count=2, size=None):
    H, W = shape
    size = size or max(96, min(256, min(H, W) // 6))
    cm = conf_map.copy()
    gy, gx = cm.shape
    boxes = []
    for _ in range(count):
        idx = int(np.argmax(cm))
        cy, cx = divmod(idx, gx)
        if cm[cy, cx] <= 0.05:
            break
        y = int(cy * HOP - TILE + TILE / 2)
        x = int(cx * HOP - TILE + TILE / 2)
        x0 = int(np.clip(x - size // 2, 0, W - size))
        y0 = int(np.clip(y - size // 2, 0, H - size))
        boxes.append((x0, y0, x0 + size, y0 + size))
        r = max(4, size // HOP)
        cm[max(0, cy - r):cy + r, max(0, cx - r):cx + r] = 0
    return boxes


# ---------------------------------------------------------------- learned filter

MODEL_PATH = Path(__file__).resolve().parent / "models" / "gpt_maze_unet.onnx"
_NET = {}


def _net():
    """The maze model (ONNX, run by OpenCV's DNN module), or None if unavailable."""
    if "net" not in _NET:
        _NET["net"] = None
        if cv2 is not None and MODEL_PATH.exists():
            try:
                _NET["net"] = cv2.dnn.readNetFromONNX(str(MODEL_PATH))
            except (cv2.error, AttributeError):   # no DNN module / unsupported layer
                _NET["net"] = None
    return _NET["net"]


def cnn_luma(Y, tile=1024, pad=32):
    """Y: float32 luminance 0..255 -> the model's maze-free luminance (same scale).

    A small U-Net trained on real GPT maze texture (harvested from GPT renders)
    added to clean photos and AI images; it predicts the maze and subtracts it.
    Tiled with overlap so memory stays flat at 4K."""
    net = _net()
    H, W = Y.shape
    X = (Y / 255.0).astype(np.float32)
    out = np.empty_like(X)
    for y0 in range(0, H, tile):
        for x0 in range(0, W, tile):
            y1, x1 = min(H, y0 + tile), min(W, x0 + tile)
            ya, xa, yb, xb = max(0, y0 - pad), max(0, x0 - pad), min(H, y1 + pad), min(W, x1 + pad)
            t = X[ya:yb, xa:xb]
            ph, pw = (-t.shape[0]) % 4, (-t.shape[1]) % 4
            tp = np.pad(t, ((0, ph), (0, pw)), mode="reflect")
            net.setInput(tp[None, None])
            o = net.forward()[0, 0]
            out[y0:y1, x0:x1] = o[y0 - ya:y1 - ya, x0 - xa:x1 - xa]
    return out * 255.0


def presence_map(conf, shape, sigma_tiles=4.0, k=0.35):
    """Pixel map (0..1) of where the maze is, as a REGION property.

    Per-tile detection on 32 px tiles is noisy: inside a velvet surface it
    leaves salt-and-pepper holes, and every hole stayed unfiltered next to
    filtered neighbours - the blotchy look. Normalised smoothing fills them."""
    dens = _blur(conf.astype(np.float32), sigma_tiles)
    reg = np.clip(dens / k, 0.0, 1.0)
    H, W = shape
    up = cv2.resize(reg, (reg.shape[1] * HOP, reg.shape[0] * HOP), interpolation=cv2.INTER_LINEAR)
    off = TILE // 2
    up = np.pad(up, ((0, max(0, H + off - up.shape[0])), (0, max(0, W + off - up.shape[1]))), mode="edge")
    return np.clip(up[off:off + H, off:off + W], 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------- upscale grid

GRID_PERIODS = ((2, 8.0), (4, 12.0), (8, 16.0))


def periodic_z(Y, p):
    """How strongly a fixed-phase period-p pattern stands out of the high-pass
    (z ~ 1 for natural content, tens to hundreds for an upscaler grid)."""
    hp = Y - _blur(Y, 1.5)
    h, w = Y.shape
    hh, ww = (h // p) * p, (w // p) * p
    blk = hp[:hh, :ww].reshape(hh // p, p, ww // p, p).mean((0, 2))
    blk = blk - blk.mean()
    n = (hh // p) * (ww // p)
    return float(np.sqrt((blk ** 2).mean()) * np.sqrt(n) / max(float(hp.std()), 1e-6))


def _phase_consistency(Y, p=2, block=64):
    """Share of blocks whose local period-p signature agrees with the global one.
    A fixed upscaler grid agrees everywhere; JPEG blocking or texture does not."""
    hp = Y - _blur(Y, 1.0)
    h, w = Y.shape
    H, W = (h // block) * block, (w // block) * block
    q = hp[:H, :W].reshape(H // block, block // p, p, W // block, block // p, p)
    local = q.mean((1, 4))                       # (by, p, bx, p)
    local = local - local.mean((1, 3), keepdims=True)
    glob = local.mean((0, 2))
    agree = (local * glob[None, :, None, :]).sum((1, 3))
    # flat / clipped blocks (white seamless backgrounds) carry no evidence either way
    energy = hp[:H, :W].reshape(H // block, block, W // block, block).std((1, 3))
    busy = energy > 0.3
    if busy.sum() < 8:
        return 0.0
    return float((agree[busy] > 0).mean())


def _degrid_channel(ch, period, sigma):
    """Remove a fixed-phase periodic pattern: global phase signature x local gain."""
    h, w = ch.shape
    H, W = (h // period) * period, (w // period) * period
    hp = ch - _blur(ch, 1.0 if period == 2 else period / 2)
    sig = hp[:H, :W].reshape(H // period, period, W // period, period).mean((0, 2))
    sig = sig - sig.mean()
    A = np.tile(sig, (h // period + 1, w // period + 1))[:h, :w].astype(np.float32)
    gain = _blur(hp * A, sigma) / (_blur(A * A, sigma) + 1e-9)
    return ch - np.clip(gain, 0.0, 4.0) * A


def degrid(rgb255, force=False, is_gpt=False):
    """Detect and remove the 2/4/8-px grid some GPT pipelines leave when they
    upscale to 2K/4K. Returns (rgb255, info)."""
    Y = luma(rgb255)
    z = {p: round(periodic_z(Y, p), 1) for p, _ in GRID_PERIODS}
    cons = round(_phase_consistency(Y), 3)
    thr = 20.0 if is_gpt else 40.0
    detected = force or (z[2] >= thr and cons >= 0.8)
    info = {"fold_z_before": z, "phase_consistency": cons, "applied": bool(detected)}
    if not detected:
        return rgb255, info
    out = rgb255.astype(np.float32).copy()
    for c in range(3):
        for p, sg in GRID_PERIODS:
            out[..., c] = _degrid_channel(out[..., c], p, sg)
    Yo = luma(out)
    info["fold_z_after"] = {p: round(periodic_z(Yo, p), 1) for p, _ in GRID_PERIODS}
    info["mean_change_255"] = round(float(np.abs(out - rgb255).mean()), 3)
    return out, info


GPT_NAME_HINTS = ("gpt-image", "gpt_image", "gptimage", "gpt-4o", "chatgpt", "openai", "dall-e", "dalle")


def looks_like_gpt(path, model=None):
    if model:
        return model.lower().startswith(("gpt", "openai", "dall"))
    name = Path(path).name.lower()
    return any(h in name for h in GPT_NAME_HINTS)


def pre_gate(shape, info, is_gpt, force):
    """Cheap checks before any spectral work. Returns reason to skip or None."""
    if force or is_gpt:
        return None
    if info.get("camera"):
        return f"带相机 EXIF（{info['camera']}），按实拍照片跳过；确认是 GPT 图可加 --model gpt 或 --force"
    if max(shape) > 3200:
        return "分辨率高于 GPT 原生输出（长边 >3200px），按实拍/放大图跳过；确认是 GPT 图可加 --model gpt"
    return None


def gate(maze_score, shape, info, is_gpt, force):
    """Decide whether to process. Returns (ok, reason)."""
    if force:
        return True, "forced"
    if is_gpt:
        if maze_score >= 0.02:
            return True, "GPT 图且检测到迷宫纹"
        return False, f"GPT 图但几乎没有迷宫纹（maze_score={maze_score:.3f}）"
    skip = pre_gate(shape, info, is_gpt, force)
    if skip:
        return False, skip
    if maze_score >= 0.05:
        return True, "检测到 GPT 迷宫纹特征"
    return False, f"未检测到明显 GPT 迷宫纹（maze_score={maze_score:.3f}）"


def process(rgb, info, src_path, strength=60, force=False, mask=None, model=None):
    """In-memory demaze. Returns (output rgb, result dict, confidence map)."""
    is_gpt = looks_like_gpt(src_path, model)
    skip = pre_gate(rgb.shape[:2], info, is_gpt, force)
    if skip or strength <= 0:
        result = {"route": "gpt-demaze", "strength": strength, "gpt_hint": is_gpt, "maze_score": None,
                  "decision": skip or "strength 0", "action": "no-op"}
        return rgb, result, np.zeros((1, 1), np.float32)
    # 1) upscaler grid first: it adds energy near Nyquist and hides the maze cliff
    rgb255, grid = degrid(rgb * 255.0, is_gpt=is_gpt)
    base = np.clip(rgb255 / 255.0, 0.0, 1.0) if grid["applied"] else rgb
    Y = luma(base) * 255.0
    use_net = _net() is not None
    if use_net:
        conf, dinfo = maze_detect(Y)
        Y2 = Y
    else:
        Y2, conf, dinfo = demaze_luma(Y, strength=strength, mask=mask)
    ok, why = gate(dinfo["maze_score"], Y.shape, info, is_gpt, force)
    result = {"route": "gpt-demaze", "strength": strength, "gpt_hint": is_gpt, **dinfo, "decision": why,
              "grid": grid}
    Yn = None
    if ok and use_net:
        try:
            Yn = cnn_luma(Y)
        except Exception as e:  # noqa: BLE001 - any DNN failure falls back to the spectral filter
            result["model_error"] = str(e).strip().splitlines()[-1][:200]
            Y2, _, _ = demaze_luma(Y, strength=strength, mask=mask)
    if Yn is not None:
        # learned filter: removes the worms without the blotches spectral subtraction
        # leaves; applied only where the maze is (skin, knit and backgrounds untouched)
        # strength up to 60 scales the correction; subtracting more than the predicted
        # maze prints an inverted maze, so above 60 it widens WHERE the filter applies
        # (patches with sparser maze reach full strength) instead
        amount = float(np.clip(strength / 60.0, 0.0, 1.0))
        density = 0.35 - 0.20 * float(np.clip((strength - 60.0) / 40.0, 0.0, 1.0))
        pres = presence_map(conf, Y.shape, k=density) if not force else np.ones(Y.shape, np.float32)
        Y2 = Y + (Yn - Y) * pres * amount
        if mask is not None:
            Y2 = Y2 * (1.0 - mask) + Y * mask
        result["method"] = "unet"
        result["presence_fraction"] = round(float((pres > 0.5).mean()), 4)
    else:
        result["method"] = "spectral"
    if not ok:
        result["action"] = "degrid" if grid["applied"] else "no-op"
        if grid["applied"] and mask is not None:
            base = base * (1 - mask[..., None]) + rgb * mask[..., None]
        return base, result, conf
    out = np.clip(base + ((Y2 - Y) / 255.0)[..., None], 0.0, 1.0)
    if grid["applied"] and mask is not None:
        out = out * (1 - mask[..., None]) + rgb * mask[..., None]
    result["action"] = "degrid+demaze" if grid["applied"] else "demaze"
    Yo = luma(out) * 255.0
    Y = luma(rgb) * 255.0
    f0, c0 = maze_index(Y)
    f1, _ = maze_index(Yo)
    sel = c0 > 0.5
    if sel.any():
        result["maze_bump_before"] = round(float(np.median(f0["m"][sel])), 2)
        result["maze_bump_after"] = round(float(np.median(f1["m"][sel])), 2)
    result["edge_preservation"] = round(float(edge_preservation(Y, Yo) or 1.0), 4)
    result["luma_mae_255"] = round(float(np.abs(Yo - Y).mean()), 3)
    return out, result, conf


def board(path, rgb, out, result, conf):
    crops = pick_crops(conf, rgb.shape[:2])
    comparison_board(
        path,
        "GPT 迷宫纹去除",
        f"强度 {result['strength']} · 迷宫纹覆盖 {result['maze_score']:.0%} · 凸起 "
        f"{result.get('maze_bump_before', '-')}→{result.get('maze_bump_after', '-')}（≈1 为自然纹理） · "
        f"边缘保持 {result.get('edge_preservation', '-')}",
        [("原图", to_pil(rgb)), ("去迷宫纹", to_pil(out))],
        crops=crops,
    )


def load_mask(path, shape):
    if not path:
        return None
    from PIL import Image
    m = Image.open(path).convert("L").resize((shape[1], shape[0]), Image.Resampling.NEAREST)
    return np.asarray(m, np.float32) / 255.0


def run(src, dst, strength=60, force=False, protect_mask=None, report=None, comparison=None, model=None):
    t0 = time.time()
    rgb, info = load_image(src)
    out, result, conf = process(rgb, info, src, strength, force, load_mask(protect_mask, rgb.shape), model)
    result["source"] = str(Path(src).resolve())
    save_image(dst, out, info)
    result["output"] = str(Path(dst).resolve())
    if comparison and result["action"] != "no-op":
        board(comparison, rgb, out, result, conf)
        result["comparison"] = str(Path(comparison).resolve())
    result["seconds"] = round(time.time() - t0, 2)
    if report:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        Path(report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main():
    ap = argparse.ArgumentParser(description="Remove GPT-image maze/worm texture noise (luminance only).")
    ap.add_argument("source")
    ap.add_argument("output")
    ap.add_argument("--strength", type=float, default=60, help="0-100, default 60")
    ap.add_argument("--force", action="store_true", help="process even if no maze texture is detected")
    ap.add_argument("--model", help="source model hint, e.g. gpt-image-2 (default: guess from file name)")
    ap.add_argument("--protect-mask", help="white = keep pixels unchanged")
    ap.add_argument("--report")
    ap.add_argument("--comparison")
    a = ap.parse_args()
    r = run(a.source, a.output, a.strength, a.force, a.protect_mask, a.report, a.comparison, a.model)
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
