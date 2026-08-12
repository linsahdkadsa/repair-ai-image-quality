# Evaluation and iteration

## Minimum public-beta set

Maintain at least 30 labeled images for the public denoise/clarity capability:

- 10 images that should be repaired;
- 10 coherent images that should be skipped;
- 10 high-risk images where only some regions are safe.

Cover:

- daylight and dark night scenes;
- neon, fire, strong saturation, and deep shadows;
- faces, hands, text, and multiple people;
- anime, painterly, ink, photographic, and cinematic styles;
- hair, jewelry, lace, architecture, foliage, tableware, and repeated motifs;
- low resolution, heavy compression, and intentional film grain.

Track structural cases only as out-of-scope routing checks. They must remain unchanged and never count as repair successes.

## Strong-profile calibration

Use clean-reference tests only for calibration, never as a substitute for real-image review. Add deterministic luminance noise, chroma noise, dark-field chroma blotches, and sparse impulses to a frozen clean source, then measure recovery against the clean source.

The 2026-07 strong-profile six-scene calibration covered line illustration, neon rain, saturated portrait, 2D animation, painterly sci-fi, and 3D firelight. It achieved:

- luminance-noise reduction: 45%–75%;
- chroma-noise reduction: 86%–90%;
- input-output edge correlation: 0.971–0.993;
- clean-reference PSNR gain: +3.41 to +5.94 dB;
- full-image RGB MAE: 7.2–9.9/255.

Treat these ranges as a regression baseline, not a universal quality claim.

The real-image line-art control test established the controller boundary:

- strength 60: sky residual −61%, edge correlation 0.967, strict gate passed;
- strength 80: sky residual −63%, edge correlation 0.888, strict gate failed;

This test demonstrates that visually stronger cleanup is not automatically a better accepted repair. Preserve both deterministic outcomes in regression tests.

The 2026-08 one-click fallback regression fixed the missing-middle-profile failure. Across six frozen clean-reference scenes, default strength `60` produced:

- previous average clean-reference improvement: `33.8%`;
- adaptive one-click average improvement: `37.2%`;
- relative gain over the previous accepted chain: `10.2%`;
- strict fidelity gate passes: `6/6`.

Keep this as a regression floor, not a universal quality claim. The 30-image public-beta gate remains separate.

The 2026-08 extended controlled regression covered 30 frozen sources and an independent mixed-noise generator, including 13 night scenes, saturated images, faces, ornate tableware, flat graphics, text-heavy labels, sparse glow/circuit lines, and cinematic frames. At default strength `60`:

- positive clean-reference improvement: `30/30`;
- strict fidelity gate passes: `30/30`;
- coherent clean sources correctly skipped: `28/30` (`93.3%`);
- average clean-reference improvement: `33.0%`;
- Gaussian-blur baseline: `18.8%`;
- 3×3 median baseline: `28.1%`;
- night subset average improvement: `38.1%` across 13 scenes;
- one-click beat Gaussian on `23/30` samples and median on `20/30` samples.

Use the `sparse-lines` route for the two cases that originally regressed despite passing global fidelity. This controlled set proves regression resistance, not superiority over dedicated neural denoisers or the public real-image gate.

The 2026-08 real/native public-beta set added 40 frozen images: 27 native-noise photographs, 7 high-risk AI images, and 6 compressed-video frames. A dedicated SCUNet baseline was tested but rejected for the shipped route because its full output visibly over-smoothed coherent texture; its available ONNX conversion also took `43.7 s` for a `128×128` CUDA tile on the target machine. The accepted deterministic ensemble uses the original guided route, colored non-local means, channel-separated non-local means, and no-op rollback behind one controller. At default strength `60` it produced:

- mean luminance-noise reduction: `28.8%`;
- mean chroma-noise reduction: `26.1%`;
- mean structured high-frequency retention: `97.4%`;
- mean RGB change: `2.94/255`;
- mean processing time: `2.24 s` per image on the frozen mixed-size set;
- accepted backend mix: `15` channel-separated NLM, `6` colored NLM, `8` changed guided outputs, and `11` no-op guided routes;
- effective-strength violations at the default ceiling: `0/40`.

A separate controller matrix covered 9 representative images at strengths `0/20/35/60/85/100` (`54` cases). It passed controller-ceiling, nested-quality, strength-zero identity, and protected-mask pixel-identity checks with zero failures. Treat these figures as a frozen-machine regression baseline and visual-review aid, not a universal “best denoiser” claim.

## Failure labels

Assign one primary label:

- `route-wrong`: wrong safe defect class or no-op decision;
- `over-repair`: valid detail removed or appearance changed;
- `under-repair`: selected safe defect remains;
- `semantic-drift`: identity, anatomy, text, object count, ownership, or geometry changed;
- `registration`: double edge, ghosting, or crop shift;
- `texture-confusion`: intentional grain, glow, or ornament treated as noise;
- `strong-softness`: noise is removed but coherent edges or texture look unnaturally soft;
- `volume-collapse`: detail remains fused or loses 3D separation;
- `unsafe-case`: cannot be repaired reliably with current evidence and controls.

## Decide what to change

| Failure | First component to change |
|---|---|
| route-wrong | routing signals and examples |
| over-repair | confidence floor, mask, and protection |
| under-repair | safe route prompt or one additional local pass |
| strong-softness | deterministic luminance profile and texture protection |
| semantic-drift | protected regions and rollback |
| registration | alignment and composite mask |
| texture-confusion | intentional-texture rules |
| volume-collapse | stop Prompt iteration; require trusted geometry or skip |
| unsafe-case | skip/refusal policy |

Only change one component per test round. Re-run the same frozen evaluation set before adding new samples.

## Geometry stop rule

Broken, fused, melted, duplicated, or incoherent geometry is outside the skill's capability. Do not generate a repair attempt, auxiliary geometry, or prompt variant. Leave the region unchanged and evaluate only whether routing correctly skipped it.

## Release gate

The public denoise/clarity capability may ship only when:

- protected invariants have zero visible semantic errors on the frozen set;
- at least 90% of coherent images are correctly skipped;
- at least 80% of repairable noise/clarity defects are visibly improved;
- every failed region rolls back without harming the accepted base;
- night/neon and ornate-image subsets pass separately.

Out-of-scope geometry checks cannot inflate public repair metrics.

Public wording:

> 一键清理 AI 图片噪点与脏糊，同时尽量保持原图细节、色彩和光影不变。无法安全处理的结构问题会自动跳过。
