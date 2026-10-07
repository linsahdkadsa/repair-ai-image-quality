#!/usr/bin/env python3
"""GPT maze controller: decide, per image, how to get rid of the maze, run it, check it.

Two steps, because the best repair needs an image-edit model this script cannot call:

    controller.py plan IMG [IMG ...]               -> plan.json: which images need a wash, and the prompt
    (re-render each listed image with an image-edit model, e.g. Nano Banana 2,
     same aspect ratio and size; any image-edit tool works)
    controller.py run IMG [IMG ...] --washed DIR   -> repaired images + report

Decision per image (`run`):
  no maze detected                -> left as is
  no washed version supplied      -> local maze filter (smooth; works offline)
  wash agrees with the original   -> FUSE: original colour + structure, wash fine texture
  wash moved / redrew details     -> whole wash, colour-matched back to the original, flagged for review
  wash redrew a lot (> 50 %)      -> same, plus `rewash` in the report: generate it again
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import color_match as cm  # noqa: E402
import gpt_demaze as gd  # noqa: E402
import retexture  # noqa: E402
from common import comparison_board, load_image, luma, save_image, to_pil  # noqa: E402

WASH_PROMPT = ("Keep this image exactly the same: same composition, framing, product shape, buttons, labels, "
               "text, people, lighting, colors and background. Only re-render the velvet / fabric surfaces so "
               "they look clean, soft and natural like a real photo, removing the squiggly maze-like noise texture.")
FUSE_MAX_REJECT = 0.15    # share of the maze region where the wash disagrees with the original's structure
REWASH_REJECT = 0.50
EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}


def detect(path, model=None):
    rgb, info = load_image(path)
    is_gpt = gd.looks_like_gpt(path, model)
    skip = gd.pre_gate(rgb.shape[:2], info, is_gpt, False)
    if skip:
        return rgb, info, {"maze_score": None, "needs_repair": False, "reason": skip}
    Y = luma(rgb) * 255.0
    _, dinfo = gd.maze_detect(Y)
    ok, why = gd.gate(dinfo["maze_score"], Y.shape, info, is_gpt, False)
    return rgb, info, {"maze_score": round(float(dinfo["maze_score"]), 4), "needs_repair": bool(ok), "reason": why}


def find_washes(orig, washed_paths):
    """All washed candidates of `orig`: names containing orig's stem, or the number that
    leads orig's name (some asset libraries keep it: 5204_..._4992_name).
    Several candidates (SeedVR2, banana with different prompts...) are all tried."""
    stem = orig.stem
    num = re.match(r"(\d{3,})_", orig.name)
    out = [w for w in washed_paths if stem in w.stem and w.resolve() != orig.resolve()]
    if num:
        pat = re.compile(rf"(^|_){num.group(1)}(_|$)")
        out += [w for w in washed_paths if pat.search(w.stem) and w.resolve() != orig.resolve() and w not in out]
    return sorted(set(out))


def _crop_boxes(rgb, conf, n=2, side=320):
    boxes = gd.pick_crops(conf, rgb.shape[:2], count=n, size=side) if conf is not None and conf.size > 1 else []
    return boxes


def run_one(path, wash_path, out_dir, strength=60, model=None):
    t0 = time.time()
    rgb, info, det = detect(path, model)
    rec = {"input": str(path), "wash": None, **det}
    stem = path.stem
    out_path = out_dir / f"{stem}_fixed{path.suffix if path.suffix.lower() in ('.png', '.jpg', '.jpeg') else '.png'}"
    if not det["needs_repair"]:
        rec.update(method="none", output=None, decision="没有检测到需要处理的迷宫纹，保持原图")
        return rec
    local, lres, conf = gd.process(rgb, info, str(path), strength, False, None, "gpt" if model is None else model)
    if wash_path is None:
        out = local
        rec.update(method="local", decision="没有洗过的版本：用本地迷宫纹滤波（偏平滑）。想要真实绒毛质感，先用 plan 的提示词洗一遍再 run",
                   maze_bump_before=lres.get("maze_bump_before"), maze_bump_after=lres.get("maze_bump_after"))
    else:
        # every candidate is fused; the one whose structure agrees best wins
        best = None
        rec["candidates"] = []
        for wp in (wash_path if isinstance(wash_path, (list, tuple)) else [wash_path]):
            washed, _ = load_image(wp)
            f_out, f_rep = retexture.fuse(rgb, washed, info, str(path), strength, local=local)
            rec["candidates"].append({"wash": str(wp), "rejected": f_rep["wash_rejected_fraction"]})
            if best is None or f_rep["wash_rejected_fraction"] < best[2]["wash_rejected_fraction"]:
                best = (wp, f_out, f_rep)
        wash_path, fused, frep = best
        rec["wash"] = str(wash_path)
        rec["fuse"] = frep
        rej = frep["wash_rejected_fraction"]
        if rej <= FUSE_MAX_REJECT:
            out = fused
            rec.update(method="fuse", decision=f"洗过的图和原图结构一致（迷宫纹区域里只有 {rej:.0%} 对不上）：融合，颜色和结构用原图，细纹理用洗过的图")
        else:
            r, views = cm.match(str(path), str(wash_path), None, return_views=True)
            corrected = (views or {}).get("output")
            if corrected is None:
                corrected, _ = load_image(wash_path)
            # back into the original's framing (banana sometimes zooms or shifts the shot);
            # anything the wash does not cover is filled from the original
            aligned, valid, reg = retexture.align(rgb, np.asarray(corrected, np.float32))
            a = retexture._feather(valid, 4.0)[..., None]
            out = a * aligned + (1 - a) * rgb
            rec["wash_registration"] = reg
            ca = r.get("after") or {}
            cb = r.get("before") or {}
            rec["color"] = {"action": r.get("action"), "deltaE00_before": cb.get("deltaE00_mean"), "deltaE00_after": ca.get("deltaE00_mean")}
            rec.update(method="wash+color", review=True,
                       decision=f"洗过的图改动了 {rej:.0%} 的迷宫纹区域结构（明暗、接缝或细节位置），不适合融合："
                                f"整张用洗过的图并校回原图颜色。请看对比图确认产品细节没变")
            if rej > REWASH_REJECT:
                rec["rewash"] = True
                rec["decision"] += "；改动太多，建议再洗一次"
    out = np.clip(out, 0, 1).astype(np.float32)
    save_image(out_path, out, info)
    rec["output"] = str(out_path)
    # board: original / result (+ wash when used), two crops where the maze was strongest
    panels = [("原图", to_pil(rgb))]
    if wash_path is not None:
        w, _ = load_image(wash_path)
        import cv2
        panels.append(("洗过的图（未处理）", to_pil(cv2.resize(w, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_AREA))))
    panels.append((f"结果（{ {'local': '本地滤波', 'fuse': '融合', 'wash+color': '整张洗图+校色'}[rec['method']]}）", to_pil(out)))
    board = out_dir / f"{stem}_fixed_compare.png"
    comparison_board(board, path.name, rec["decision"], panels, crops=_crop_boxes(rgb, conf), crop_zoom=2)
    rec["comparison"] = str(board)
    rec["seconds"] = round(time.time() - t0, 1)
    return rec


def collect(paths):
    out = []
    for p in map(Path, paths):
        if p.is_dir():
            out += sorted(q for q in p.iterdir() if q.suffix.lower() in EXTS)
        else:
            out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="detect the maze and list the images that need a wash")
    p.add_argument("images", nargs="+")
    p.add_argument("--out", default=None, help="plan.json path (default: <first image folder>/repaired/plan.json)")
    p.add_argument("--model", help="source model hint, e.g. gpt-image-2")
    r = sub.add_parser("run", help="repair: fuse / colour-match washed versions, or filter locally")
    r.add_argument("images", nargs="+")
    r.add_argument("--washed", nargs="*", default=[], help="washed files or folders (matched by name or leading number)")
    r.add_argument("--out-dir")
    r.add_argument("--strength", type=float, default=60)
    r.add_argument("--model")
    a = ap.parse_args()
    imgs = collect(a.images)
    if a.cmd == "plan":
        rows = []
        for f in imgs:
            _, _, det = detect(f, a.model)
            rows.append({"input": str(f), **det, "wash_prompt": WASH_PROMPT if det["needs_repair"] else None})
            print(f"{'需要洗' if det['needs_repair'] else '跳过  '}  {f.name}  迷宫纹 {det['maze_score']}  {det['reason']}", flush=True)
        out = Path(a.out) if a.out else imgs[0].parent / "repaired" / "plan.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"wash_prompt": WASH_PROMPT, "images": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n{sum(r['needs_repair'] for r in rows)} / {len(rows)} 张需要处理 → {out}")
        print("下一步：用图像编辑模型（如 Nano Banana 2，同比例同尺寸）按 wash_prompt 重绘这些图，然后 run --washed <输出文件夹>")
        return
    washed = collect(a.washed) if a.washed else []
    recs = []
    for f in imgs:
        if washed and any(f.resolve() == w.resolve() for w in washed):
            continue
        out_dir = Path(a.out_dir) if a.out_dir else f.parent / "repaired"
        out_dir.mkdir(parents=True, exist_ok=True)
        cands = find_washes(f, washed) if washed else []
        rec = run_one(f, cands or None, out_dir, a.strength, a.model)
        recs.append(rec)
        flag = "  ⚠ 请人工确认" if rec.get("review") else ""
        print(f"{rec['method']:10} {f.name}  {rec['decision']}{flag}", flush=True)
    if recs:
        out_dir = Path(a.out_dir) if a.out_dir else imgs[0].parent / "repaired"
        (out_dir / "controller_report.json").write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")
        n = {m: sum(r["method"] == m for r in recs) for m in ("none", "local", "fuse", "wash+color")}
        print(f"\n融合 {n['fuse']} · 整张洗图+校色 {n['wash+color']} · 本地滤波 {n['local']} · 不处理 {n['none']}"
              f"；需要人工确认 {sum(bool(r.get('review')) for r in recs)}，建议重洗 {sum(bool(r.get('rewash')) for r in recs)}")


if __name__ == "__main__":
    main()
