# banana edit colour drift

## What the drift looks like

Measured on 41 well-registered "original → nano-banana edit" pairs from a real
production library (unchanged areas only, edit minus original):

| Edit type | a\* (+ = magenta/red) | b\* (− = blue) | L\* | RGB pattern |
|---|---|---|---|---|
| banana-pro, 2K edits | +0.4 … +1.1 | −0.3 … 0 | ±0.3 | R↑ G↓ B↑ |
| banana-pro, 4K outputs / upscales | **+2.2 … +3.1** | −1.3 … −1.8 | ±0.4 | e.g. [+4.8, −1.6, +3.8] /255 |
| banana-2 edits | +0.4 … +1.3 | −0.2 … +0.5 | up to +1.7 (brighter) | R↑ G↑ B↑, R most |

- The cast depends on **lightness**: some edits leave shadows untouched and shift
  mids/highlights by +1.1 … +1.9 L\*; others are strongest in shadows. Highlights
  tend toward blue (b\* −2 … −3 after several rounds).
- It also depends on the **colour itself**. At the same lightness, banana drifts skin,
  hair and wood about twice as far as a grey wall (after five Banana 2 rounds: +5.4
  vs +2.8 a\*), greens less, and it pushes blues further blue (jeans: b\* −5 against
  −1.6 for the frame). One global offset, or one offset per lightness, therefore
  over-corrects some colours and under-corrects others.
- On flat walls the cast can vary across the frame by ±1.5 a\*.
- Every banana edit also re-renders the picture: **1–2 px shift, ~0.2 % downscale**
  (ECC scale 0.997–0.998), and new texture in skin, hair, knit, velvet and foliage.
  Pixel-by-pixel comparison without registration is meaningless, and pixel-level
  "unchanged" tests reject exactly the areas people look at.
- The drift **accumulates over rounds**: about +1 a\* per banana-pro round on people and
  warm scenes in a controlled Higgsfield test. See
  [multi-round-workflow.md](multi-round-workflow.md).

## Algorithm (`scripts/color_match.py`)

1. **Analysis copies** at 1024 px long side; the source is loaded at ≤ 2048 px unless
   `--paste-back` needs full resolution (sources can be 100 MP).
2. **Registration**: ECC translation → affine from identity when aspect ratios match;
   otherwise (crop / outpaint / new aspect) SIFT/ORB matches + RANSAC similarity.
   The higher gradient-correlation score wins.
