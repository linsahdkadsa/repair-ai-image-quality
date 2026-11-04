#!/usr/bin/env python3
"""Wash step: send images to an image-edit model (Nano Banana / Gemini image) and save the results.

The controller's best repairs need one re-render by an image-edit model. This module does that call so the
whole thing is one command. Providers (pick with --provider, default: the first one that is configured):

  gemini   Google Gemini API, key in GEMINI_API_KEY (get one at https://aistudio.google.com/apikey; billed by Google)
           model default gemini-nano-banana-2.1 (--wash-model to change, e.g. gemini-3-pro-image)
  fal      fal.ai, key in FAL_KEY; model default fal-ai/nano-banana/edit
  cmd      any tool you already use: --wash-cmd 'mytool --in {input} --prompt-file {prompt} --out {output}'
           ({input} {prompt} {output} {ratio} are filled in; exit code 0 + a file at {output} = success)
  manual   nothing configured: writes a folder with the images, the prompt and step-by-step instructions
           for the Gemini app / AI Studio web page; put the results back and run `controller run`

Only the standard library is used (no SDK to install). Keys are read from the environment, never printed.
"""

import base64
import json
import mimetypes
import os
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

GEMINI_URL = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
FAL_URL = os.environ.get("FAL_BASE_URL", "https://fal.run")
RATIOS = {"1:1": 1, "3:2": 1.5, "2:3": 2 / 3, "3:4": 0.75, "4:3": 4 / 3, "4:5": 0.8, "5:4": 1.25,
          "9:16": 9 / 16, "16:9": 16 / 9, "21:9": 21 / 9}


def nearest_ratio(path):
    w, h = Image.open(path).size
    import math
    return min(RATIOS, key=lambda r: abs(math.log(RATIOS[r] * h / w)))


def available(provider=None, wash_cmd=None):
    if provider:
        return provider
    if wash_cmd:
        return "cmd"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    if os.environ.get("FAL_KEY"):
        return "fal"
    return "manual"


