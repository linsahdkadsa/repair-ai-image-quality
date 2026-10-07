---
name: repair-ai-image-quality
description: Fixes two systematic defects of AI image models, locally and deterministically (no regeneration). (1) GPT image (gpt-image-1 / 2 / 2.5, ChatGPT) "maze / worm" texture noise - labyrinth squiggles on velvet, knit, foam, skin, walls that make surfaces look dirty or grainy. (2) Gemini nano-banana (banana-pro, banana-2) edit colour drift - unchanged areas come back magenta/pink with a tone shift versus the original, and the drift accumulates over multi-round edits. Use when the user mentions GPT 生图噪点 / 颗粒 / 蚯蚓纹 / 迷宫纹 / 绒面发脏, or banana 改图偏洋红 / 偏粉 / 偏紫 / 色调和原图不一致 / 越改越红, or wants an edited image's colours matched back to its original 底图. Also: (3) product details an image model drew wrong (stripes, overlays, logos, embossed text) can be restored from a real product photo with `transplant` - use when the user says 产品细节不对 / 条纹不对 / logo 字乱 / 还原产品.
---

# Repair AI Image Quality

Two independent, measured repairs behind one command:

| Problem | Model family | What the tool does |
|---|---|---|
| Maze / worm texture noise, upscale grid | GPT image | Removes the fixed 2×2/4×4/8×8 upscale grid some providers leave, then the 4-10 px labyrinth itself with a small network trained on real GPT maze, only where the maze is detected and only in luminance; skin, hair, edges and colour are kept |
| Magenta cast / tone drift after edits | nano-banana | Aligns the edit to the ORIGINAL image, finds what the edit did not change (including faces, hair and fabric that banana re-rendered), fits a per-colour mapping there and applies it to the whole edit; intentional recolours (a new sky, a new garment colour) are excluded from the fit |

## Commands

Use `scripts/run.sh` (macOS/Linux) or `scripts/run.ps1` (Windows). First use builds a private runtime in `runtime/` (numpy, Pillow, OpenCV); set `REPAIR_AI_IMAGE_PYTHON` to reuse an existing Python that has `scripts/requirements.txt`.

```bash
# GPT image noise (auto-detected; non-GPT images are skipped)
scripts/run.sh IMAGE [IMAGE ...]

# banana edit colour drift - BASE must be the ORIGINAL first image (底图)
scripts/run.sh --source BASE EDIT [EDIT ...]

# multi-round edits: per-round drift table, every round matched to BASE
scripts/run.sh --source BASE --chain ROUND1 ROUND2 ROUND3

# keep every unchanged pixel bit-identical to BASE (output in BASE's frame/resolution)
scripts/run.sh --source BASE EDIT --paste-back
```

Outputs go to `<image folder>/repaired/` (`--out-dir` to change): `<name>_fixed.<ext>`, `<name>_fixed.json`, `<name>_fixed_compare.png`. The GPT step and the colour step both run when applicable (`--no-demaze`, `--no-color` to skip one). Single-purpose entry points: `run.sh demaze IN OUT`, `run.sh color SRC EDIT OUT`, `run.sh selftest`.

## GPT maze: the controller (preferred when an image-edit tool is available)

The local filter removes the maze but leaves the surface smooth. The best result comes from letting an
image-edit model re-render the fabric, then keeping only what it is good for. Drive it end to end:

1. `scripts/run.sh controller plan IMAGES...` - detects the maze; writes `repaired/plan.json` with the images
   that need a wash and the exact `wash_prompt`.
2. For every listed image, call an image-edit model with that prompt and the image as the reference, same
   aspect ratio and size (any image-edit model: Nano Banana 2 / Pro via Gemini, an API aggregator, or the
   user's own tool; GPT image works too). Name the output after the original (same stem or its leading
   number) or put the washes in one folder.
   If this session has no image-edit tool, hand `plan.json` to the user: they wash the listed images in any
   app, drop the results in a folder, and you run step 3. Without washes, `run` falls back to the local filter.
3. `scripts/run.sh controller run IMAGES... --washed WASH_DIR_OR_FILES` - per image:
   * wash agrees with the original's structure (<= 15 % of the maze region differs) -> **fuse**: colour and
     everything coarser than ~10 px from the original, fine luminance texture from the wash (no colour cast);
   * wash moved or redrew details -> whole wash, colour-matched back to the original and warped into its
     framing, flagged `review` - open the board and check the product details;
   * > 50 % redrawn -> also `rewash`: generate that image again (new seed) and rerun;
   * no wash supplied -> local filter.
4. Report from `repaired/controller_report.json`; show the `_fixed_compare.png` boards of every `review` item.

## Product details drawn wrong: transplant from the real product photo (EXPERIMENTAL, unstable)

Validated on only a few products and not reliable yet: it fixed scrambled logo lettering, but stripe
curvature/width, serrated edges, stitching and material sheen often still differ from the product, and the
harmonize pass can soften or shift details. Tell the user it is experimental and always show the result
next to the product photo before calling it done.

Image models redraw small product parts the way such parts "usually" look (stripes parallel and evenly
spaced, an extra stripe, logo letters re-typeset level). Prompts, line-art guides and product references
do not stop it. What works is real pixels: map the part from a product photo shot from the same side,
then let the model only blend.

