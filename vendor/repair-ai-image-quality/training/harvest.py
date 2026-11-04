#!/usr/bin/env python3
"""Cut training patches for the maze filter.

    python harvest.py --gpt GPT_DIR [GPT_DIR ...] --clean CLEAN_DIR [CLEAN_DIR ...] --out data/

maze.npy     The maze itself: band-pass (0.16-0.62 x Nyquist) of 128 px luminance
             patches where the detector is confident (mean confidence >= 0.6),
             divided by local brightness. The maze amplitude follows brightness,
             so training multiplies it back by the clean patch's brightness.
clean.npy    Random 128 px luminance patches of clean images.
texture.npy  Clean patches with real texture in the maze band (skin, hair, knit,
             fleece, foliage) and low maze confidence: they teach the network
             what to keep.

GPT_DIR: GPT renders that show the maze (native 2K, not upscaled). CLEAN_DIR:
camera photos or other models' images. Images are used at <= 2048 px long side,
the scale the maze lives at. --hold NAME_PREFIX keeps images out of training
(use it for the ones you evaluate on).
"""
import argparse
import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gpt_demaze as g  # noqa: E402
from common import luma  # noqa: E402

Image.MAX_IMAGE_PIXELS = None
P = 128
EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def bandpass(Y, lo=0.16, hi=0.62):
    h, w = Y.shape
    F = np.fft.rfft2(Y - Y.mean())
    r = np.hypot(np.fft.fftfreq(h)[:, None] * 2, np.fft.rfftfreq(w)[None, :] * 2)
    m = np.clip((r - lo) / 0.04, 0, 1) * np.clip((hi - r) / 0.04, 0, 1)
    return np.fft.irfft2(F * m, s=Y.shape).astype(np.float32)


def images(dirs, hold):
    for d in dirs:
        for f in sorted(Path(d).rglob("*")):
            if f.suffix.lower() in EXTS and not f.name.startswith(tuple(hold)):
                yield f


def load_luma(f):
    im = Image.open(f).convert("RGB")
    s = min(1.0, 2048 / max(im.size))
    if s < 1.0:
        im = im.resize((round(im.size[0] * s), round(im.size[1] * s)), Image.Resampling.LANCZOS)
    rgb = np.asarray(im, np.float32)
    rgb, _ = g.degrid(rgb, is_gpt=g.looks_like_gpt(f))      # some providers add a 2x2 upscale grid
    return luma(np.clip(rgb / 255.0, 0, 1)).astype(np.float32)


def confidence_map(Y):
    _, conf = g.maze_index(Y * 255.0)
    import cv2
    return cv2.resize(conf.astype(np.float32), (Y.shape[1], Y.shape[0]), interpolation=cv2.INTER_LINEAR)


def rng_for(f):
    return np.random.RandomState(zlib.crc32(str(f).encode()) & 0x7FFFFFFF)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gpt", nargs="+", required=True)
    ap.add_argument("--clean", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--hold", nargs="*", default=[], help="file name prefixes to leave out")
    ap.add_argument("--per-maze-image", type=int, default=80)
    ap.add_argument("--per-clean-image", type=int, default=14)
    ap.add_argument("--per-texture-image", type=int, default=12)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    maze = []
    for f in images(a.gpt, a.hold):
        Y = load_luma(f)
        if min(Y.shape) < P:
            continue
        cmap, rng, n = confidence_map(Y), rng_for(f), 0
        for _ in range(3000):
            y, x = rng.randint(0, Y.shape[0] - P), rng.randint(0, Y.shape[1] - P)
            if cmap[y:y + P, x:x + P].mean() < 0.6:
                continue
            patch = Y[y:y + P, x:x + P]
            maze.append(bandpass(patch) / max(float(patch.mean()), 0.05))
            n += 1
            if n >= a.per_maze_image:
                break
        print(f"maze    {f.name[:60]:60} {n}", flush=True)

    clean, texture = [], []
    for f in images(a.clean, a.hold):
        Y = load_luma(f)
        if min(Y.shape) < P:
            continue
        cmap, rng = confidence_map(Y), rng_for(f)
        for _ in range(a.per_clean_image):
            y, x = rng.randint(0, Y.shape[0] - P), rng.randint(0, Y.shape[1] - P)
            clean.append(Y[y:y + P, x:x + P].copy())
        got = 0
        for _ in range(600):
            y, x = rng.randint(0, Y.shape[0] - P), rng.randint(0, Y.shape[1] - P)
            if cmap[y:y + P, x:x + P].mean() > 0.2:
                continue
            patch = Y[y:y + P, x:x + P]
            if bandpass(patch).std() / max(float(patch.mean()), 0.05) < 0.03:
                continue
            texture.append(patch.copy())
            got += 1
            if got >= a.per_texture_image:
                break
        print(f"clean   {f.name[:60]:60} {a.per_clean_image} + texture {got}", flush=True)

    if not maze or not clean:
        sys.exit("need at least one maze patch and one clean patch (check the folders / --hold)")
    np.save(out / "maze.npy", np.stack(maze).astype(np.float32))
    np.save(out / "clean.npy", np.stack(clean).astype(np.float32))
    if texture:
        np.save(out / "texture.npy", np.stack(texture).astype(np.float32))
    print(f"maze {len(maze)}, clean {len(clean)}, texture {len(texture)} patches -> {out}")


if __name__ == "__main__":
    main()
