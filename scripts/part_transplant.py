#!/usr/bin/env python3
"""Product-part transplant: put a product detail back into an AI image with the REAL geometry.

Image models redraw small product parts (stripes, overlays, logos, stitching) the way they
"usually" look -- parallel, evenly spaced, an extra stripe -- and text or line-art guides do
not stop them. What works: take the part from a real product photo shot from the same side,
warp it onto the AI image, relight it, and let the image model only blend the seams.

    part_transplant.py grid IMG --out grid.png [--box x0,y0,x1,y1] [--step 50]
        draw a labelled coordinate grid, to read landmark positions off both images
    part_transplant.py prep --scene AI.jpg --product PRODUCT.jpg --out DIR \
        --pairs "px,py=sx,sy; ..."    >= 4 landmark pairs, product -> scene, on the product's
                                       FIXED structure (heel, collar, lace-panel ends, sole line),
                                       spread over the whole object -- never on the part being
                                       fixed: the AI drew that part wrong, so its position and
                                       angle there are exactly what must not be copied
        --part "x,y; x,y; ..."         polygon around the part, PRODUCT coordinates
        [--clip "x,y; ..."]            only change pixels inside this SCENE polygon
                                       (e.g. stop at the lace panel and the sole)
        [--erase "x,y; ..."]           SCENE polygon of the wrong part to remove first
      -> DIR/transplant.jpg (whole image), DIR/blend_input.png (crop for the image model),
         DIR/guide.jpg (product line art in red, for checking the warp), DIR/prompt.txt, meta.json
    (blend: image model, refs = [DIR/blend_input.png] ONLY, prompt = DIR/prompt.txt,
     ratio from meta.json, 2+ candidates. Do not add the product photo as a reference:
     the model then redraws the part its own way again.)
    part_transplant.py finish --dir DIR --candidates C1.jpg C2.jpg ... [--out FILE]
      -> each candidate is colour-matched and checked against the transplant inside the part
         (overall correlation + per-tile shift, which catches a changed slant or spacing);
         rejected ones are listed. The best is pasted back; inside the part only its shading is
         used, the lines come from the transplant (--no-protect to turn that off).
"""

import argparse
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import color_match as cm  # noqa: E402
import retexture  # noqa: E402
from common import font, load_image, save_image, to_pil  # noqa: E402

RATIOS = {"1:1": 1.0, "5:4": 1.25, "4:5": 0.8, "4:3": 4 / 3, "3:4": 0.75, "3:2": 1.5, "2:3": 2 / 3,
          "16:9": 16 / 9, "9:16": 9 / 16, "21:9": 21 / 9}
MIN_SHAPE_SCORE = 0.45      # band-pass correlation with the transplant inside the part
MAX_LOCAL_SHIFT = 2.0       # px; any tile of the part moved more than this = the model redrew it
BLEND_PROMPT = (
    "Retouch this photo. The {part} is already correct: do NOT move, reshape, straighten, re-space, "
    "add or remove any of its elements; keep its exact layout, edges and stitching. Only fix the "
    "compositing: blend any visible paste seams or patchy shading around it into one continuous "
    "surface, continue nearby seams and stitch lines naturally, and match its lighting and sheen to "
    "the rest of the {object} (no studio highlights). Everything else (framing, background, other "
    "parts) stays identical. Photorealistic.")


def parse_pts(s):
    return np.array([[float(v) for v in p.split(",")] for p in re.split(r"[;\s]+", s.strip()) if p], np.float32)


def parse_pairs(s):
    src, dst = [], []
    for p in s.split(";"):
        if p.strip():
            a, b = p.split("=")
            src.append([float(v) for v in a.split(",")])
            dst.append([float(v) for v in b.split(",")])
    return np.float32(src), np.float32(dst)


def poly_mask(shape, pts):
    m = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(m, [np.round(pts).astype(np.int32)], 1)
    return m.astype(bool)


def to_lab(rgb):
    return cv2.cvtColor(np.clip(rgb, 0, 1).astype(np.float32), cv2.COLOR_RGB2LAB)


