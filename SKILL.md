---
name: repair-ai-image-quality
description: One-click strong denoise and clarity repair for AI-generated images with luminance noise, chroma noise, speckles, compression grit, dirty gradients, dark-field blotches, or muddy local separation. Use when the user wants obvious noise removal or a cleaner and clearer image while preserving composition, identity, objects, geometry, lighting, colors, style, intentional texture, and legitimate fine detail. Broken, fused, melted, duplicated, or incoherent geometry is outside this skill's scope and must remain unchanged.
---

# Repair AI Image Quality

Expose one simple action: clean noise and improve clarity while keeping the source appearance stable. Keep routing, candidate scanning, protected regions, validation, and rollback internal.

Highest principle: **require both visible cleanup and fidelity; otherwise return the source unchanged**.

## User interface

Expose one `去噪强度` controller from `0–100`. Use `60` by default.

- `0`: unchanged source.
- `1–35`: conservative deterministic cleanup.
- `36–70`: adaptive deterministic cleanup. The default `60` opens the full non-local-means writeback and original `auto` candidate; higher values remain a cleanup ceiling.
- `71–100`: adaptive strong deterministic cleanup with automatic fallback. Fine texture may simplify; mark the result medium-risk when the accepted effective strength exceeds `70`.

Never call a generative redraw from this controller. A higher value increases the deterministic cleanup ceiling, but the accepted effective strength may be lower when a fidelity gate rejects the requested candidate.

## Workflow

1. Inspect the source at full view and representative 100% crops.
2. Record protected invariants: canvas, crop, camera, subject identity, face, hands, pose, text, object count, silhouettes, geometry, lighting direction, palette, style, material identity, ornament density, and intentional grain.
3. Route internally:
   - `no-op`: no confident defect;
   - `noise`: unintended pixel/chroma noise, compression speckles, dirty flat fields, or dirty gradients;
   - `clarity`: low-level haze or muddy tonal separation with intact geometry;
   - `noise+clarity`: both safe defect classes are independently visible.
   If the visible problem is broken, fused, melted, duplicated, or incoherent geometry, classify it as out of scope rather than as a repair route.
4. Read [references/routing-and-guardrails.md](references/routing-and-guardrails.md) before editing. Read only the selected safe route in [references/prompt-library.md](references/prompt-library.md).
5. For pixel/chroma noise on Windows, run `scripts/run_one_click.ps1`; it guarantees that the complete OpenCV-backed candidate set is available instead of silently degrading. Use `--detail-mode auto` unless visual inspection clearly identifies inked line art. Use the hidden `--content-risk high` hint for faces, hands, readable text, or dense micro-detail. Use `--content-risk sparse-lines` for sparse glow, circuits, wires, stars, filaments, or bright lines on dark fields. Supply `--protected-mask` when protected pixels must remain identical.
6. Let the one-click script scan hidden guided, colored-NLM, and luminance/chroma-separated NLM candidates plus safer writeback amounts. High-risk content may use only the channel-separated NLM route; sparse-line content never uses NLM. It must accept the best requested candidate that passes visible-cleanup, texture-retention, and strict fidelity gates. It must return `no-op` when every candidate fails. If OpenCV is unavailable, it must transparently fall back to the original guided route.
7. Run `scripts/check_fidelity.py ... --preset strong-denoise` when independently auditing the accepted output. Treat metrics as guardrails, not proof.
8. Never attempt structural reconstruction. Keep broken or ambiguous geometry unchanged, and continue only with independently safe noise/clarity regions. Do not increase denoise strength to hide fused pseudo-detail or broken object topology.
9. Reject and roll back any region that changes a protected invariant. Returning the unchanged source or a partial cleanup is a valid success.
10. Return the accepted result, JSON report, and before/after comparison. At an accepted effective strength above `70`, state the medium-risk texture-simplification class.

## One-click command

```powershell
& scripts/run_one_click.ps1 SOURCE OUTPUT --strength 60 --detail-mode auto --protected-mask MASK --report REPORT.json --comparison COMPARISON.png
python scripts/check_fidelity.py SOURCE OUTPUT --preset strong-denoise --protected-mask MASK --json
```

The installed Skill carries a dedicated runtime. If it is absent after moving the Skill to another machine, run `scripts/setup_runtime.ps1 -Python PATH_TO_PYTHON` once. On non-Windows systems, install `scripts/requirements.txt` and call `one_click_denoise.py` directly. Omit `--protected-mask` only after verifying that the full frame contains no pixel-identical protected region. Require `opencv_available: true` in the report for the full candidate set; an explicit `guided-fallback` is safe but not the best tested route. The one-click wrapper scans deterministic guided and NLM candidates, quantizes before validation, preserves white mask pixels exactly, records texture retention, and records every rejected and accepted attempt.

## Editing rules

- Preserve intentional film grain, stippling, paper texture, brush texture, glow particles, reflections, and legitimate ornament.
- Prefer small coherent masks over semi-transparent global blends.
- For global stochastic noise, use the deterministic one-click script instead of generative repainting.
- Treat the public controller value as a cleanup ceiling, not a promise to apply that exact internal profile. Keep strict-gate fallback and no-op routing behind the controller.
- Protect faces, hands, text, logos, subject silhouettes, coherent objects, and depth boundaries by default.
- Do not add, remove, merge, split, or redesign people, objects, windows, jewelry, tableware, buildings, limbs, or decorative motifs.
- Do not change crop, camera, pose, facial identity, lighting direction, palette, style, or material identity.
- Do not use a white-model conversion, generated replacement geometry, or broad restyling intermediate.
- Do not claim “lossless,” structural repair, or “works on every image.”

## Iteration

When a result fails, classify the failure before modifying prompts. Read [references/evaluation-and-iteration.md](references/evaluation-and-iteration.md).

- If the wrong safe route ran, fix routing.
- If a protected invariant changed, tighten masks or rollback rules.
- If safe noise/clarity was under-repaired, revise only that route's prompt or mask.
- If the `36–70` result looks soft, increase texture protection or reduce only the luminance profile; do not weaken chroma cleanup first.
- If `71–100` fails the strict gate, return the automatically selected lower passing strength or `no-op`.
- If valid texture was removed, improve intentional-texture detection.
- If volume layers are fused or geometry is broken, leave that region unchanged and state that it is outside scope.

Never lengthen the universal prompt to solve every failure. Keep route prompts short and independently testable.