def _post(url, body, headers, timeout=300):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _find_image(obj):
    """First base64 image (or image URL) anywhere in a JSON response: works for the Interactions API,
    generateContent (inlineData), fal (images[].url) and data URIs."""
    if isinstance(obj, dict):
        mt = obj.get("mime_type") or obj.get("mimeType") or obj.get("content_type") or ""
        if isinstance(obj.get("data"), str) and len(obj["data"]) > 200 and (mt.startswith("image") or not mt):
            return ("b64", obj["data"])
        if isinstance(obj.get("url"), str) and (obj["url"].startswith("http") or obj["url"].startswith("data:image")):
            return ("url", obj["url"])
        for v in obj.values():
            r = _find_image(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_image(v)
            if r:
                return r
    return None


def _save(found, out):
    kind, val = found
    if kind == "url" and val.startswith("data:"):
        kind, val = "b64", val.split(",", 1)[1]
    if kind == "b64":
        out.write_bytes(base64.b64decode(val))
    else:
        with urllib.request.urlopen(val, timeout=300) as r:
            out.write_bytes(r.read())
    Image.open(out).verify()


def _b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


def _mime(path):
    return mimetypes.guess_type(str(path))[0] or "image/png"


def gemini(inp, prompt, out, ratio, model=None, size="2K"):
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    model = model or "gemini-nano-banana-2.1"
    h = {"x-goog-api-key": key}
    try:
        resp = _post(f"{GEMINI_URL}/interactions", {
            "model": model,
            "input": [{"type": "text", "text": prompt},
                      {"type": "image", "mime_type": _mime(inp), "data": _b64(inp)}],
            "response_format": {"type": "image", "mime_type": "image/png", "aspect_ratio": ratio, "image_size": size}}, h)
    except urllib.error.HTTPError as e:
        if e.code not in (400, 404):
            raise
        # older endpoint, still served for many keys and models
        resp = _post(f"{GEMINI_URL}/models/{model}:generateContent", {
            "contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": _mime(inp), "data": _b64(inp)}}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": ratio, "imageSize": size}}}, h)
    found = _find_image(resp)
    if not found:
        raise RuntimeError(f"no image in response: {json.dumps(resp)[:300]}")
    _save(found, out)


def fal(inp, prompt, out, ratio, model=None, size=None):
    model = model or "fal-ai/nano-banana/edit"
    resp = _post(f"{FAL_URL}/{model}", {"prompt": prompt, "num_images": 1, "output_format": "png",
                                        "aspect_ratio": ratio, "sync_mode": True,
                                        "image_urls": [f"data:{_mime(inp)};base64,{_b64(inp)}"]},
                 {"Authorization": f"Key {os.environ['FAL_KEY']}"})
    found = _find_image(resp)
    if not found:
        raise RuntimeError(f"no image in response: {json.dumps(resp)[:300]}")
    _save(found, out)


def cmd(inp, prompt, out, ratio, wash_cmd):
    pf = out.with_suffix(".prompt.txt")
    pf.write_text(prompt, encoding="utf-8")
    line = wash_cmd.format(input=shlex.quote(str(inp)), prompt=shlex.quote(str(pf)),
                           output=shlex.quote(str(out)), ratio=ratio)
    subprocess.run(line, shell=True, check=True, timeout=900)
    pf.unlink(missing_ok=True)
    if not out.exists():
        raise RuntimeError("the command finished but wrote no output file")
    Image.open(out).verify()


def manual(items, folder):
    """items: [(input_path, prompt)] -> folder with images + instructions."""
    folder.mkdir(parents=True, exist_ok=True)
    todo = folder / "待洗"
    todo.mkdir(exist_ok=True)
    done = folder / "洗好的放这里"
    done.mkdir(exist_ok=True)
    prompts = {}
    for inp, prompt in items:
        shutil.copy2(inp, todo / Path(inp).name)
        prompts.setdefault(prompt, []).append(Path(inp).name)
    lines = ["# 手动洗图（没有配置 API 时）", "",
             "1. 打开 Gemini（gemini.google.com）或 Google AI Studio（aistudio.google.com），选 Nano Banana / 图片模型。",
             "2. 每次上传「待洗」里的一张图，粘贴下面的提示词，生成。",
             "3. 下载结果，文件名保留原图名字（比如原图 123_枕头.png → 123_枕头_洗.png），放进「洗好的放这里」。",
             "4. 回到 Claude Code / Codex 说「洗好了」，或运行：", "",
             f"   run.sh controller run <原图们> --washed \"{done}\"", "", "## 提示词", ""]
    for p, names in prompts.items():
        lines += [f"适用于：{', '.join(names)}", "", "```", p, "```", ""]
    (folder / "怎么洗.md").write_text("\n".join(lines), encoding="utf-8")
    (folder / "提示词.txt").write_text("\n\n".join(prompts), encoding="utf-8")
    return done


def wash_all(items, out_dir, provider=None, model=None, wash_cmd=None, size="2K", retries=2, log=print):
    """items: [(input_path, prompt)]. Returns (provider, [washed paths], manual_folder_or_None)."""
    out_dir = Path(out_dir)
    prov = available(provider, wash_cmd)
    if prov == "manual":
        return prov, [], manual(items, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    done = []
    for inp, prompt in items:
        inp = Path(inp)
        out = out_dir / f"{inp.stem}_wash.png"
        if out.exists():
            done.append(out)
            log(f"已有  {out.name}")
            continue
        ratio = nearest_ratio(inp)
        for k in range(retries + 1):
            try:
                t = time.time()
                if prov == "gemini":
                    gemini(inp, prompt, out, ratio, model, size)
                elif prov == "fal":
                    fal(inp, prompt, out, ratio, model, size)
                else:
                    cmd(inp, prompt, out, ratio, wash_cmd)
                done.append(out)
                log(f"洗好  {inp.name} → {out.name}（{time.time() - t:.0f}s，{prov}）")
                break
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")[:200]
                if e.code in (401, 403):
                    raise SystemExit(f"{prov} 拒绝了请求（{e.code}）：key 不对或没开通图片模型。{msg}")
                log(f"失败  {inp.name}（{e.code}）{msg}" + ("，重试" if k < retries else ""))
            except Exception as e:  # network / bad output: retry, then move on
                log(f"失败  {inp.name}：{str(e)[:200]}" + ("，重试" if k < retries else ""))
            time.sleep(3 * (k + 1))
    return prov, done, None