def from_lab(lab):
    return np.clip(cv2.cvtColor(lab.astype(np.float32), cv2.COLOR_LAB2RGB), 0, 1)


def line_art(rgb):
    """XDoG-style line drawing (1 = line)."""
    g = cv2.bilateralFilter((rgb.mean(2) * 255).astype(np.uint8), 9, 30, 7).astype(np.float32)
    d = cv2.GaussianBlur(g, (0, 0), 1.2) - 0.98 * cv2.GaussianBlur(g, (0, 0), 2.4)
    return (d < -2.0).astype(np.uint8)


def band(rgb, lo=1.0, hi=4.0):
    y = rgb.mean(2).astype(np.float32) if rgb.ndim == 3 else rgb.astype(np.float32)
    return cv2.GaussianBlur(y, (0, 0), lo) - cv2.GaussianBlur(y, (0, 0), hi)


def plane(L, mask, xx, yy, region=None):
    """Linear lighting fit on `mask`; falls back to a constant when the samples do not span
    the region they are applied to (a thin ring would extrapolate wildly)."""
    ys, xs = np.nonzero(mask)
    if region is not None and region.any():
        ry, rx = np.nonzero(region)
        span = min(np.ptp(xs) / max(np.ptp(rx), 1), np.ptp(ys) / max(np.ptp(ry), 1))
        if span < 0.8:
            return np.full(L.shape, float(L[mask].mean()), np.float32)
    A = np.c_[xx[mask], yy[mask], np.ones(int(mask.sum()))]
    c, *_ = np.linalg.lstsq(A, L[mask], rcond=None)
    return c[0] * xx + c[1] * yy + c[2]


def hf_level(rgb, mask):
    b = band(rgb, 0.7, 2.0)
    return float(b[mask].std()) if mask.any() else 0.0


# ---------------------------------------------------------------- grid