1. `run.sh transplant grid IMG --out g.png [--box x0,y0,x1,y1]` on the scene and the product photo; read
   4+ landmark pairs off the grids **on the object's fixed structure, spread over the whole object** (heel,
   collar, lace-panel ends, sole line). Never on the part being fixed: the model drew it wrong, so its
   position and angle are exactly what must not be copied.
2. `run.sh transplant prep --scene AI.jpg --product PRODUCT.jpg --pairs "px,py=sx,sy; ..." --part "x,y; ..."
   [--clip ...] [--erase ...] --out DIR` - `--mode patch` (default) for stripes and panels, `--mode detail
   --strokes-only` for embossed logos / small text (keeps the scene's shading, takes only the relief).
3. One image-edit pass on the whole image with a one-line prompt: "Harmonize this photo: make the
   lighting, color, sharpness and texture uniform across the whole product so every part looks
   photographed together in one shot. Change nothing else." Short prompts move the geometry least; do
   not attach the product photo here (the model then redraws the part its own way). 3-4 candidates.
4. `run.sh transplant finish --dir DIR --candidates C1 C2 ...` scores every candidate (overall structure
   + per-tile shift) and rejects the ones whose part moved; then colour-match the winner to the scene
   base (`run.sh --source BASE WINNER --no-demaze`).
5. Show the result **next to the product photo, whole object, same scale** - not only the part the user
   pointed at. Count the elements (stripes, rows of teeth, letters) against the product.

Rules learned the hard way: start every attempt from the clean base, never from a previous attempt (each
layer of edits leaves patches); one AI pass per attempt; compare material too (glossy nylon vs matte
canvas is as visible as a wrong stripe). Embossed logos: let the model erase the scene's text, have it
trace the product logo into a black/white mask (verify against the product), warp the mask with the
landmarks and emboss it - letting the model "blend" lettering re-typesets it.

## Workflow rules

1. **Anchor colour to the original.** Always pass the very first image as `--source`, never the previous round. Banana drift adds up (measured: round 1 a* +1.7, round 2 a* +3.9); matching to the previous round leaves the earlier drift baked in.
2. **Correct every round before the next edit.** In iterative editing, run the colour match right after each banana result and use the corrected file as the next round's input, so drift never compounds.
3. **Identify the base.** If the user's asset library records references (e.g. `@编号底图`, refs in an index), follow the ref chain to its root. The base must carry the true colours: a white model (白模), sketch, depth or line render is not a colour reference. If no original exists, say colour matching needs one; do not invent a reference.
4. **Global colour edits.** If the edit's purpose IS a global colour change (sunset, warmer grade, B&W), skip the colour step or pass `--ignore-mask` for the edited region; the fit cannot tell a deliberate global grade from a cast.
5. **Show the result.** Open the comparison board and quote the numbers from the JSON: maze `maze_bump_before → maze_bump_after` (natural texture is ≈1 or below), `presence_fraction` (share of the frame filtered), `method` (`unet` = learned filter; `spectral` = fallback, with `model_error` saying why) and `edge_preservation`; colour `before/after deltaE00_mean` and `lab_shift_edit_minus_source.da` (positive = magenta/red), plus `unchanged_fraction`. The colour numbers are measured on the pixels used for the fit; say so, and let the user judge skin and backgrounds on the board.
6. **No-op is a valid answer.** Every skip carries a `decision` / `reason` (no maze found, camera photo, too little unchanged area, already matching, grey/white-model source, difference far beyond a banana cast). Relay it instead of forcing (`--force`, `--model gpt`, `--force-color` exist for confirmed cases).

## Tuning

- `--strength 0-100` (default 60): maze removal. Up to 60 it scales the correction (60 removes all the maze found, 30 half); 80-100 also treat patches where the maze is sparser (residual worms on very dirty velvet/knit). 30-40 when fine real texture matters more.
- `--color-strength 0-100` (default 100): blend of the colour correction.
- `--keep-new-colors`: colours that exist only in the edited region keep banana's rendering (default removes the global cast from them too, which keeps the whole frame consistent).
- `--ignore-mask MASK`: white = deliberately edited area, never used for the colour fit.
- `--force-color`: correct even when the unchanged area moved far beyond any banana cast (|L\*| > 8 or |a\*b\*| > 12). Only use it after the user confirms the edit was not meant as a regrade.

## Limits

- The maze filter targets the GPT spectral signature only; it is not a general denoiser (JPEG blocks, film grain, Midjourney grain are left alone). Images with camera EXIF or a long side > 3200 px are skipped unless `--model gpt`. A GPT render upscaled 2× after generation has a maze twice as large and is not detected: process the native-size file.
- Colour matching needs an alignable original and at least ~10 % unchanged area. Re-framed edits (crop/outpaint) are aligned with feature matching; completely re-composed images are reported as no-op.
- The maze and colour repairs never redraw content. Product-detail transplant needs a same-side product
  photo and enough flat surface to map; strongly curved parts (toe caps) or a very different camera angle
  map poorly. Faces, identity and free text are out of scope.
- What needs an image-edit model: the maze wash (optional - the local filter works offline) and the
  harmonize pass of a transplant. Everything else runs locally with Python only.

Details and measurements: [references/gpt-maze-noise.md](references/gpt-maze-noise.md), [references/banana-color-drift.md](references/banana-color-drift.md), [references/multi-round-workflow.md](references/multi-round-workflow.md). Retraining the maze model for a new GPT version: [training/README.md](training/README.md).
