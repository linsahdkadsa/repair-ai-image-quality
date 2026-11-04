#!/usr/bin/env python3
"""Train the maze filter on patches from harvest.py.

    python train.py --data data/ --out maze_unet.pt [--steps 30000] [--val-clean C.npy --val-noisy N.npy]
    python train.py --data data/ --out tuned.pt --init maze_unet.pt --lr 3e-4 --steps 10000   # fine-tune

Each sample is a clean patch plus a maze patch (rotated/flipped independently)
scaled by the clean patch's local brightness and a random amplitude 0.2-1.4.
25 % of samples get no maze at all, so the network learns to leave clean
texture alone; 30 % of the mazes are synthetic ring noise (0.28-0.45 x Nyquist)
so it does not memorise the harvested ones. Loss: L1 + 0.5 x L1 of the image
gradients (keeps edges sharp). AdamW, one-cycle LR 1e-3, batch 32 x 96 px.

Validation: --val-clean / --val-noisy (N x H x W [x 3] arrays in 0..1, e.g.
held-out renders' maze added to clean crops); without them, 5 % of the
patches are held out and given a fixed synthetic maze. The checkpoint with
the best validation PSNR is kept. ~2 h on an Apple M-series GPU (mps), also
runs on CUDA or CPU.
"""
import argparse
import math
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from model import MazeUNet


def to_luma(a):
    a = np.asarray(a, np.float32)
    if a.ndim == 4:
        a = a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
    return torch.from_numpy(a.astype(np.float32))[:, None]


def ring_noise(n, size, dev):
    """Gaussian noise with an isotropic ring spectrum (0.28-0.45 x Nyquist), unit std."""
    fy = torch.fft.fftfreq(size, device=dev)[:, None] * 2
    fx = torch.fft.rfftfreq(size, device=dev)[None, :] * 2
    r = torch.sqrt(fy ** 2 + fx ** 2)[None]
    r0 = 0.28 + 0.17 * torch.rand(n, 1, 1, device=dev)
    s = 0.05 + 0.06 * torch.rand(n, 1, 1, device=dev)
    filt = torch.exp(-0.5 * ((r - r0) / s) ** 2) * torch.clamp((0.6 - r) / 0.05, 0, 1)
    z = torch.fft.irfft2(torch.fft.rfft2(torch.randn(n, size, size, device=dev)) * filt, s=(size, size))
    return z / z.std(dim=(1, 2), keepdim=True).clamp_min(1e-6)


def make_batch(cleans, mazes, dev, bs=32, P=96, no_maze=0.25, synthetic=0.3):
    ci = torch.randint(0, len(cleans), (bs,), device=cleans.device)
    mi = torch.randint(0, len(mazes), (bs,), device=mazes.device)
    y0, x0 = np.random.randint(0, cleans.shape[-1] - P + 1, 2)
    c = cleans[ci][:, y0:y0 + P, x0:x0 + P].to(dev)
    m = mazes[mi][:, y0:y0 + P, x0:x0 + P].to(dev)
    c = torch.rot90(c, np.random.randint(4), (1, 2))
    m = torch.rot90(m, np.random.randint(4), (1, 2))
    if np.random.rand() < 0.5:
        c = c.flip(2)
    if np.random.rand() < 0.5:
        m = m.flip(1)
    use_syn = (torch.rand(bs, 1, 1, device=dev) < synthetic).float()
    m = use_syn * ring_noise(bs, P, dev) * 0.10 + (1 - use_syn) * m      # 0.10 ~ harvested maze std
    amp = (0.2 + 1.2 * torch.rand(bs, 1, 1, device=dev)) * (torch.rand(bs, 1, 1, device=dev) > no_maze).float()
    lum = F.avg_pool2d(c[:, None], 31, 1, 15, count_include_pad=False)[:, 0].clamp(0.05, 1.0)
    return (c + amp * m * lum).clamp(0, 1)[:, None], c[:, None]


def psnr(model, noisy, clean, dev, border=16):
    model.eval()
    out = []
    with torch.no_grad():
        for n, c in zip(noisy, clean):
            o = model(n[None].to(dev)).cpu()[0, 0]
            mse = float(((o - c[0])[border:-border, border:-border] ** 2).mean())
            out.append(10 * math.log10(1 / max(mse, 1e-12)))
    model.train()
    return float(np.mean(out))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--steps", type=int, default=30000)
    ap.add_argument("--width", type=int, default=24)
    ap.add_argument("--val-clean")
    ap.add_argument("--val-noisy")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--init", help="start from this checkpoint (fine-tuning, or finishing an interrupted run)")
    ap.add_argument("--lr", type=float, default=1e-3, help="peak learning rate of the one-cycle schedule")
    a = ap.parse_args()
    torch.manual_seed(a.seed)
    np.random.seed(a.seed)
    dev = torch.device("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")

    d = Path(a.data)
    mazes = torch.from_numpy(np.load(d / "maze.npy")).float()
    cleans = torch.from_numpy(np.load(d / "clean.npy")).float()
    if (d / "texture.npy").exists():
        cleans = torch.cat([cleans, torch.from_numpy(np.load(d / "texture.npy")).float()])
    if a.val_clean and a.val_noisy:
        val_c, val_n = to_luma(np.load(a.val_clean)), to_luma(np.load(a.val_noisy))
    else:
        g = torch.Generator().manual_seed(1)
        idx = torch.randperm(len(cleans), generator=g)
        k = max(8, len(cleans) // 20)
        held, cleans = cleans[idx[:k]], cleans[idx[k:]]
        mz = mazes[torch.randint(0, len(mazes), (k,), generator=g)]
        lum = F.avg_pool2d(held[:, None], 31, 1, 15, count_include_pad=False)[:, 0].clamp(0.05, 1.0)
        val_c, val_n = held[:, None], (held + 0.8 * mz * lum).clamp(0, 1)[:, None]
    mazes, cleans = mazes.to(dev), cleans.to(dev)       # keep the patch banks on the device

    model = MazeUNet(a.width)
    if a.init:
        model.load_state_dict(torch.load(a.init, map_location="cpu"))
    model = model.to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.steps, pct_start=0.05)
    base = float(np.mean([10 * math.log10(1 / max(float(((n - c)[0, 16:-16, 16:-16] ** 2).mean()), 1e-12))
                          for n, c in zip(val_n, val_c)]))
    print(f"{sum(p.numel() for p in model.parameters()) / 1e3:.0f}k parameters on {dev}; "
          f"{len(mazes)} maze / {len(cleans)} clean patches; validation PSNR before {base:.2f} dB", flush=True)
    best, t0 = (psnr(model, val_n, val_c, dev) if a.init else -1.0), time.time()
    if a.init:
        print(f"starting point {a.init}: validation PSNR {best:.2f} dB", flush=True)
    for step in range(1, a.steps + 1):
        n, c = make_batch(cleans, mazes, dev)
        o = model(n)
        loss = (o - c).abs().mean() \
            + 0.5 * ((o[..., 1:, :] - o[..., :-1, :]) - (c[..., 1:, :] - c[..., :-1, :])).abs().mean() \
            + 0.5 * ((o[..., 1:] - o[..., :-1]) - (c[..., 1:] - c[..., :-1])).abs().mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
        sched.step()
        if step % 2000 == 0 or step == a.steps:
            v = psnr(model, val_n, val_c, dev)
            if v > best:
                best = v
                torch.save(model.state_dict(), a.out)
            print(f"step {step} loss {loss.item():.5f} validation PSNR {v:.2f} (best {best:.2f}) {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
