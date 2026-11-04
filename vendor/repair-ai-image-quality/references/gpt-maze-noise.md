# GPT image maze / worm noise

## What it is

GPT image models (seen on gpt-image-2 and gpt-image-2.5 at 2K) render many surfaces
with a labyrinth of 4–10 px "worms": velvet, knitwear, foam, fleece, skin, plaster.
At 100 % it looks like squiggles; scaled down, the surface just looks dirty or
grainy. Flat areas (white seamless backgrounds, skies) stay clean, so generic noise
estimators barely react: flat-area noise is only 0.3–0.4 levels.

Signature measured on 32 gpt-image outputs:

| Feature | GPT maze tiles | Natural texture (camera, Midjourney, banana) |
|---|---|---|
| mid-band bump m (power at 0.25–0.47 × Nyquist / r⁻² extrapolation) | 4 … 35 | 0.3 … 60: overlaps, not decisive alone |
| peak position q (power at 0.38–0.44 / power at 0.19–0.25) | ≈ 0.5 … 1.1 (still rising) | ≈ 0.2 (already falling) |
| cliff c (power at 0.56–0.70 / power at 0.37–0.50) | 0.05 … 0.10 | 0.25 … 1.2 at ≤ 3 MP; full-size camera files can also be < 0.1 (lens softness) |
| anisotropy (max / mean of 8 orientation sectors) | 1.8 … 2.5 | weave, knit, hair, text ≥ 3; fleece and sand are isotropic too |

The cliff means GPT images hold almost no real detail above ~0.55 × Nyquist. The
maze is texture the decoder hallucinates just below that limit.

## What is known about the cause

No primary source explains it. What is public (as of 2026-10):

