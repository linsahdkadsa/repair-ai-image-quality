#!/usr/bin/env python3
"""One-click repair for AI-generated images.

  repair.py IMAGE [IMAGE ...]                    GPT image maze/worm noise (auto-detected)
  repair.py --source BASE EDIT [EDIT ...]        banana edit colour drift, matched to BASE
  repair.py --source BASE --chain V1 V2 V3 ...   multi-round edits: report the accumulated
                                                 drift per round and match every round to BASE

BASE must be the ORIGINAL image (the very first 底图), not the previous round:
banana drift accumulates round after round, and only the original is drift-free.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import color_match  # noqa: E402
import gpt_demaze  # noqa: E402
from common import comparison_board, load_image, save_image, to_pil  # noqa: E402


def out_paths(src, out_dir, suffix="_fixed"):
    src = Path(src)
    out_dir = Path(out_dir) if out_dir else src.parent / "repaired"
    ext = src.suffix.lower() if src.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff") else ".png"
    stem = src.stem + suffix
    return out_dir / (stem + ext), out_dir / (stem + ".json"), out_dir / (stem + "_compare.png")


def repair_one(image, source=None, out_dir=None, strength=60, color_strength=100, paste=False,
               demaze=True, color=True, model=None, force=False, keep_new_colors=False,
               ignore_mask=None, comparison=True, force_color=False):
    t0 = time.time()
    out_path, report_path, cmp_path = out_paths(image, out_dir)
    rgb, info = load_image(image)
    report = {"input": str(Path(image).resolve()), "source": str(Path(source).resolve()) if source else None,
              "steps": []}
    current = rgb
    demaze_res, conf = None, None
    if demaze:
        current, demaze_res, conf = gpt_demaze.process(rgb, info, image, strength, force, None, model)
        report["steps"].append(demaze_res)
    color_res, views = None, None
    if source and color:
        color_res, views = color_match.match(
            source, image, None, strength=color_strength, paste=paste, ignore_mask=ignore_mask,
            keep_new_colors=keep_new_colors, edit_image=(current, info), return_views=True,
            force_color=force_color)
        report["steps"].append(color_res)
        current = views["output"]
        info = views["info"]
    elif not source and color and _looks_like_edit(image, model):
        report["hint"] = "这张像 banana 改图：要校正偏色，请用 --source 指定最初的底图"
    changed = any(st.get("action") not in ("no-op", None) for st in report["steps"])
    save_image(out_path, current, info)
    report["output"] = str(out_path.resolve())
    if comparison and changed:
        panels, crops = [], []
        if views and views.get("src_view") is not None:
            panels.append(("原图（已对齐）", to_pil(views["src_view"])))
        panels.append(("输入", to_pil(rgb)))
        final_view = views["out_view"] if views and views.get("out_view") is not None else current
        panels.append(("修复后", to_pil(final_view)))
        if color_res and color_res.get("action") == "color-match":
            crops += views["crops"][:1]
        if demaze_res and "demaze" in demaze_res.get("action", ""):
            crops += gpt_demaze.pick_crops(conf, rgb.shape[:2], count=1 if crops else 2)
        comparison_board(cmp_path, "AI 图修复", summary_line(report), panels, crops=crops)
        report["comparison"] = str(cmp_path.resolve())
    report["seconds"] = round(time.time() - t0, 2)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report"] = str(report_path.resolve())
    return report


def _looks_like_edit(path, model):
    name = (model or Path(path).name).lower()
    return any(k in name for k in ("banana", "gemini", "nano"))


def summary_line(report):
    parts = []
    for st in report["steps"]:
        if st["route"] == "gpt-demaze":
            if (st.get("grid") or {}).get("applied"):
                parts.append("放大网格已去除")
            if "demaze" in st["action"]:
                parts.append(f"GPT 迷宫纹 覆盖{st['maze_score']:.0%} 凸起{st.get('maze_bump_before', '-')}→"
                             f"{st.get('maze_bump_after', '-')}")
            else:
                parts.append("迷宫纹：跳过")
        elif st["route"] == "banana-color":
            b, a = st.get("before") or {}, st.get("after") or {}
            if st["action"] == "color-match":
                parts.append(f"偏色 ΔE00 {b['deltaE00_mean']}→{a['deltaE00_mean']} · a* "
                             f"{b['lab_shift_edit_minus_source']['da']:+.2f}→"
                             f"{a['lab_shift_edit_minus_source']['da']:+.2f}")
            else:
                parts.append("校色：跳过")
    return " · ".join(parts) or "无改动"


def print_report(r):
    print(f"\n✓ {Path(r['input']).name}\n  → {r['output']}")
    for st in r["steps"]:
        if st["route"] == "gpt-demaze":
            g = st.get("grid") or {}
            if g.get("applied"):
                print(f"  GPT 放大网格：已去除（周期 2/4/8 z 值 {list(g['fold_z_before'].values())} → "
                      f"{list(g['fold_z_after'].values())}，平均改动 {g['mean_change_255']} 灰阶）")
            if "demaze" in st["action"]:
                how = "学习模型" if st.get("method") == "unet" else "频域滤波（备用）"
                if st.get("model_error"):
                    how += f"，模型未能运行：{st['model_error']}"
                print(f"  GPT 迷宫纹：覆盖 {st['maze_score']:.0%}，凸起 {st.get('maze_bump_before')} → "
                      f"{st.get('maze_bump_after')}（≈1 为自然纹理），方法 {how}，边缘保持 {st.get('edge_preservation')}")
            else:
                print(f"  GPT 迷宫纹：跳过（{st.get('decision')}）")
        else:
            if st["action"] == "color-match":
                b, a = st["before"], st["after"]
                print(f"  banana 偏色：未改动区域 {st['unchanged_fraction']:.0%}，ΔE00 {b['deltaE00_mean']} → "
                      f"{a['deltaE00_mean']}，Lab 偏移 {b['lab_shift_edit_minus_source']} → "
                      f"{a['lab_shift_edit_minus_source']}（模型 {st['model']}）")
                if st.get("paste_back"):
                    print(f"  回贴：改动区域 {st['paste_back']['edited_area_share']:.0%}，其余像素来自原图")
            else:
                print(f"  banana 偏色：跳过（{st.get('reason')}）")
    if r.get("hint"):
        print(f"  提示：{r['hint']}")
    if r.get("comparison"):
        print(f"  对比图：{r['comparison']}")


def main():
    ap = argparse.ArgumentParser(description="Fix GPT-image maze noise and banana edit colour drift.")
    ap.add_argument("images", nargs="+", help="images to repair (for --chain: rounds in order v1 v2 ...)")
    ap.add_argument("--source", help="the ORIGINAL base image the edits were made from (enables colour match)")
    ap.add_argument("--chain", action="store_true", help="images are successive edit rounds of --source")
    ap.add_argument("--out-dir", help="default: <image folder>/repaired")
    ap.add_argument("--strength", type=float, default=60, help="GPT maze removal 0-100 (default 60)")
    ap.add_argument("--color-strength", type=float, default=100, help="colour correction 0-100 (default 100)")
    ap.add_argument("--paste-back", action="store_true",
                    help="output in the source frame: only the edited region comes from the edit")
    ap.add_argument("--keep-new-colors", action="store_true",
                    help="do not remove the cast from colours that only exist in the edited region")
    ap.add_argument("--ignore-mask", help="white = region edited on purpose (never used for the colour fit)")
    ap.add_argument("--no-demaze", action="store_true")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--model", help="model hint for every image, e.g. gpt-image-2 / banana-pro")
    ap.add_argument("--force", action="store_true", help="run maze removal even if not detected")
    ap.add_argument("--force-color", action="store_true",
                    help="colour-match even when the difference is far beyond a banana cast")
    ap.add_argument("--no-compare", action="store_true", help="skip comparison boards")
    a = ap.parse_args()
    if a.chain and not a.source:
        ap.error("--chain needs --source (the original base image)")
    reports = []
    for img in a.images:
        r = repair_one(img, a.source, a.out_dir, a.strength, a.color_strength, a.paste_back,
                       not a.no_demaze, not a.no_color, a.model, a.force, a.keep_new_colors,
                       a.ignore_mask, not a.no_compare, a.force_color)
        print_report(r)
        reports.append(r)
    if a.chain:
        print("\n多轮累积偏色（每一轮都对照最初的底图）：")
        print("  轮次  改图前 ΔE00 / a* / b*        校正后 ΔE00 / a* / b*")
        rows = []
        for i, r in enumerate(reports, 1):
            st = next((s for s in r["steps"] if s["route"] == "banana-color"), None)
            if not st or not st.get("before") or not st["before"].get("deltaE00_mean"):
                print(f"  {i:>3}   无法对照（{(st or {}).get('reason', '-')}）")
                continue
            b, af = st["before"], st.get("after") or st["before"]
            bs, as_ = b["lab_shift_edit_minus_source"], af["lab_shift_edit_minus_source"]
            print(f"  {i:>3}   {b['deltaE00_mean']:>5} / {bs['da']:+.2f} / {bs['db']:+.2f}"
                  f"        {af['deltaE00_mean']:>5} / {as_['da']:+.2f} / {as_['db']:+.2f}")
            rows.append({"round": i, "input": r["input"], "before": b, "after": af})
        out_dir = Path(a.out_dir) if a.out_dir else Path(a.images[0]).parent / "repaired"
        (out_dir / "chain_report.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  链报告：{(out_dir / 'chain_report.json').resolve()}")


if __name__ == "__main__":
    main()
