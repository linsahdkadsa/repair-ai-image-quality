#!/usr/bin/env python3
"""Synthetic regression test (~10 s). Exit code 0 = all checks passed.

1. GPT maze: band-limited labyrinth texture on a smooth "velvet" surface with a
   sharp seam; must lose most of the maze, keep the seam, keep colour. Runs the
   learned filter (the default) and the spectral fallback.
2. Upscale grid: a fixed 2x2 pattern must be removed; broadband camera-like
   texture must be left alone.
3. banana colour: magenta cast + 1 px shift + 0.2 % zoom + an intentional
   recolour; the cast must go, the intentional recolour must stay.
4. green-screen regeneration (new pose, different screen shade): no-op.
5. colour-dependent drift (skin 2x the wall, plant less) with re-rendered skin
   texture: every region must come back within 0.6 a* - neither left magenta
   nor pushed green; a new white object drawn without the cast stays white.
6. grey source (white model) next to a colourful edit: no-op.
7. part transplant: a striped "product photo" mapped by 4 landmarks onto a scene
   with a wrongly drawn part; the stripes must land where the homography puts
   them, and `finish` must reject a candidate whose stripes moved.
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import color_match  # noqa: E402
import gpt_demaze  # noqa: E402
from common import delta_e2000, lab_to_rgb, luma, rgb_to_lab, save_image  # noqa: E402

RNG = np.random.RandomState(7)
FAILS = []


def check(name, ok, detail):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    if not ok:
        FAILS.append(name)


def bandpass_noise(h, w, lo, hi):
    n = RNG.randn(h, w)
    F = np.fft.fft2(n)
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    r = np.hypot(fy, fx) / 0.5
    F *= (r >= lo) & (r <= hi)
    out = np.real(np.fft.ifft2(F))
    return out / out.std()


def maze_test(tmp):
    h = w = 768
    yy, xx = np.mgrid[0:h, 0:w] / h
    shade = 0.55 + 0.12 * np.sin(3 * xx + 1) * np.cos(2 * yy)        # soft velvet shading
    seam = (np.abs(xx - 0.62) < 0.004).astype(np.float32) * -0.18      # a sharp seam line
    clean = np.clip(shade + seam, 0, 1)
    # GPT-like maze: thresholded band-pass noise, then band-limited (the "cliff")
    m = np.tanh(2.5 * bandpass_noise(h, w, 0.22, 0.48))
    F = np.fft.fft2(m)
    r = np.hypot(np.fft.fftfreq(h)[:, None], np.fft.fftfreq(w)[None, :]) / 0.5
    m = np.real(np.fft.ifft2(F * (r <= 0.56)))
    maze = 0.05 * m / np.abs(m).max() * 2.2
    rgb_clean = np.dstack([clean * 0.98, clean, clean * 1.02]).astype(np.float32)
    noisy = np.clip(rgb_clean + maze[..., None], 0, 1).astype(np.float32)
    out, res, _ = gpt_demaze.process(noisy, {}, "synthetic_gpt-image.png", strength=60)
    err_before = np.abs(noisy - rgb_clean).mean() * 255
    err_after = np.abs(out - rgb_clean).mean() * 255
    check("maze detected", res["action"] == "demaze" and res["maze_score"] > 0.3,
          f"action={res['action']} maze_score={res['maze_score']:.2f}")
    check("maze removed", err_after < 0.5 * err_before,
          f"error vs clean {err_before:.2f} -> {err_after:.2f} /255")
    Yc, Yo = luma(rgb_clean) * 255, luma(out) * 255
    seam_c = Yc[:, int(0.62 * w)].mean() - Yc[:, int(0.70 * w)].mean()
    seam_o = Yo[:, int(0.62 * w)].mean() - Yo[:, int(0.70 * w)].mean()
    check("seam kept", abs(seam_o - seam_c) < 0.15 * abs(seam_c), f"seam contrast {seam_c:.1f} -> {seam_o:.1f}")
    chroma = np.abs((out - luma(out)[..., None]) - (noisy - luma(noisy)[..., None])).max() * 255
    check("colour untouched", chroma < 1.0, f"max chroma change {chroma:.2f} /255")
    loaded = gpt_demaze._net() is not None
    check("maze model used", loaded and res.get("method") == "unet",
          f"method={res.get('method')}" + ("" if loaded else " - scripts/models/gpt_maze_unet.onnx missing or OpenCV DNN unavailable"))
    # the spectral filter runs when the model cannot: it must still remove the maze
    saved = dict(gpt_demaze._NET)
    gpt_demaze._NET.clear()
    gpt_demaze._NET["net"] = None
    out_s, res_s, _ = gpt_demaze.process(noisy, {}, "synthetic_gpt-image.png", strength=60)
    gpt_demaze._NET.clear()
    gpt_demaze._NET.update(saved)
    err_s = np.abs(out_s - rgb_clean).mean() * 255
    check("spectral fallback works", res_s.get("method") == "spectral" and err_s < 0.5 * err_before,
          f"error vs clean {err_before:.2f} -> {err_s:.2f} /255")


def grid_test():
    """2x2 upscaler grid (GPT via some providers) must be detected and removed."""
    h, w = 768, 1024
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    base = 0.45 + 0.15 * np.sin(xx / 97.0) * np.cos(yy / 71.0)
    tex = cv2.GaussianBlur(RNG.rand(h, w).astype(np.float32), (0, 0), 1.2) - 0.5
    clean = np.clip(base + 0.08 * tex, 0, 1)
    pat = np.zeros((h, w), np.float32)
    pat[0::2, 0::2] = 1.0
    pat[1::2, 1::2] = -1.0
    gridded = np.clip(clean + pat * (0.004 + 0.02 * np.abs(tex)), 0, 1)
    rgb = np.dstack([gridded] * 3).astype(np.float32)
    out, res, _ = gpt_demaze.process(rgb, {}, "night_gpt-image.png", strength=60)
    g = res.get("grid") or {}
    zb, za = g.get("fold_z_before", {}).get(2, 0), (g.get("fold_z_after") or {}).get(2, 99)
    err_b = np.abs(rgb[..., 0] - clean).mean() * 255
    err_a = np.abs(out[..., 0] - clean).mean() * 255
    check("upscale grid removed", g.get("applied") and za < 3 and err_a < 0.5 * err_b,
          f"period-2 z {zb} -> {za}, error vs clean {err_b:.2f} -> {err_a:.2f} /255")


def false_positive_test():
    h = w = 768
    n = RNG.randn(h, w)
    F = np.fft.fft2(n)
    r = np.hypot(np.fft.fftfreq(h)[:, None], np.fft.fftfreq(w)[None, :]) + 1e-3
    tex = np.real(np.fft.ifft2(F / r))                                  # 1/f camera-like texture
    tex = 0.5 + 0.12 * tex / tex.std()
    rgb = np.clip(np.dstack([tex, tex * 0.95, tex * 0.9]), 0, 1).astype(np.float32)
    _, res, _ = gpt_demaze.process(rgb, {}, "photo.jpg", strength=60)
    check("natural texture skipped", res["action"] == "no-op", f"maze_score={res['maze_score']:.3f}")


def color_test(tmp):
    h, w = 720, 960
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    base = np.dstack([
        0.35 + 0.4 * xx / w, 0.30 + 0.35 * yy / h, 0.25 + 0.3 * (1 - xx / w)]).astype(np.float32)
    tex = cv2.GaussianBlur(RNG.rand(h, w).astype(np.float32), (0, 0), 2.0)
    src = np.clip(base + 0.25 * (tex[..., None] - 0.5) + 0.06 * np.sin(xx / 23)[..., None], 0, 1)
    for i in range(6):                                                   # coloured objects
        cy, cx = RNG.randint(80, h - 80), RNG.randint(80, w - 80)
        col = RNG.rand(3) * 0.8 + 0.1
        cv2.circle(src, (cx, cy), int(RNG.randint(25, 60)), tuple(float(c) for c in col), -1)
    # banana-like edit: magenta cast (R,B up, G down; stronger in mids), 1 px shift, 0.2 % zoom
    cast = np.clip(src * np.array([1.03, 0.965, 1.03], np.float32) + np.array([0.01, -0.006, 0.012]), 0, 1)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), 0, 1.002)
    M[:, 2] += (1.0, -1.0)
    edit = cv2.warpAffine(cast, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    # intentional recolour: a big block turned blue (must survive)
    edit[60:260, 560:900] = np.array([0.20, 0.35, 0.80], np.float32)
    sp, ep, op = Path(tmp) / "src.png", Path(tmp) / "edit_banana.png", Path(tmp) / "out.png"
    save_image(sp, src)
    save_image(ep, edit)
    res = color_match.match(str(sp), str(ep), str(op))
    from common import load_image
    out = load_image(op)[0]
    src_w = cv2.warpAffine(src, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    keep = np.ones((h, w), bool)
    keep[40:280, 540:920] = False
    de_b = delta_e2000(rgb_to_lab(edit[keep]).astype(np.float64), rgb_to_lab(src_w[keep]).astype(np.float64)).mean()
    de_a = delta_e2000(rgb_to_lab(out[keep]).astype(np.float64), rgb_to_lab(src_w[keep]).astype(np.float64)).mean()
    check("cast removed", res["action"] == "color-match" and de_a < 0.4 * de_b, f"dE00 {de_b:.2f} -> {de_a:.2f}")
    blue_in = edit[100:220, 600:860].reshape(-1, 3).mean(0)
    blue_out = out[100:220, 600:860].reshape(-1, 3).mean(0)
    de_blue = float(delta_e2000(rgb_to_lab(blue_in[None]).astype(np.float64),
                                rgb_to_lab(blue_out[None]).astype(np.float64))[0])
    check("intentional recolour kept", de_blue < 6.0 and blue_out[2] > 0.7,
          f"blue block moved dE00 {de_blue:.2f} (stays blue: B={blue_out[2]:.2f})")


def chroma_key_test(tmp):
    """New pose on a green screen whose shade changed: must NOT be 'colour corrected'."""
    h, w = 720, 540
    def sprite(cx):
        img = np.zeros((h, w, 3), np.float32)
        img[:] = (0.05, 0.85, 0.10)
        tex = cv2.GaussianBlur(RNG.rand(h, w).astype(np.float32), (0, 0), 1.5)
        body = np.zeros((h, w), np.uint8)
        cv2.ellipse(body, (cx, 380), (90, 230), 0, 0, 360, 255, -1)
        m = body > 0
        img[m] = np.stack([0.55 + 0.3 * tex[m], 0.35 + 0.2 * tex[m], 0.30 + 0.2 * tex[m]], -1)
        return img
    src = sprite(200)
    edit = sprite(330)
    screen = (np.abs(edit - np.array([0.05, 0.85, 0.10], np.float32)).sum(-1) < 1e-6)
    edit[screen] = (0.18, 0.80, 0.16)                                  # different screen shade
    sp, ep, op = Path(tmp) / "k_src.png", Path(tmp) / "k_edit_banana.png", Path(tmp) / "k_out.png"
    save_image(sp, src)
    save_image(ep, edit)
    res = color_match.match(str(sp), str(ep), str(op))
    check("green-screen regeneration skipped", res["action"] == "no-op", f"action={res['action']} reason={res.get('reason', '')[:40]}")


def portrait_scene(seed_face):
    """Grey wall, a warm textured 'face', a green 'plant', a dark 'jacket'."""
    h, w = 720, 960
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rng = np.random.RandomState(11)
    wall = np.dstack([0.66 + 0.04 * xx / w] * 3).astype(np.float32) + 0.02 * (cv2.GaussianBlur(rng.rand(h, w).astype(np.float32), (0, 0), 6)[..., None] - 0.5)
    img = wall.copy()
    masks = {}
    for name, (cx, cy, ax, ay), col in (("skin", (480, 300, 130, 170), (0.86, 0.64, 0.52)),
                                       ("plant", (170, 520, 110, 150), (0.25, 0.50, 0.22)),
                                       ("jacket", (480, 640, 260, 120), (0.16, 0.17, 0.22))):
        m = np.zeros((h, w), np.uint8)
        cv2.ellipse(m, (cx, cy), (ax, ay), 0, 0, 360, 255, -1)
        m = m > 0
        masks[name] = m
        img[m] = col
    shade = 0.08 * np.sin(yy / 60)[..., None] + 0.05 * np.cos(xx / 45)[..., None]
    img = img + shade * 0.5
    # fine texture; the face's pores get a different seed in the edit (banana re-renders them)
    pores = cv2.GaussianBlur(np.random.RandomState(seed_face).rand(h, w).astype(np.float32), (0, 0), 1.2)
    img[masks["skin"]] += 0.10 * (pores[masks["skin"]][:, None] - 0.5)
    leaves = cv2.GaussianBlur(rng.rand(h, w).astype(np.float32), (0, 0), 1.5)
    img[masks["plant"]] += 0.16 * (leaves[masks["plant"]][:, None] - 0.5)
    return np.clip(img, 0, 1), masks


def color_dependent_test(tmp):
    src, masks = portrait_scene(1)
    edit, _ = portrait_scene(2)
    lab = rgb_to_lab(edit)
    drift = np.zeros(lab.shape[:2] + (3,), np.float32)
    drift[..., 1], drift[..., 2] = 3.0, -1.0                       # wall / everything: magenta
    for name, da, db in (("skin", 6.0, -0.5), ("plant", 1.5, -1.0), ("jacket", 4.0, -2.5)):
        drift[masks[name], 1], drift[masks[name], 2] = da, db
    drift = cv2.GaussianBlur(drift, (0, 0), 2.0)
    drift[..., 0] = 0.6                                              # slight brightening
    edit = np.clip(lab_to_rgb(lab + drift), 0, 1)
    cup = np.zeros(edit.shape[:2], np.uint8)                       # new object, rendered neutral
    cv2.rectangle(cup, (720, 420), (860, 560), 255, -1)
    cup = cup > 0
    edit[cup] = 0.84 + 0.04 * (RNG.rand(int(cup.sum()), 1) - 0.5)
    M = cv2.getRotationMatrix2D((480, 360), 0, 1.002)
    M[:, 2] += (1.0, 0.0)
    h, w = src.shape[:2]
    edit = cv2.warpAffine(edit, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    sp, ep, op = Path(tmp) / "p_src.png", Path(tmp) / "p_edit_banana.png", Path(tmp) / "p_out.png"
    save_image(sp, src)
    save_image(ep, edit)
    res = color_match.match(str(sp), str(ep), str(op))
    from common import load_image
    out = load_image(op)[0]
    src_w = cv2.warpAffine(src, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    lo, ls = rgb_to_lab(cv2.GaussianBlur(out, (0, 0), 4)), rgb_to_lab(cv2.GaussianBlur(src_w, (0, 0), 4))
    wall = ~(masks["skin"] | masks["plant"] | masks["jacket"])
    errs = {}
    for name, m in (("wall", wall), ("skin", masks["skin"]), ("plant", masks["plant"]), ("jacket", masks["jacket"])):
        m = cv2.warpAffine(m.astype(np.uint8), M, (w, h), flags=cv2.INTER_NEAREST) > 0
        m = cv2.erode(m.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        errs[name] = float(np.median((lo - ls)[m][:, 1]))
    cup_w = cv2.erode((cv2.warpAffine(cup.astype(np.uint8), M, (w, h), flags=cv2.INTER_NEAREST) > 0).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    cup_a = float(np.median(rgb_to_lab(out)[cup_w][:, 1]))
    ok = res["action"] == "color-match" and all(abs(v) < 0.6 for v in errs.values()) and cup_a > -0.4
    check("colour-dependent drift, no green", ok,
          "a* after: " + ", ".join(f"{k} {v:+.2f}" for k, v in errs.items()) + f", new white object {cup_a:+.2f}")


def grey_source_test(tmp):
    """A white-model / grey render of a colourful scene is no colour reference."""
    h, w = 720, 960
    rng = np.random.RandomState(3)                                  # independent of the other tests
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    edit = np.dstack([0.30 + 0.5 * xx / w, 0.55 - 0.3 * yy / h, 0.20 + 0.4 * (1 - xx / w)]).astype(np.float32)
    edit += 0.2 * (cv2.GaussianBlur(rng.rand(h, w).astype(np.float32), (0, 0), 2.0)[..., None] - 0.5)
    for i in range(8):
        cv2.circle(edit, (int(rng.randint(80, w - 80)), int(rng.randint(80, h - 80))), int(rng.randint(30, 70)),
                   tuple(float(c) for c in rng.rand(3) * 0.8 + 0.1), -1)
    # the right half is a neutral wall in both (it still matches, as in real white-model shots)
    wall = 0.62 + 0.12 * (cv2.GaussianBlur(rng.rand(h, w).astype(np.float32), (0, 0), 1.5) - 0.5)
    edit[:, w // 2:] = wall[:, w // 2:, None]
    edit = np.clip(edit, 0, 1)
    g = luma(edit)[..., None].repeat(3, -1).astype(np.float32)     # white model / grey render
    sp, ep, op = Path(tmp) / "g_src.png", Path(tmp) / "g_edit_banana.png", Path(tmp) / "g_out.png"
    save_image(sp, g)
    save_image(ep, edit)
    res = color_match.match(str(sp), str(ep), str(op))
    check("grey source skipped", res["action"] == "no-op" and "灰" in (res.get("reason") or ""),
          f"action={res['action']} reason={res.get('reason', '')[:40]}")


def transplant_test(tmp):
    import json
    import subprocess
    tmp = Path(tmp)
    h = w = 400
    prod = np.full((h, w, 3), (0.85, 0.75, 0.2), np.float32)
    for x0 in (150, 210):                                    # two dark stripes, 30 px wide
        prod[60:340, x0:x0 + 30] = (0.55, 0.40, 0.10)
    prod += RNG.normal(0, 0.01, prod.shape).astype(np.float32)
    scene = np.full((500, 500, 3), (0.80, 0.72, 0.22), np.float32)
    scene[100:400, 200:240] = (0.50, 0.38, 0.12)             # one wrong, wide stripe
    scene += RNG.normal(0, 0.01, scene.shape).astype(np.float32)
    save_image(tmp / "prod.png", np.clip(prod, 0, 1)); save_image(tmp / "scene.png", np.clip(scene, 0, 1))
    # product -> scene: shift (+50, +50)
    pairs = "40,40=90,90; 360,40=410,90; 360,360=410,410; 40,360=90,410"
    out = tmp / "pt"
    py, here = sys.executable, Path(__file__).resolve().parent / "part_transplant.py"
    r = subprocess.run([py, str(here), "prep", "--scene", str(tmp / "scene.png"), "--product", str(tmp / "prod.png"),
                        "--pairs", pairs, "--part", "130,50; 260,50; 260,350; 130,350",
                        "--erase", "190,140; 260,140; 260,410; 190,410", "--out", str(out)],
                       capture_output=True, text=True)
    if r.returncode:
        check("transplant prep", False, r.stderr.strip()[-120:]); return
    t = cv2.imread(str(out / "transplant.jpg"))[..., ::-1].astype(np.float32) / 255
    row = t[250, 150:330].mean(1)
    dark = np.where(row < row.max() - 0.12)[0] + 150
    ok = len(dark) and abs(dark.min() - 200) <= 3 and abs(dark.max() - 289) <= 3 and row[245 - 150] > row.max() - 0.12
    check("transplant geometry", bool(ok), f"stripe pixels on row 250 at x {dark.min() if len(dark) else '-'}..{dark.max() if len(dark) else '-'} (expected 200..289, gap at 240..259)")
    meta = json.loads((out / "meta.json").read_text())
    x0, y0, x1, y1 = meta["box"]
    good = t.copy()
    moved = t.copy()                                       # a candidate that moved ONE stripe (a global
    moved[:, 240:320] = np.roll(t[:, 240:320], 12, axis=1)  # shift would just be registered away)
    save_image(tmp / "good.png", good[y0:y1, x0:x1]); save_image(tmp / "moved.png", moved[y0:y1, x0:x1])
    r = subprocess.run([py, str(here), "finish", "--dir", str(out), "--no-protect", "--candidates",
                        str(tmp / "good.png"), str(tmp / "moved.png")], capture_output=True, text=True)
    rep = json.loads((out / "finish_report.json").read_text()) if (out / "finish_report.json").exists() else {}
    acc = {Path(c["candidate"]).stem: c["accepted"] for c in rep.get("candidates", [])}
    check("transplant drift check", acc.get("good") is True and acc.get("moved") is False, f"accepted={acc}")


def portrait_test():
    import portrait
    ok = portrait.YUNET.exists()
    flat = np.full((600, 450, 3), 0.6, np.float32) + RNG.normal(0, 0.02, (600, 450, 3)).astype(np.float32)
    info = portrait.portrait_info(np.clip(flat, 0, 1)) if ok else {}
    check("face detector loads, no face on a plain image", ok and info.get("portrait") is False, f"model={'ok' if ok else 'missing'} info={info}")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        maze_test(tmp)
        grid_test()
        false_positive_test()
        color_test(tmp)
        chroma_key_test(tmp)
        color_dependent_test(tmp)
        grey_source_test(tmp)
        transplant_test(tmp)
        portrait_test()
    print("\nALL PASS" if not FAILS else f"\nFAILED: {', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
