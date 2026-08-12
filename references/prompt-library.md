# Prompt library

Use the shortest route-specific prompt that describes the visible safe defect. Replace bracketed fields with concrete observations. Do not combine every route into one edit.

## Shared invariant block

Append this block to every editing prompt:

> Treat the supplied image as the absolute appearance reference. Preserve the exact composition, crop, camera, subject identity, pose, face, hands, text, object count, silhouettes, geometry, depth ordering, lighting direction, colors, style, materials, ornament density, and all legitimate fine detail. Do not add, remove, merge, split, redesign, relight, recolor, restyle, or globally smooth anything outside the specified defects.

## Noise route

Run the deterministic one-click script before prompting when the noise is stochastic and frame-wide:

```powershell
python scripts/one_click_denoise.py SOURCE OUTPUT --strength 60 --detail-mode auto --protected-mask MASK --report REPORT.json --comparison COMPARISON.png
python scripts/check_fidelity.py SOURCE OUTPUT --preset strong-denoise --protected-mask MASK --json
```

Use the following prompt only for a residual localized defect:

> Remove only the unintended [luminance speckles / chroma speckles / compression grit / dirty gradient residue] visible in [specific regions]. Reconstruct clean local color transitions from neighboring pixels while preserving edges, intentional grain, paper or brush texture, stippling, glow particles, reflections, and real micro-detail. Keep sharpness natural; do not create halos or plastic surfaces.

For night or saturated scenes, add:

> Preserve the physical logic of colored light, glow falloff, fire, sparks, neon reflections, deep shadow texture, and atmospheric grain. A bright colored particle is not noise unless it is visibly detached from the scene's lighting or surface logic.

Do not ask a generative editor to “denoise harder.” Raise the deterministic controller ceiling and let candidate scanning select the strongest passing output. If every stronger candidate loses coherent texture, keep the lower accepted result.

## Clarity route

Use only when the image is genuinely muddy while geometry remains coherent:

> Improve local separation in [specific regions] by correcting low-level haze and weak tonal transitions already implied by the source. Preserve the original depth of field, softness, grain, edge character, depth ordering, and lighting. Do not globally sharpen, increase saturation, deepen contrast, invent texture, or reconstruct geometry.

## Noise + clarity route

Do not create a combined prompt. Run the noise prompt first. After acceptance and compositing, run the clarity prompt against the accepted base.

If geometry is ambiguous, return:

> Structural repair skipped: the source does not contain enough trustworthy geometry to separate the fused volume without redesigning it. Safe noise or clarity cleanup can still proceed elsewhere.

Do not offer a structural repair route from this skill, even when a guide is supplied.

## Negative instruction discipline

Prefer a compact invariant block to long lists of stylistic negatives. If a new failure appears, first decide whether it belongs in routing, masking, validation, or a safe route-specific prompt. Do not expand every prompt with the same failure.