def cmd_grid(a):
    im = Image.open(a.image).convert("RGB")
    box = tuple(int(v) for v in a.box.split(",")) if a.box else (0, 0, im.width, im.height)
    c = im.crop(box)
    sc = min(1.0, 1800 / max(c.size)) if a.scale is None else a.scale
    c = c.resize((int(c.width * sc), int(c.height * sc)), Image.Resampling.LANCZOS)
    d = ImageDraw.Draw(c)
    f = font(max(12, int(14 * max(sc, 0.8))))
    for x in range((box[0] // a.step + 1) * a.step, box[2], a.step):
        X = (x - box[0]) * sc
        d.line([(X, 0), (X, c.height)], fill=(40, 80, 255), width=1)
        d.text((X + 2, 2), str(x), font=f, fill=(255, 40, 40))
    for y in range((box[1] // a.step + 1) * a.step, box[3], a.step):
        Y = (y - box[1]) * sc
        d.line([(0, Y), (c.width, Y)], fill=(40, 80, 255), width=1)
        d.text((2, Y + 2), str(y), font=f, fill=(255, 40, 40))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    c.save(a.out)
    print(a.out)


# ---------------------------------------------------------------- prep

def cmd_prep(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    scene, sinfo = load_image(a.scene)
    prod, _ = load_image(a.product)
    h, w = scene.shape[:2]
    src, dst = parse_pairs(a.pairs)
    if len(src) < 4:
        sys.exit("need at least 4 --pairs")
    H, inl = cv2.findHomography(src, dst, cv2.RANSAC if len(src) > 4 else 0, a.ransac_px)
    if len(src) > 4 and inl is not None and inl.sum() >= 4:
        keep = inl.ravel().astype(bool)          # least squares over all agreeing landmarks
        H, _ = cv2.findHomography(src[keep], dst[keep], 0)
    res = cv2.perspectiveTransform(src.reshape(-1, 1, 2), H).reshape(-1, 2) - dst
    part_p = parse_pts(a.part)
    part_s = cv2.perspectiveTransform(part_p.reshape(-1, 1, 2), H).reshape(-1, 2)
    warped = cv2.warpPerspective(prod, H, (w, h), flags=cv2.INTER_AREA, borderMode=cv2.BORDER_REPLICATE)
    covered = cv2.warpPerspective(np.ones(prod.shape[:2], np.float32), H, (w, h)) > 0.99
    part = poly_mask(scene.shape, part_s) & covered
    clip = poly_mask(scene.shape, parse_pts(a.clip)) if a.clip else np.ones((h, w), bool)
    part &= clip
    if not part.any():
        sys.exit("the part polygon lands outside the scene / clip")

    base = scene.copy()
    erase = poly_mask(scene.shape, parse_pts(a.erase)) & clip if a.erase else np.zeros((h, w), bool)
    if erase.any():
        u8 = (scene * 255).astype(np.uint8)
        base = cv2.inpaint(u8, (erase & ~part).astype(np.uint8) * 255, 7, cv2.INPAINT_TELEA).astype(np.float32) / 255

    # relight: L as a plane fitted on the surface just around the part, chroma by mean shift
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    k = max(15, int(0.12 * np.sqrt(part.sum())) | 1)
    ring = (cv2.dilate(part.astype(np.uint8), np.ones((k, k), np.uint8)) > 0) & ~part & clip & covered & ~erase
    if ring.sum() < 200:
        sys.exit("not enough surface around the part to match the lighting; enlarge --clip or shrink --erase")
    blur_sigma, detail_gain = 0.0, None
    if a.mode == "detail":
        # small parts on a textured surface (embossed logos, printing, stitching): keep the
        # scene's own shading and colour, take only the fine relief from the product
        # only the band where the part's lines live is swapped: the scene keeps its own shading
        # (below the band) and its own fine surface grain (above it), so no smooth patch shows
        lo, hi = a.detail_fine, a.detail_sigma
        def mid(img):
            y = img.mean(2)
            return (cv2.GaussianBlur(y, (0, 0), lo) if lo > 0 else y) - cv2.GaussianBlur(y, (0, 0), hi)
        mp, ms = mid(warped), mid(base)
        detail_gain = a.detail_gain or float(np.clip(ms[ring].std() / max(mp[ring].std(), 1e-4), 0.3, 2.5))
        if a.strokes_only:
            # where the product has structure coarser than its surface grain (letters, seams),
            # and only there: the grain around them stays the scene's
            e = cv2.GaussianBlur(np.abs(cv2.GaussianBlur(warped.mean(2), (0, 0), 1.5)
                                        - cv2.GaussianBlur(warped.mean(2), (0, 0), 4.0)), (0, 0), 1.5)
            lo_e, hi_e = np.percentile(e[part], [50, 92])
            wgt = cv2.GaussianBlur(np.clip((e - lo_e) / max(hi_e - lo_e, 1e-5), 0, 1), (0, 0), 1.0)
        else:
            wgt = np.ones((h, w), np.float32)
        relit = np.clip(base + (wgt * (detail_gain * mp - ms))[..., None], 0, 1)
    else:
        Ls, Lp = to_lab(base), to_lab(warped)
        out_lab = Lp.copy()
        out_lab[..., 0] = np.clip(Lp[..., 0] - plane(Lp[..., 0], ring, xx, yy, part)
                                  + plane(Ls[..., 0], ring, xx, yy, part), 0, 100)
        for ch in (1, 2):
            out_lab[..., ch] = Lp[..., ch] - Lp[..., ch][ring].mean() + Ls[..., ch][ring].mean()
        relit = from_lab(out_lab)
        # sharpness: a studio shot is usually crisper than the AI image around it
        target = hf_level(base, ring)
        for sgm in (0.0, 0.4, 0.7, 1.0, 1.4, 2.0):
            cand = cv2.GaussianBlur(relit, (0, 0), sgm) if sgm else relit
            blur_sigma = sgm
            if hf_level(cand, ring) <= target * 1.05:
                break
        if blur_sigma:
            relit = cv2.GaussianBlur(relit, (0, 0), blur_sigma)
    alpha = cv2.GaussianBlur(part.astype(np.float32), (0, 0), a.feather) * clip
    trans = alpha[..., None] * relit + (1 - alpha[..., None]) * base
    save_image(out / "transplant.jpg", trans, sinfo)

    # crop for the image model, expanded to the nearest supported aspect ratio
    ys, xs = np.nonzero(part)
    if a.box:
        bx = [int(v) for v in a.box.split(",")]
        xs, ys = np.array([bx[0] + a.margin, bx[2] - a.margin]), np.array([bx[1] + a.margin, bx[3] - a.margin])
    x0, x1 = xs.min() - a.margin, xs.max() + a.margin
    y0, y1 = ys.min() - a.margin, ys.max() + a.margin
    bw, bh = x1 - x0, y1 - y0
    ratio_name = min(RATIOS, key=lambda r: abs(np.log(RATIOS[r] * bh / bw)))
    r = RATIOS[ratio_name]
    if bw / bh < r:
        bw = int(round(bh * r))
    else:
        bh = int(round(bw / r))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    x0, y0 = int(round(cx - bw / 2)), int(round(cy - bh / 2))
    x0, y0 = min(max(0, x0), max(0, w - bw)), min(max(0, y0), max(0, h - bh))
    x1, y1 = min(w, x0 + bw), min(h, y0 + bh)
    crop = trans[y0:y1, x0:x1]
    up = 2048 / max(crop.shape[:2])
    to_pil(crop).resize((int(crop.shape[1] * up), int(crop.shape[0] * up)), Image.Resampling.LANCZOS).save(out / "blend_input.png")

    la = line_art(prod) * poly_mask(prod.shape, part_p)
    la_w = cv2.warpPerspective(la.astype(np.float32), H, (w, h)) > 0.4
    g = trans.copy()
    g[la_w & clip] = (0.9, 0.08, 0.08)
    save_image(out / "guide.jpg", g[y0:y1, x0:x1], None)
    prompt = BLEND_PROMPT.format(part=a.part_name, object=a.object_name)
    (out / "prompt.txt").write_text(prompt, encoding="utf-8")
    meta = {"scene": str(Path(a.scene).resolve()), "product": str(Path(a.product).resolve()),
            "H": H.tolist(), "pair_residual_px": [round(float(v), 1) for v in np.hypot(*res.T)],
            "box": [int(x0), int(y0), int(x1), int(y1)], "ratio": ratio_name, "part_name": a.part_name,
            "part_scene": part_s.round(1).tolist(), "clip": a.clip, "mode": a.mode, "relight_blur_sigma": blur_sigma, "detail_gain": detail_gain,
            "part_area_px": int(part.sum())}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    np.save(out / "part_mask.npy", part)
    print(json.dumps({k: meta[k] for k in ("box", "ratio", "pair_residual_px", "mode", "relight_blur_sigma", "detail_gain")}, ensure_ascii=False))
    print(f"next: image model with refs=[{out / 'blend_input.png'}] only, ratio {ratio_name}, prompt in {out / 'prompt.txt'}")


# ---------------------------------------------------------------- finish

def shape_score(ref, cand, mask):
    """How well the candidate keeps the transplanted part: correlation of fine structure."""
    a, b = band(ref), band(cand)
    m = mask & (np.abs(a) + np.abs(b) > 0)
    if m.sum() < 100:
        return 0.0
    a, b = a[m] - a[m].mean(), b[m] - b[m].mean()
    return float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-9))


def drift(ref, cand, mask, tile_px=None):
    """Largest local shift (px) between transplant and candidate inside the part.
    A redrawn part (different slant, spacing, extra element) shifts unevenly across it."""
    ys, xs = np.nonzero(mask)
    if len(xs) < 100:
        return 0.0, []
    t = tile_px or int(np.clip(np.sqrt(mask.sum()) / 3, 24, 96))
    a, b = band(ref, 0.8, 3.0), band(cand, 0.8, 3.0)
    win = cv2.createHanningWindow((t, t), cv2.CV_32F)
    shifts = []
    for y in range(ys.min(), ys.max() - t // 2, t // 2):
        for x in range(xs.min(), xs.max() - t // 2, t // 2):
            if y + t > mask.shape[0] or x + t > mask.shape[1] or mask[y:y + t, x:x + t].mean() < 0.6:
                continue
            pa, pb = a[y:y + t, x:x + t], b[y:y + t, x:x + t]
            if pa.std() < 1e-3 or pb.std() < 1e-3:
                continue
            (dx, dy), resp = cv2.phaseCorrelate(pa.astype(np.float32), pb.astype(np.float32), win)
            if resp > 0.08:
                shifts.append((x + t // 2, y + t // 2, float(np.hypot(dx, dy))))
    if not shifts:
        return 0.0, []
    return max(s_[2] for s_ in shifts), shifts


def tile(img, label, size):
    im = to_pil(img) if isinstance(img, np.ndarray) else img
    im = im.convert("RGB")
    im.thumbnail(size, Image.Resampling.LANCZOS)
    t = Image.new("RGB", size, (14, 16, 20))
    t.paste(im, ((size[0] - im.width) // 2, (size[1] - im.height) // 2))
    d = ImageDraw.Draw(t, "RGBA")
    f = font(26)
    tw = d.textlength(label, font=f)
    d.rounded_rectangle([8, 8, 24 + tw, 48], radius=8, fill=(20, 20, 24, 210))
    d.text((16, 12), label, font=f, fill=(255, 255, 255))
    return t


def cmd_finish(a):
    d = Path(a.dir)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    scene, sinfo = load_image(meta["scene"])
    trans, _ = load_image(d / "transplant.jpg")
    part = np.load(d / "part_mask.npy")
    x0, y0, x1, y1 = meta["box"]
    crop = trans[y0:y1, x0:x1]
    pm = part[y0:y1, x0:x1]
    ref_path = d / "_transplant_crop.png"
    to_pil(crop).save(ref_path)
    rows, best = [], None
    for c in a.candidates:
        r, views = cm.match(str(ref_path), str(c), None, return_views=True)
        cand = np.asarray((views or {}).get("output") if views and views.get("output") is not None
                          else load_image(c)[0], np.float32)
        al, valid, reg = retexture.align(crop, cand)
        sc = shape_score(crop, al, pm & valid)
        dmax, _ = drift(crop, al, pm & valid)
        row = {"candidate": str(c), "shape_score": round(sc, 3), "max_local_shift_px": round(dmax, 2),
               "registration": reg, "deltaE_after": (r.get("after") or {}).get("deltaE00_mean"),
               # protected: only the model's shading (blurred at protect_sigma) is used inside the part,
               # so a shift below that radius cannot move any line; unprotected: lines must not move
               "accepted": sc >= a.min_score and dmax <= (a.protect_sigma if a.protect else a.max_shift)}
        rows.append(row)
        print(f"{'OK  ' if row['accepted'] else '拒绝'}  {Path(c).name}  形状一致度 {sc:.2f}  局部最大位移 {dmax:.1f}px", flush=True)
        if row["accepted"] and (best is None or sc > best[0]):
            best = (sc, al, valid, c)
    report = {"dir": str(d), "candidates": rows, "min_score": a.min_score}
    if best is None:
        report["decision"] = "所有候选都改动了部件形状：重新出图，或直接用 transplant.jpg（未融合接缝）"
        print(report["decision"])
        (d / "finish_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    sc, al, valid, c = best
    m = np.zeros(crop.shape[:2], np.float32)
    b = max(8, min(crop.shape[:2]) // 16)
    m[b:-b, b:-b] = 1
    m = cv2.GaussianBlur(m, (0, 0), b / 3) * valid
    if a.protect:
        sg = a.protect_sigma
        inside = cv2.GaussianBlur(al, (0, 0), sg) + (crop - cv2.GaussianBlur(crop, (0, 0), sg))
        pa = cv2.GaussianBlur(cv2.dilate(pm.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32), (0, 0), 2.0)[..., None]
        al = np.clip(pa * inside + (1 - pa) * al, 0, 1)
    out = scene.copy()
    out[y0:y1, x0:x1] = m[..., None] * al + (1 - m[..., None]) * scene[y0:y1, x0:x1]
    dst = Path(a.out) if a.out else d / f"{Path(meta['scene']).stem}_part_fixed.jpg"
    save_image(dst, out, sinfo)
    report.update(chosen=str(c), output=str(dst))
    # board: before / transplant / result / product, all on the crop
    prod, _ = load_image(meta["product"])
    Hm = np.array(meta["H"])
    corners = np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]).reshape(-1, 1, 2)
    pc = cv2.perspectiveTransform(corners, np.linalg.inv(Hm)).reshape(-1, 2)
    px0, py0 = np.maximum(pc.min(0).astype(int), 0)
    px1, py1 = pc.max(0).astype(int)
    size = (720, int(720 * (y1 - y0) / (x1 - x0)))
    tiles = [tile(scene[y0:y1, x0:x1], "原图", size), tile(crop, "产品部件移植", size),
             tile(out[y0:y1, x0:x1], f"融合后（形状一致度 {sc:.2f}）", size),
             tile(prod[py0:py1, px0:px1], "产品图", size)]
    board = Image.new("RGB", (2 * size[0] + 10, 2 * size[1] + 10), (255, 255, 255))
    for i, t in enumerate(tiles):
        board.paste(t, ((i % 2) * (size[0] + 10), (i // 2) * (size[1] + 10)))
    board.save(d / "compare.jpg", quality=90)
    report["comparison"] = str(d / "compare.jpg")
    (d / "finish_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {dst}\n→ {d / 'compare.jpg'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grid")
    g.add_argument("image")
    g.add_argument("--out", required=True)
    g.add_argument("--box")
    g.add_argument("--step", type=int, default=50)
    g.add_argument("--scale", type=float)
    p = sub.add_parser("prep")
    p.add_argument("--scene", required=True)
    p.add_argument("--product", required=True)
    p.add_argument("--pairs", required=True)
    p.add_argument("--part", required=True)
    p.add_argument("--clip")
    p.add_argument("--erase")
    p.add_argument("--out", required=True)
    p.add_argument("--margin", type=int, default=60)
    p.add_argument("--ransac-px", type=float, default=20.0,
                   help="landmark pairs further off than this are dropped (e.g. a toe seen at a different angle)")
    p.add_argument("--box", help="force the crop box x0,y0,x1,y1 (scene coords)")
    p.add_argument("--feather", type=float, default=2.5)
    p.add_argument("--mode", choices=["patch", "detail"], default="patch",
                   help="patch: whole part with its own colour, relit (stripes, panels). "
                        "detail: scene shading + product fine relief only (logos, small text, stitching)")
    p.add_argument("--detail-sigma", type=float, default=4.0, help="detail mode: coarsest scale swapped (px)")
    p.add_argument("--detail-fine", type=float, default=1.0, help="detail mode: finer than this stays from the scene (surface grain)")
    p.add_argument("--strokes-only", action="store_true",
                   help="detail mode: transfer only the part's strokes (letters, seams), not the product's surface grain")
    p.add_argument("--detail-gain", type=float, help="strength of the product relief (default: match the surface texture)")
    p.add_argument("--part-name", default="product detail")
    p.add_argument("--object-name", default="product")
    f = sub.add_parser("finish")
    f.add_argument("--dir", required=True)
    f.add_argument("--candidates", nargs="+", required=True)
    f.add_argument("--out")
    f.add_argument("--min-score", type=float, default=MIN_SHAPE_SCORE)
    f.add_argument("--max-shift", type=float, default=MAX_LOCAL_SHIFT)
    f.add_argument("--no-protect", dest="protect", action="store_false",
                   help="let the model's version of the part through (default: inside the part only its shading is used)")
    f.add_argument("--protect-sigma", type=float, default=4.0)
    a = ap.parse_args()
    {"grid": cmd_grid, "prep": cmd_prep, "finish": cmd_finish}[a.cmd](a)


if __name__ == "__main__":
    main()
