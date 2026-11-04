# Multi-round editing without colour drift

## Why it gets worse every round

Each banana edit re-renders the whole frame and adds its own cast on top of the
input's colours. The next round takes that drifted image as its input, so the casts
stack:

| Outdoor original (8000×6000) → | a\* vs original | ΔE00 vs original |
|---|---|---|
| round 1: sky replaced, 2K (banana-pro) | +1.69 | 2.2 |
| round 2: 4K upscale of round 1 (banana-pro) | **+3.87** | **4.7** |

Correcting round 2 against round 1 removes only round 2's own drift (+2.19). Round
1's +1.6 remains baked in. Correcting round 2 against the **original** brings a\* to
−0.07 and ΔE00 to 1.0.

### Controlled 5-round test (Higgsfield, 2026-10)

Bases were generated with GPT Image 2.5. Each round was a small local edit
("add an earring", "add a candle", ...) with "keep everything else exactly the
same". The **raw chain** fed each output straight into the next round. The
**corrected chain** matched each output back to the base before the next round.
All values are vs the base, over the whole unchanged area (edited region removed,
local mean colour; see "How it is measured" in
[banana-color-drift.md](banana-color-drift.md)):

| Chain | R1 a\* | R2 | R3 | R4 | R5 | R5 ΔE00 → after matching to base |
|---|---|---|---|---|---|---|
| portrait, banana-pro, raw | +1.37 | +2.55 | +3.64 | +5.13 | **+6.37** | 8.51 → 1.43 |
| portrait, banana-pro, corrected | +1.37 | +1.64 | +1.49 | +1.67 | +1.74 | 2.93 → 1.57 |
| whisky bar (night), banana-pro, raw | +1.50 | +3.25 | +4.98 | +6.76 | **+8.51** | 7.25 → 1.89 |
| whisky bar, banana-pro, corrected | +1.50 | +2.09 | +2.25 | +2.76 | +2.45 | 3.23 → 2.18 |
| portrait, Banana 2, raw | +0.86 | +1.77 | +2.63 | +3.54 | +4.23 | 5.46 → 1.46 |
| white-background pillow, banana-pro, raw | −0.17 | −0.17 | −0.17 | −0.14 | −0.13 | 3.49 → 0.71 |
| white-background pillow, GPT 2.5 edits, raw | −0.24 | −0.43 | −0.58 | −0.66 | −0.73 | 1.80 → 0.53 |

- banana-pro adds about **+1.3 to +1.8 a\* per round** on people and warm scenes,
  plus a slight brightening; Banana 2 about +0.85. On the white-background
  product shot the white backdrop does not drift (hence the near-zero a\*), but the
  grey velvet pillow itself turns lavender (a\* +6 by round 5, and it was reshaped
  along the way). The correction now brings it back to the original grey
  (pillow after correction a\* +0.33 / L\* 56.5, original +0.42 / 56.5).
- The corrected chain never accumulates. Each round carries only its own single-round
  cast, which is then removed.
- After correction, every content type in every round stays within a\* −0.33 …
  +1.14 of the base; all except the jeans in the corrected portrait chain stay
  within ±0.4. No region goes green.
- Six people scenes (elderly man, freckled woman, man in knitwear in a café, street
  fashion, child in fleece, dinner group) gave the same picture: a\* +0.96–1.63
  after one banana-pro edit, +2.07–3.43 after two, +3.07–5.06 after three. Matching
  to the base brought ΔE00 from 4.42–5.94 down to 0.95–1.35. Intentional red
  additions (beanie, mittens) were kept.
- The ΔE00 that remains after matching (≈0.5–2) is texture banana re-rendered,
  not cast. Higgsfield also re-encodes uploaded inputs as a resized JPEG, which
  slightly raises it on the corrected chain.

## Standard procedure

1. **Keep the original** (the first 底图 / product photo). It is the only drift-free
   reference.
2. **After every banana round**, match the result back to the original before doing
   anything else:
   ```bash
   scripts/run.sh --source ORIGINAL ROUND_N.jpg
   ```
3. **Feed the corrected file** (`repaired/ROUND_N_fixed.jpg`) into the next edit, not
   the raw banana output. Then each round starts drift-free and the cast never
   compounds.
4. If rounds were already made without correction, fix them all at once and inspect
   the accumulation table:
   ```bash
   scripts/run.sh --source ORIGINAL --chain R1.jpg R2.jpg R3.jpg
   ```
   This also writes `repaired/chain_report.json`.
5. For deliverables that must match the original pixel-for-pixel outside the edit
   (e-commerce main images), finish with `--paste-back`.
6. For GPT-image rounds, the maze filter runs automatically on each output. Applying
   it to the final deliverable is the minimum; applying it between rounds is harmless.

## Finding the original automatically

Asset libraries that record references make this deterministic: follow the
reference chain (`refs` → `@编号底图` / `@name`) to its root, and use that file as
`--source`. When an edit used several references, the first one is usually the
image being edited. Check that it has the same framing before trusting it.

## When NOT to match colours

- The edit's purpose is a global colour change (sunset, warmer grade, black-and-white,
  "make the whole scene blue"). The tool would undo it. Skip the colour step
  (`--no-color`) or mask the area (`--ignore-mask`).
- The edit re-composed the scene (new camera angle, new pose). Too little is
  unchanged, so the tool reports `no-op`.