3. **Cast estimate (`CastModel`)** from pixels that are certainly unchanged: textured,
   structurally identical (15 px NCC > 0.8), and no lightness jump > 10 L\* (banana
   brightens ~0.5 L\* per round; a bigger jump is new content or a misaligned
   outline). Two passes, the second without pixels the first cannot explain. There
   is one lightness profile for near-neutral source colours and one for coloured
   ones, blended by source chroma. Pixels are binned by the pair's *mean* L\*
   (binning by the edit's L\* biases the difference where texture was re-rendered).
4. **Candidates**, all gated by the cast-compensated ΔE00 < 8, the lightness-jump
   test and a chroma-residual limit (6 + 0.35·source chroma, capped at 10):
   - *pixel level*: structure match as above;
   - *coarse level*: wherever banana re-rendered texture (skin pores, hair strands,
     knit, velvet, foliage), the shading still matches after a σ = 6 px blur
     (41 px NCC > 0.85, object outlines excluded). Without this level a portrait is
     fitted on its background wall alone.
5. **Recoloured backdrops**: banana's drift cannot give a truly neutral source a
   colour. Bright near-neutral regions of the source (overcast sky, wall, backdrop),
   traced on sharp colours, are treated as an intentional edit as a whole when a
   quarter of them clearly gained colour. Their nearby fringe counts too (the pale
   haze of a new blue sky, also between grass blades). The cast is re-estimated
   without them.
6. **Training pairs**: the sharp pair where the structure is identical; elsewhere the
   pixel's own colour with the *local mean shift* as target, so the model sees the
   light and dark threads of re-rendered fabric that it will be applied to.
7. **Robust inliers**: a curve fit, then curve + LUT fits; pixels with ΔE above
   max(3, 3·median) and coherent regions with a smoothed residual above
   max(2, 1.8·median) are dropped. The exception is **drift-like regions**: those
   that moved in the cast's a\*b\* direction (within 30°, up to 2× as far). Without
   this exception a face is dropped for being more magenta than the wall. A
   recolour moves in another direction and stays excluded.
8. **Evidence checks**, each a `no-op` with its reason:
   - the only match is a *coloured* flat backdrop (green or magenta screen, textured
     matches < 3 %): a re-generation, not an edit;
   - **grey source**: where the structure matches (recoloured backdrops left out), the
     source's 95th-percentile chroma is below 8 or below 0.6× the edit's (edit > 15).
     A white model (白模), grey render, sketch or desaturated reference carries no
     colour truth; matching to it greys out a colourful edit (measured: 0.18 and 0.53
     for two "白模材质恢复" pairs, ≥ 0.76 for every real edit, 0.93 for a sky
     replacement once its sky is left out);
   - **implausibly large cast**: the certainly-unchanged pixels moved by more than
     8 L\* or 12 a\*b\* (five accumulated banana-pro rounds reach ~8.5). That is an
     intentional regrade, relight or new backdrop; `--force-color` corrects anyway.
9. **Model levels**, chosen by 2-fold spatial-block cross-validation at half analysis
   resolution (a level must beat the simpler one by ≥ 3 %):
   - `curves`: per-channel monotone tone curves (64-bin medians → weighted isotonic
     regression → slope-1 extrapolation → light smoothing);
   - `+lut`: residual 17³ 3D LUT (trilinear splat, σ 0.7-cell smoothing, light
     shrinkage) for colour-dependent drift;
   - `+spatial`: low-frequency per-channel offset field (σ = 12 % of the short side).
10. **Support blending**: a colour counts as seen when about 20 fitted pixels fall
    within one LUT cell (counted on all inliers, with no colour-space blur). Unseen
    colours (a new blue sky, a recoloured product) receive only the cast measured on
    unchanged pixels of their kind, neutral or coloured, at their lightness. Its tone
    part is slope-limited to 0.85–1.15 so it cannot stretch texture contrast.
    `--keep-new-colors` leaves them untouched instead.
11. **New content stays neutral**: on content with no counterpart in the source at
    either scale (new objects) and on recoloured backdrops, an a\* or b\* channel
    that is near zero (|value| < 6, fading out by 12) may be corrected toward zero
    but never across it. The cast is removed, not inverted.
12. Apply to the full-resolution edit; `--color-strength` blends.

### Why the first release turned corrected images green

On the Higgsfield test set, corrected portraits and the bar looked *greener* than
the original. These are the causes, each fixed above:

- Only pixel-identical areas were used for fitting. In portraits that left the
  background wall: 4 % of skin pixels and 0 % of dark hair survived (step 4, coarse
  level).
- The outlier rejection then removed faces as "intentional recolours" because they
  drifted further than the wall (step 7, drift-like regions).
- The support threshold scaled with the training-set size (0.002·N ≈ 500 samples).
  Small regions (a face, a plant) therefore got only half the fit and half the
  fallback cast. That cast was dominated by the wall, or by skin and wood. Faces
  kept their magenta, and greens, blues and bright highlights went green: the dinner
  scene's highlights reached a\* −3.7 (step 10).
- The LUT's colour-space smoothing pulled small colour regions toward the much larger
  populations next to them.

A second report ("still green") came from **new objects**. These are things banana
added, which my per-region metric excluded together with the edited area: a grey
scarf and cap, a white daisy, a snowman. The colour model works per colour, not
per place, so a daisy drawn without any cast (a\* −0.4) received the correction
learned from the drifted white T-shirt (+2.5) and ended at −1.7. A grey scarf
added two rounds earlier (+2.8, while the wall drifted +3.6) got the stronger
drift of the jacket and shadows and ended at −1.6. Step 11 keeps such near-neutral
channels from crossing zero; the scarf and cap now end at −0.2, the daisy at −0.5
(it started at −0.4), the snowman at −0.2. Unchanged pixels keep the exact model
output, because the source's own greys may be slightly green (the portrait wall
sits at a\* −1.4). The comparison page also defaults to "original ↔ corrected":
next to the magenta uncorrected image any correct result looks greenish.

### The failures the safeguards fix

On a "grey sky → blue sky" edit the first prototype treated the new sky as unchanged
(flat area, similar luminance). It "corrected" the sky back to grey and turned the
jacket pink. The colour gate (step 4), regional rejection (step 7) and support
blending (step 10) prevent this. Making the fit trust small regions (step 10)
re-opened the problem through the sky's pale fringe near the horizon. That haze had
changed by only ~5 b\* and slipped into the fit, where it taught "pale blue → grey".
Step 5 closes it: the new sky now keeps b\* −14.3 / −6.9 (upper / lower) against
banana's −16.4 / −9.5. The difference is the bright-tone cast measured on the jacket,
removed from the sky like everywhere else.

Game sprites re-posed on a green screen used to "match" only through the backdrop.
A screen shade change of a\* +8.3 was then applied to the whole character. The
evidence check (step 8) now reports these as re-generations.

## Results

### How it is measured

The report's `before` / `after` numbers are measured on the pixels used for the
fit, so they look better than what a viewer sees. All numbers below follow a
viewer-style protocol instead:

- Align the base to the edit and remove the area the edit really changed (big
  cast-compensated colour change or changed structure).
- Compare the *local mean* colour (4 px blur at 1024 px) of corrected vs base over
  everything else, so banana's re-rendered texture does not count as colour error.
- Report per content type: skin/warm, foliage, blue/cool, neutral grey, shadows,
  mid-tones and highlights (median a\*, b\*, L\*). Also report the share of 32 px
  blocks that end up visibly greener or more magenta than the base (|Δa\*| > 1).

### Controlled Higgsfield set (GPT 2.5 bases, banana edits, 16 images)

| Image | ΔE00 raw | first release | **now** | most-off region, first release | **now** |
|---|---|---|---|---|---|
| portrait, banana-pro round 5 | 8.51 | 2.86 | **1.42** | shadows/hair a\* +5.03 | jeans b\* −1.60 |
| portrait, Banana 2 round 5 | 5.46 | 2.51 | **1.46** | skin a\* +3.38 | blue b\* −0.54 |
| whisky bar, banana-pro round 5 | 7.25 | 2.32 | **1.89** | warm a\* +2.15 | warm b\* −0.36 |
| white-background pillow, round 5 | 3.49 | 3.51 | **0.68** | pillow left lavender | mid-tones a\* +0.14 |
| elderly man, round 3 | 5.94 | 1.67 | **1.16** | skin a\* +2.07 | shadows b\* −0.13 |
| knit café, round 3 | 4.52 | 1.67 | **1.34** | skin b\* +2.47 | foliage b\* −0.28 |
| boy in snow, round 3 | 4.61 | 1.19 | **1.02** | skin a\* +3.40 | skin a\* +0.34 |
| dinner, round 3 | 4.59 | 1.16 | **1.01** | highlights a\* −3.66 | highlights a\* −0.07 |

Over all 16 images the most-off region dropped from a mean of 1.88 to **0.42**
(median 1.90 → 0.27). Skin and warm areas went from +0.2 … +4.0 a\* to −0.02 … +0.34.
The remaining ΔE00 of ~1–1.9 is re-rendered texture, not cast.
The bar's near-black wood (L\* ≈ 13) still shows block-level noise of ±1.6 a\* in both
directions; at that lightness a few RGB levels already move a\* that much.

### Production library

All 322 "original → banana edit" pairs of a production library (311 readable
images; the others were videos). Most are re-generations from style references
and are correctly skipped:

| Outcome | Pairs |
|---|---|
| colour-matched | 83 |
| skipped: different framing / too little overlap / alignment failed | 218 |
| skipped: already matching | 5 |
| skipped: grey source (white model) | 2 |
| skipped: implausibly large cast (regrade) | 2 |
| skipped: coloured screen only | 1 |

On the 83 matched pairs (viewer-style, unchanged area): ΔE00 median 1.29 → **0.61**
(mean 1.75 → 0.85); 82 improved. The most-off content type has a median of
**0.15** and a 90th percentile of 0.49; blocks visibly greener than the original
have a median of 0 % (max 7 %). Two pairs score worse only because the metric can
compare almost nothing in them: a face close-up generated from a full-body
reference (1 % of the frame comparable) and a nursery shot whose "source" is a
different scene. In both, the correction removes a light magenta cast and looks
right. Intentional edits were kept: on "grey sky → blue sky" and "sky made bluer"
the new sky stays blue (ΔE00 vs the uncorrected sky 1.9–2.6 and 0.8–0.9). The
grassland pairs with added cattle or sheep keep their animals (ΔE00 1.0–1.5).

## Report fields

- `unchanged_fraction`: share of the frame used for fitting (`--mask-out` shows it:
  green = used, red = changed or excluded); `unchanged_rerendered_fraction` is the
  part of it that came from the coarse level (texture banana re-rendered).
- `before` / `after`: `deltaE00_mean`, `deltaE00_p90`, `lab_shift_edit_minus_source`
  (median dL / da / db; da > 0 means magenta/red), measured on the fitted pixels.
- `model`, `cv_deltaE00`: chosen level and the cross-validated error of every level.
- `registration`: kind (identity / translation / affine / features), score, shift, scale.
- `unchanged_textured_fraction`: share of the frame that is unchanged AND textured
  (the evidence check in step 5).
- `action`: `color-match` or `no-op` with `reason` (too little unchanged area,
  alignment failed, only a coloured screen matches, grey source, already matching).

## Paste-back (`--paste-back`)

Outputs in the **source frame at source resolution**. The colour-corrected edit is
warped back onto the original, and only the changed region is composited in: the
structural change, the cast-sized coherent recolours, plus a dilated, feathered rim.
Every other pixel is the original. This suits product shots that must stay identical
outside the edited area. Do not use it when the edit intentionally changed global
lighting.
