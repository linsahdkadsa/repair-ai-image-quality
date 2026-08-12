# Routing and guardrails

## Public routes

### No-op

Choose `no-op` when the image is coherent and the suspected noise is plausibly intentional:

- film grain or sensor-like texture consistent across materials;
- ink stippling, paper fibers, brush texture, halftone, or painterly marks;
- physically plausible sparks, rain, snow, dust, stars, bokeh, or glow particles;
- dense decoration whose contours remain attached to real objects.

Do not call an image defective merely because it is detailed.

### Noise

Choose `noise` when defects are non-semantic:

- isolated luminance or chroma speckles in otherwise flat fields;
- compression grit, block boundaries, mosquito noise, or dirty gradients;
- random high-frequency residue that does not follow surfaces or contours.

Night and neon scenes require stronger evidence. Preserve plausible glow falloff, sparks, reflections, film grain, colored light, and shadow texture.

Use only the deterministic denoise script when the residue is stochastic and spread across the frame. If the defect cannot be represented as pixel/chroma noise or safe clarity correction, leave it unchanged.

### Clarity

Choose `clarity` only when geometry is intact but local separation is reduced by:

- low-level haze;
- weak tonal transitions between already coherent surfaces;
- soft compression residue that makes existing edges look dirty.

Do not use clarity repair to invent edges, change depth of field, or reconstruct volume.

### Noise + clarity

Choose `noise+clarity` only when both safe classes are independently visible. Run separate passes:

1. conservative noise cleanup;
2. validation and accepted composite;
3. local clarity correction;
4. final validation.

## Out-of-scope geometry

Do not create a structural repair candidate. Leave the affected pixels unchanged when the image contains:

- fused or melted object boundaries;
- ambiguous front/back ordering;
- contours that stop, split, or reconnect impossibly;
- malformed anatomy or object geometry;
- repeated motifs that mutate into incoherent pseudo-detail.

This remains out of scope even when:

- the intended contour looks obvious;
- the user supplies or generates a line, depth, normal, or edge guide;
- a prompt or frequency blend appears to preserve texture;
- only one object is affected.

For mixed images, safe noise/clarity cleanup may proceed outside the affected region. A trusted guide does not expand this skill's scope.

## Protected regions

Treat these as high-risk and unchanged unless the user explicitly requests repair and trustworthy evidence exists:

- faces, eyes, mouths, hands, fingers, and body silhouettes;
- readable text, logos, symbols, and signatures;
- object count, placement, ownership, and depth order;
- jewelry, lace, hair edges, eyelashes, thin wires, fences, and repeated ornaments;
- highlight clusters, fire, sparks, reflections, neon, and star fields;
- intentional grain and illustration texture.

If a safe defect overlaps a protected region, shrink the mask or skip it.

## Strength mapping

| Controller | Method | Detail mode | Risk | Acceptance |
|---:|---|---|---|---|
| 0 | no-op | source | none | source |
| 1–35 | conservative deterministic + partial NLM candidate | `natural` or `line-art` | low | cleanup + strict fidelity + texture gate |
| 36–70 | adaptive guided/NLM ensemble | `auto`, `natural`, or `line-art` | low | candidate scan; default 60 |
| 71–100 | adaptive strong deterministic | `natural` or `line-art` | medium | candidate scan with automatic fallback |

Command mapping:

- `1–35` → conservative profile plus nested partial NLM writebacks
- `36–60` → adaptive guided/NLM candidates, reaching full NLM writeback at `60`
- `61–70` → full `auto` profile as a ceiling; do not force a method switch
- `71–100` → adaptive `strong`, then `auto`, then `conservative` fallback

Select `line-art` behind the controller for inked illustrations with broad color fields. Select `natural` for photographic, painterly, 3D, or cinematic images. Strength never authorizes structural editing.

Use the hidden `high` route for faces, hands, text, and dense micro-detail. It may evaluate only luminance/chroma-separated NLM, never whole-color NLM. Use the hidden `sparse-lines` risk route for circuit traces, thin wires, filaments, star fields, and isolated glow on a dark field. Cap that route at the conservative guided profile and disable NLM because global edge correlation can remain high after valid sparse energy has already been erased.

Use a white-on-black `--protected-mask` for regions that must remain pixel-identical. In night scenes, protect coherent sparks, rain streaks, neon letters, small specular highlights, and readable signs only when automatic texture protection is insufficient.

## Acceptance gate

Reject a candidate if visual inspection finds:

- changed identity, face, hand, pose, text, object count, ownership, or depth order;
- shifted crop, camera, horizon, or major silhouette;
- altered lighting direction, palette, style, material identity, or depth of field;
- erased legitimate ornament or intentional grain;
- new decoration, duplicated edges, halos, plastic smoothing, or flattened volume.

Run `scripts/check_fidelity.py` on the full image and important crops. Default numerical guardrails:

- same canvas size;
- full-image RGB MAE no higher than 12/255;
- edge correlation at least 0.70;
- coarse luminance correlation at least 0.985.

For controller values `36–100`, require the integrated one-click gate and optionally confirm with `check_fidelity.py --preset strong-denoise`:

- input-output RGB MAE no higher than 12/255;
- input-output edge correlation at least 0.95, preferably 0.97 or higher;
- coarse luminance correlation at least 0.995;
- visible luminance-noise reduction without flattened coherent texture;
- visible chroma-noise reduction without color bleeding across luminance boundaries.
- structured high-frequency retention above the route-specific floor (`0.975` for high-risk, `0.99` for sparse lines, noise-adaptive for standard images).

If the strict gate fails, the candidate is not the accepted result. Continue the writeback/profile fallback scan. Do not return a failed preview as the main result.

Do not use percentage noise reduction as an acceptance signal when the measured pre-cleanup noise is near zero. Inspect the image and prefer `no-op` or `保守`.

For protected-region masks, require much stricter similarity. Metrics cannot overrule a visible semantic or 3D error.

### Hidden fallback behind the controller

Treat the requested controller value as the maximum permitted cleanup:

1. Build the mapped guided profile and, when OpenCV is available, fixed colored/channel-separated NLM candidates.
2. Scan nested writeback amounts up to the requested ceiling. Higher controller values retain lower passing candidates.
3. Reject NLM candidates that lose structured high-frequency energy even when edge correlation passes.
4. If no amount passes, move to the next safer profile and repeat.
5. Require at least `12%` measured luminance-noise reduction or `20–25%` chroma-noise reduction in addition to fidelity.
6. If every candidate fails, accept the unchanged source.
7. When estimated luminance residue is approximately `1.25/255` or lower and chroma residue is approximately `1.50/255` or lower, prefer `no-op`, except a dark line-art image may test only the high-risk channel-separated route; these are conservative confidence thresholds, not universal definitions of noise.

The UI remains one controller. The fallback profile, masks, validation, and rollback stay internal, but reports must record the effective accepted strength.

## Rollback

- Keep the source as base version 0.
- Accept each local safe pass independently.
- Composite only accepted regions.
- Roll back failed or structurally ambiguous regions to the last accepted base.
- If every candidate fails, return the unchanged source and say the edit was safely skipped.