- Users describe "cellular patterns", grime, stippling and tiling on fabric, skin,
  stone and walls. It gets worse later in a chat or edit chain, and prompting does
  not remove it ([OpenAI community: cellular patterns](https://community.openai.com/t/ai-artifacts-in-all-image-generations-cellular-patterns/1390816),
  [gpt-image-2 issue collection](https://community.openai.com/t/collection-of-gpt-image-generator-2-0-issues-bugs-and-work-around-tips-check-first-post/1379535),
  [repeated gpt-image-1 edits turn grainy](https://community.openai.com/t/multiple-gpt-image-1-high-fidelity-edits-lead-to-grainy-result/1320474)).
  Our edit-chain measurement agrees: the maze score doubled after the first GPT edit.
- An OpenAI researcher acknowledged a noise issue in gpt-image-2 in April–May 2026
  ([ApiPass write-up](https://apipass.dev/blogs/gpt-image-2-launch-tiling-texture-artifact)).
  Reviews of GPT Image 2.5 (September 2026) say it is reduced, not gone.
- GPT-ImgEval found that a detector built for up-sampling artefacts flags 99 % of
  GPT-4o images and attributes this to an internal super-resolution stage
  ([arXiv 2504.02782](https://arxiv.org/abs/2504.02782)).

Our reading (a hypothesis): an isotropic ring of energy with a sharp cut-off is what
band-limited synthesised texture looks like. A decoder or up-sampler that invents
detail just below its bandwidth limit produces exactly this, and isotropic
narrow-band noise is what the eye reads as a labyrinth.

## Second GPT artefact: the upscale grid

GPT images served at 2K/4K through some providers (measured on Higgsfield
`gpt_image_2_5` low/medium/high and `gpt_image_2`) carry a **fixed-phase 2×2
pattern**. In every 2×2 block the top-left pixel is slightly brighter and the
bottom-right slightly darker. It is the same everywhere (phase consistency 1.00)
and shows in R, G and B. Its amplitude follows local texture: ±0.3–0.5 levels on
average, ±1.2–1.5 on texture. Weaker period-4 and period-8 components ride along.
It is the footprint of an internal 2× upscale. It adds energy near Nyquist, which
breaks the maze "cliff" test, and it shows up as fine dotted grain once shadows
are lifted or the file is re-compressed.

| Source | period-2 z | phase consistency |
|---|---|---|
| Higgsfield GPT Image 2.5 / 2 (all quality tiers) | 40–207 | 0.98–1.00 |
| APIMart gpt-image-2.5 (2048²) | 0.1–1 | – |
| banana PNG / JPEG, Midjourney, photos | 6–19 | 0.62–0.90 |

`degrid()` runs first on the GPT route. It needs z ≥ 20 for a GPT-hinted image
(≥ 40 otherwise) and phase consistency ≥ 0.8. It estimates the global 2×2 (then
4×4 and 8×8) phase signature, fits only a local gain for that signature (σ 8/12/16
px windows) and subtracts it, per channel. On the test set the period-2 z dropped
from 40–207 to ≈ 0 with an average change of 0.1–0.7 levels. JPEG blocking is
content-dependent and fails the phase-consistency test, so it is left alone.

## Detection (`maze_confidence`, `presence_map`)

Per 32×32 tile (hop 8 px for processing, 16 px for scoring), soft-AND of five
sigmoids: bump (m > 2.5), cliff (c < 0.18), isotropy (anisotropy < 3.3), peak
(q > 0.38) and enough mid-band energy. Image gate (`gate`):

- file name / `--model` says GPT → process if `maze_score` ≥ 0.02;
- camera EXIF (Make/Model) or long side > 3200 px → skip unless `--model gpt` / `--force`
  (40 MP camera photos of canvas or fleece can mimic the signature at full size);
- otherwise process if `maze_score` ≥ 0.05.

`maze_score` = share of textured tiles with confidence > 0.5.

Where to filter is a property of a **region**, not a tile. Inside a velvet surface
the per-tile decision leaves salt-and-pepper holes, and every hole stayed dirty
next to cleaned neighbours: the blotchy look of the first release. `presence_map`
smooths the tile confidences (Gaussian, σ = 4 tiles = 32 px) and reaches full
strength at 35 % local density. On the white-background pillow shots it covers the
pillow and nothing else; skin, hair, knit and flat backgrounds stay at 0.

## Removal

### Default: learned filter (`cnn_luma`)

A small luminance U-Net predicts the maze and subtracts it:
`Y' = Y + (net(Y) − Y) · presence · min(1, strength/60)`. Only luminance changes;
ΔY is added equally to R, G and B, so chroma is untouched. Subtracting more than
the predicted maze prints an inverted maze (bump 0.9 at 1× → 4.1 at 1.5× on a
white-background main image), so above 60 `--strength` widens where the filter
applies instead: the local maze density that gets full strength drops from 35 %
to 15 % at 100.

- Network: two down/up levels, width 24, ~470 k parameters, residual output,
  bilinear ×2 + 3×3 conv for upsampling (no transposed convolutions). 1.9 MB ONNX,
  opset 13, run by OpenCV's DNN module, so there is no new dependency. Output
  matches PyTorch to within 0.0003 grey levels on OpenCV 4.8 and 5.0.
- Tiled at 1024² with 32 px overlap, so memory stays flat at 4K. About 2–3 s per
  2048² image on an Apple M-series CPU.
- Training data: real maze harvested from GPT 2.5 renders (band-pass 0.16–0.62 ×
  Nyquist of confident tiles, normalised by brightness), added to clean patches at
  0.2–1.4× amplitude and scaled by local brightness. 25 % of samples carry no maze,
  and texture-rich clean patches (skin, hair, knit, fleece, foliage) teach it what to
  keep. 30 % synthetic ring noise prevents memorising the harvested fields. Loss
  L1 + 0.5 × gradient L1, 30 k steps (56 min on an Apple M5 GPU). Recipe and scripts: [../training/](../training/README.md).
- If the model file is missing or OpenCV cannot run it, the spectral filter below
  takes over and the JSON report says so (`method`, `model_error`).

### Fallback: spectral subtraction (`demaze_luma`)

1. Overlapping 32×32 tiles, sine window, weighted overlap-add (16 phases, exact
   reconstruction at strength 0).
2. Per tile: natural level A·r⁻² from ring 1, maze profile S(r) estimated from the
   image's confident tiles (blended 50/50 with a measured prior), maze amplitude B by
   projection, smoothed spatially and multiplied by confidence.
3. Per ring gain `sqrt(max(gmin², 1 − α·B·S(r)/P(r)))`, uniform across the ring, so
   there is no musical-noise plaid. `--strength` 60 → α = 2.0, gmin = 0.15; 100 →
   α = 3.3, gmin = 0.08.
4. Harmonics (0.62–0.88 × Nyquist) are attenuated in step with the fundamental.
5. Strong oriented coefficients (P > 6–30 × ring mean, threshold falling with
   anisotropy) keep gain 1. This protects seams, edges, lettering and hair.

It lowers the spectral bump well but removes only about a quarter of the maze
amplitude, and what is left reads as blotches.

## Why not BM3D or another classical denoiser

The maze is correlated (coloured) noise with a known spectrum, which is a studied
problem. What the literature offers, and how it did on real maze:

- **BM3D for correlated noise** (Mäkinen, Azzari & Foi, "Collaborative filtering of
  correlated noise", IEEE TIP 2020) is the strongest published classical method: it
  computes the exact noise variance of every transform coefficient and corrects patch
  matching so it does not lock onto the noise. On their band-pass test kernel (a ring
  near 0.32 × Nyquist) it beats BLS-GSM, NLM and Noise Clinic. It cannot be shipped
  here: the reference `bm3d` package is free for non-commercial use only, and
  OpenCV's `xphoto.bm3dDenoising` is in the non-free build and assumes white noise.
- The part of it that is free to implement, transform-domain shrinkage with exact
  per-coefficient variances in two stages (hard-threshold pilot, then Wiener), was
  re-implemented and tested here with 16×16 block DCTs and dense overlap, after
  dividing out the brightness dependence. On real maze it scored 34.3–34.8 dB when
  given the true global maze spectrum and 30.5 dB with one estimated from the image
  (the noisy input is 31.3). Non-local means scored ≈ 30.6.
- Why they fall short: these methods assume stationary Gaussian noise with one
  spectrum. The real maze is neither. Its amplitude follows brightness, its cell
  size drifts across a surface, its cells have sharp walls (harmonics), and real
  velvet, skin and knit texture sits in the same band, which spoils any estimate
  of its spectrum. What matters is how strong the maze is in each place: told the
  true maze power of every tile, the same two-stage spectral filter reaches
  37.3 dB, and a Wiener filter that also knows the clean spectrum reaches 42.8 dB.
  Neither oracle is available on a real image. The learned filter estimates that
  local strength from the image itself and reaches 37.9 dB, slightly above the
  first oracle.
- IP note (not legal advice): US 9,123,103 B2 (MediaTek, in force until 2034) claims
  frequency-domain denoising of patches with a noise variance assessed from content.
  The spectral fallback estimates a per-tile maze amplitude in the Fourier domain;
  check before relying on it commercially. The learned filter works in the image
  domain.
- Practitioners otherwise regenerate, run the image through another model (for
  example a Nano Banana pass), or use GPU latent refiners with non-commercial
  licences. None of these are local and deterministic.

## Results

### Benchmark

Real maze harvested from two GPT 2.5 velvet renders (never used in training),
scaled by local brightness and added to 17 clean crops at 2K scale (camera fabric,
skin, grass, product, studio, AI portraits). The same set selected the training
checkpoint, so treat differences under 0.2 dB as noise.

| Method | PSNR (dB) | SSIM | band error / maze |
|---|---|---|---|
| noisy input | 31.32 | – | 1.00 |
| non-local means | ≈ 30.6 | – | – |
| block DCT, two-stage, spectrum estimated from the image | 30.5 | – | – |
| block DCT, two-stage, true global maze spectrum | 34.3–34.8 | – | – |
| spectral subtraction (fallback, strength 60) | 34.11 | 0.863 | 0.74 |
| first U-Net (transposed convs, 4 k steps) | 35.76 | 0.919 | 0.65 |
| **learned filter (shipped)** | **37.90** | **0.940** | **0.58** |
| oracle: two-stage spectral, told the true maze power of every tile | 37.29 | – | – |
| oracle: Wiener, told the true clean and maze spectra of every tile | 42.83 | – | – |

"Band error / maze" is the RMS error of the result in the maze band
(0.16–0.62 × Nyquist) relative to the maze that was added. It counts maze left
behind and real texture removed.

### Real renders

16 APIMart gpt-image-2.5 2K renders of a velvet product (white-background mains,
detail shots, a size chart, lifestyle scenes with people). Every one was detected and
processed. Measured on the 384 px crop with the most maze in each render:

| | bump (median of maze tiles) | tiles still classed as maze |
|---|---|---|
| input | 10.0 | 56 % |
| spectral fallback | 2.5 | 1.8 % |
| first U-Net | 0.6 | 0.2 % |
| learned filter (shipped) | 1.4 | 0.4 % |

The first U-Net pushed the bump lower by also flattening the velvet pile. The
shipped one keeps the pile's directional texture, which sits in the same band, so
its bump stays near the natural level of 1.

Over whole frames the learned filter changed 9–42 % of each image: the pillows,
and in one car scene a camel wool coat that GPT had drawn with the same maze.
Faces changed by 0.01–0.08 grey levels on average and knit sweaters by 0.04–0.26,
keeping ≥ 98 % of their fine detail. On the main images the bump went from 15–20
to 1.3–1.7, against 2.2–2.5 for the spectral filter. In a close-up where the
velvet pile is coarse and the maze shows only in scattered tiles, both filters
stay light on purpose (bump 8.3 → 5.1): isolated detections are not trusted.
Run time was 2.0–3.0 s per image including I/O.

### Non-GPT images

Detection and the gate are unchanged, so the skip decisions are as before. Of 60
non-GPT images (40 MP camera photos, banana, Midjourney, ink paintings, game art),
the only one processed was a layout exported from a GPT render.

### Higgsfield test set (night / low-light scenes, 2026-10)

21 GPT renders: 8 night or low-light scenes at GPT 2.5 high, 9 quality-tier
variants (GPT 2.5 low/medium, GPT Image 2 medium) and edit-chain outputs.

- Every render carried the upscale grid, and all were degridded.
- Flat-area grain was only σ 0.3–0.9 levels in every tier. Night scenes are not
  noisy in flat areas.
- The maze appears mainly on velvet. It was strongest with GPT Image 2. GPT 2.5
  *high* draws more worm detail on dark velvet than low/medium, but at low
  amplitude, so it scores below the processing threshold.
- GPT edit chains: the grid persists in every round (z 69–80). The maze score
  roughly doubled after the first edit (0.05 → 0.10).

### Which materials carry the maze (2026-10)

Ten close-ups rendered with gpt-image-2.5 at 2K, one per material, run through the
detector (maze score / share of the frame flagged):

| material | score | flagged |
|---|---|---|
| suede | 0.48 | 23 % |
| lime-plaster wall | 0.22 | 20 % |
| linen bedding | 0.09 | 8 % |
| camel wool coat | 0.02 | 2 % |
| pebbled leather | 0.02 | 1 % (below threshold) |
| knit sweater, terry towel, shaggy rug, memory foam, skin close-up | ≤ 0.004 | 0 % |

The maze lives on fine, matte, low-contrast surfaces (suede, velvet, plaster, linen),
where GPT's upsampler has to invent sub-texture. Coarse or high-contrast textures
(cable knit, terry loops, pebbled grain, pores) are not affected. One render per
material: treat it as a direction, not a rate.

## Tuning

- `--strength` up to 60 scales the learned correction: 60 (default) removes all
  the maze it finds, 30 half. 80–100 also treat patches where the maze is sparser,
  for residual worms at the edges of a dirty velvet surface.
- Real fine texture matters more than cleanliness (knit close-ups, pores the brief
  wants visible): `--strength 30–40`.
- To keep a region untouched, use the stand-alone `run.sh demaze IN OUT --protect-mask MASK`
  (white = keep).
- A render that was upscaled 2× after generation has a maze twice as large; the
  detector does not fire on it. Process the native-size file.
