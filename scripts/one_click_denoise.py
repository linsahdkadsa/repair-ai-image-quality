#!/usr/bin/env python3
"""One-click adaptive denoise with deterministic fallback and comparison output."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

try:
    import cv2
except ImportError:  # The original guided route remains a safe fallback.
    cv2 = None

from strong_denoise import analyze_noise, build_report, denoise


PROFILE_CAPACITY = {
    "conservative": 35,
    # The public default 60 reaches the full auto profile, so its reported
    # effective strength must remain 60 even though the request ceiling can
    # continue to 70 before the strong profile becomes eligible.
    "auto": 60,
    "strong": 100,
}


def correlation(first, second):
    first = first.ravel()
    second = second.ravel()
    if first.size < 2 or np.std(first) == 0 or np.std(second) == 0:
        return 1.0 if np.allclose(first, second) else 0.0
    return float(np.corrcoef(first, second)[0, 1])


def luminance_255(rgb_255):
    return (
        0.2126 * rgb_255[:, :, 0]
        + 0.7152 * rgb_255[:, :, 1]
        + 0.0722 * rgb_255[:, :, 2]
    )


def fidelity_metrics(source_u8, candidate_u8, protected=None):
    source = source_u8.astype(np.float32)
    candidate = candidate_u8.astype(np.float32)
    delta = np.abs(source - candidate)
    y_source = luminance_255(source)
    y_candidate = luminance_255(candidate)
    edge_source = np.hypot(*np.gradient(y_source))
    edge_candidate = np.hypot(*np.gradient(y_candidate))
    blur_source = np.asarray(
        Image.fromarray(y_source.astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)),
        dtype=np.float32,
    )
    blur_candidate = np.asarray(
        Image.fromarray(y_candidate.astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)),
        dtype=np.float32,
    )
    metrics = {
        "rgb_mae_255": float(delta.mean()),
        "rgb_p90_255": float(np.percentile(delta, 90)),
        "edge_correlation": correlation(edge_source, edge_candidate),
        "coarse_luminance_correlation": correlation(blur_source, blur_candidate),
    }
    if protected is not None:
        values = delta[protected]
        metrics["protected_pixel_count"] = int(protected.sum())
        metrics["protected_rgb_mae_255"] = (
            float(values.mean()) if values.size else 0.0
        )
        metrics["protected_rgb_p90_255"] = (
            float(np.percentile(values, 90)) if values.size else 0.0
        )
    metrics["guardrail_pass"] = (
        metrics["rgb_mae_255"] <= 12.0
        and metrics["edge_correlation"] >= 0.95
        and metrics["coarse_luminance_correlation"] >= 0.995
        and metrics.get("protected_rgb_mae_255", 0.0) <= 0.05
    )
    return metrics


def classify_detail_mode(source_image):
    preview = source_image.copy()
    preview.thumbnail((256, 256), Image.Resampling.LANCZOS)
    rgb = np.asarray(preview.convert("RGB"), dtype=np.float32) / 255.0
    y = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
    blur = np.asarray(
        Image.fromarray(np.clip(y * 255.0, 0, 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(0.8)
        ),
        dtype=np.float32,
    ) / 255.0
    edge = np.hypot(*np.gradient(blur))
    edge_density = float(np.mean(edge > 0.03))
    flat_fraction = float(np.mean(edge < 0.008))
    mode = "line-art" if edge_density >= 0.24 and flat_fraction <= 0.35 else "natural"
    return mode, {
        "edge_density": edge_density,
        "flat_fraction": flat_fraction,
    }


def candidate_plan(strength, detail_mode, content_risk):
    if strength <= 0:
        return []
    if content_risk == "sparse-lines":
        # Sparse glow, circuit, wire, star-field and filament graphics lose
        # valid energy before whole-image edge correlation notices. Cap them
        # at the conservative profile regardless of the public ceiling.
        return [("conservative", min(1.0, strength / 35.0))]
    if detail_mode == "line-art":
        if strength <= 70:
            amount = min(1.0, strength / 60.0)
            return [("conservative", amount)]
        amount = 0.65 + 0.35 * (strength - 71) / 29.0
        return [("auto", min(amount, 1.0)), ("conservative", 1.0)]
    if strength <= 35:
        return [("conservative", strength / 35.0)]
    if strength <= 70:
        # Reach the full auto profile at the public default (60). Values
        # above 60 remain a ceiling rather than silently switching methods.
        amount = 0.55 + 0.45 * (strength - 36) / 24.0
        return [("auto", min(amount, 1.0)), ("conservative", 1.0)]
    strong_amount = 0.65 + 0.35 * (strength - 71) / 29.0
    plan = [("strong", min(strong_amount, 1.0)), ("auto", 1.0)]
    if content_risk == "high":
        plan = [("auto", 1.0)]
    plan.append(("conservative", 1.0))
    return plan


def descending_amounts(maximum):
    levels = [maximum, 0.90, 0.80, 0.70, 0.60, 0.50]
    return sorted({round(level, 4) for level in levels if 0.20 <= level <= maximum}, reverse=True)


def load_mask(path, size):
    if not path:
        return None, None
    image = Image.open(path).convert("L")
    if image.size != size:
        image = image.resize(size, Image.Resampling.NEAREST)
    soft = np.asarray(image, dtype=np.float32) / 255.0
    return soft[:, :, None], soft > 0.5


def quantize(rgb):
    return np.clip(np.rint(rgb * 255.0), 0, 255).astype(np.uint8)


def select_guided_candidate(source, strength, detail_mode, content_risk, mask_soft, mask_bool):
    source_u8 = quantize(source)
    before = analyze_noise(source)
    low_residue = before["luma_sigma_255"] <= 1.25 and before["chroma_sigma_255"] <= 1.50
    attempts = []
    if low_residue:
        return source_u8, {
            "accepted": "no-op",
            "reason": "source residue below the conservative no-op threshold",
            "attempts": attempts,
            "source_noise": {
                "luma_sigma_255": before["luma_sigma_255"],
                "chroma_sigma_255": before["chroma_sigma_255"],
            },
        }

    profile_cache = {}
    for profile, maximum in candidate_plan(strength, detail_mode, content_risk):
        if profile not in profile_cache:
            profile_cache[profile] = denoise(source, profile, detail_mode)[0]
        raw = profile_cache[profile]
        for amount in descending_amounts(maximum):
            candidate = source + (raw - source) * amount
            if mask_soft is not None:
                candidate = candidate * (1.0 - mask_soft) + source * mask_soft
            candidate_u8 = quantize(candidate)
            candidate_float = candidate_u8.astype(np.float32) / 255.0
            fidelity = fidelity_metrics(source_u8, candidate_u8, mask_bool)
            report = build_report(
                source,
                candidate_float,
                {
                    "profile": profile,
                    "detail_mode": detail_mode,
                    "writeback_amount": amount,
                    "effective_strength": int(round(PROFILE_CAPACITY[profile] * amount)),
                },
            )
            visible_cleanup = (
                report["luma_noise_reduction_percent"] >= 12.0
                or report["chroma_noise_reduction_percent"] >= 25.0
            )
            attempt = {
                "profile": profile,
                "writeback_amount": amount,
                "effective_strength": int(round(PROFILE_CAPACITY[profile] * amount)),
                "fidelity": fidelity,
                "luma_noise_reduction_percent": report["luma_noise_reduction_percent"],
                "chroma_noise_reduction_percent": report["chroma_noise_reduction_percent"],
                "visible_cleanup": visible_cleanup,
            }
            attempts.append(attempt)
            if fidelity["guardrail_pass"] and visible_cleanup:
                return candidate_u8, {
                    "accepted": profile,
                    "reason": "highest requested candidate that passed cleanup and fidelity gates",
                    "writeback_amount": amount,
                    "effective_strength": attempt["effective_strength"],
                    "accepted_fidelity": fidelity,
                    "accepted_cleanup": report,
                    "attempts": attempts,
                    "source_noise": {
                        "luma_sigma_255": before["luma_sigma_255"],
                        "chroma_sigma_255": before["chroma_sigma_255"],
                    },
                }
    return source_u8, {
        "accepted": "no-op",
        "reason": "all candidates failed cleanup or fidelity gates",
        "attempts": attempts,
        "source_noise": {
            "luma_sigma_255": before["luma_sigma_255"],
            "chroma_sigma_255": before["chroma_sigma_255"],
        },
    }


def texture_metrics(source_u8, candidate_u8):
    """Track high-frequency retention around source structure, not noise alone."""
    source = source_u8.astype(np.float32) / 255.0
    candidate = candidate_u8.astype(np.float32) / 255.0
    source_y = source @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    candidate_y = candidate @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    source_blur = cv2.GaussianBlur(source_y, (0, 0), 1.0)
    candidate_blur = cv2.GaussianBlur(candidate_y, (0, 0), 1.0)
    source_high = source_y - source_blur
    candidate_high = candidate_y - candidate_blur
    gx = cv2.Sobel(source_blur, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(source_blur, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = np.hypot(gx, gy)
    structure = magnitude >= np.percentile(magnitude, 65)

    def energy(values, mask):
        selected = values[mask]
        return float(np.sqrt(np.mean(selected * selected))) if selected.size else 0.0

    source_energy = energy(source_high, structure)
    return {
        "structured_hf_retention": energy(candidate_high, structure)
        / max(source_energy, 1e-8),
    }


def evaluate_candidate(source, source_u8, candidate_u8, mask_bool, method, amount):
    candidate = candidate_u8.astype(np.float32) / 255.0
    return {
        "fidelity": fidelity_metrics(source_u8, candidate_u8, mask_bool),
        "cleanup": build_report(
            source,
            candidate,
            {
                "profile": method,
                "detail_mode": "deterministic",
                "writeback_amount": amount,
            },
        ),
        "texture": texture_metrics(source_u8, candidate_u8),
    }


def nlm_parameters(source, strength):
    noise = analyze_noise(source)
    h_luma = np.clip(1.75 + noise["luma_sigma_255"] * 0.72, 2.4, 7.0)
    h_color = np.clip(2.5 + noise["chroma_sigma_255"] * 0.95, 3.5, 11.0)
    return float(h_luma), float(h_color)


def run_nlm_routes(source_u8, source, strength):
    h_luma, h_color = nlm_parameters(source, strength)
    bgr = cv2.cvtColor(source_u8, cv2.COLOR_RGB2BGR)
    colored_bgr = cv2.fastNlMeansDenoisingColored(
        bgr,
        None,
        h_luma,
        h_color,
        7,
        21,
    )
    colored = cv2.cvtColor(colored_bgr, cv2.COLOR_BGR2RGB)

    ycrcb = cv2.cvtColor(source_u8, cv2.COLOR_RGB2YCrCb)
    y, cr, cb = cv2.split(ycrcb)
    channel_h_color = min(h_color, 7.0)
    y_out = cv2.fastNlMeansDenoising(y, None, h_luma, 7, 21)
    cr_out = cv2.fastNlMeansDenoising(cr, None, channel_h_color, 7, 21)
    cb_out = cv2.fastNlMeansDenoising(cb, None, channel_h_color, 7, 21)
    ycbcr = cv2.cvtColor(
        cv2.merge([y_out, cr_out, cb_out]),
        cv2.COLOR_YCrCb2RGB,
    )
    return {
        "colored-nlm": colored,
        "ycbcr-nlm": ycbcr,
    }, {
        "h_luma": h_luma,
        "h_color": h_color,
        "channel_h_color": channel_h_color,
    }


def nlm_gate(metrics, content_risk, source_luma, source_chroma):
    fidelity = metrics["fidelity"]
    cleanup = metrics["cleanup"]
    texture = metrics["texture"]
    mae_cap = 6.0 if content_risk == "high" else 4.0 if content_risk == "sparse-lines" else 12.0
    texture_floor = (
        0.975
        if content_risk == "high"
        else 0.99
        if content_risk == "sparse-lines"
        else max(
            0.86,
            0.96
            - max(source_luma - 2.0, 0.0) * 0.018
            - max(source_chroma - 2.0, 0.0) * 0.004,
        )
    )
    edge_floor = (
        0.96
        if content_risk == "high"
        else 0.985
        if content_risk == "sparse-lines"
        else max(0.82, 0.94 - max(source_luma - 2.0, 0.0) * 0.018)
    )
    reasons = []
    if fidelity["rgb_mae_255"] > mae_cap:
        reasons.append("mae")
    if fidelity["coarse_luminance_correlation"] < 0.995:
        reasons.append("coarse")
    if fidelity["edge_correlation"] < edge_floor:
        reasons.append("edge")
    if texture["structured_hf_retention"] < texture_floor:
        reasons.append("texture")
    if fidelity.get("protected_rgb_mae_255", 0.0) > 0.05:
        reasons.append("protected")
    if not (
        cleanup["luma_noise_reduction_percent"] >= 12.0
        or cleanup["chroma_noise_reduction_percent"] >= 20.0
    ):
        reasons.append("cleanup")
    return not reasons, reasons


def candidate_score(metrics):
    cleanup = metrics["cleanup"]
    fidelity = metrics["fidelity"]
    texture = metrics["texture"]
    luma = np.clip(cleanup["luma_noise_reduction_percent"], -20.0, 90.0)
    chroma = np.clip(cleanup["chroma_noise_reduction_percent"], -20.0, 90.0)
    texture_penalty = max(0.0, 0.98 - texture["structured_hf_retention"]) * 180.0
    return float(
        0.68 * luma
        + 0.32 * chroma
        - texture_penalty
        - fidelity["rgb_mae_255"] * 0.7
    )


def nlm_amounts(strength):
    maximum = min(1.0, max(0.0, strength / 60.0))
    # Fixed steps make every higher request a superset of lower requests.
    # Do not inject the arbitrary maximum as a one-off competing candidate.
    levels = [round(value / 20.0, 2) for value in range(4, 21)]
    return sorted(
        {value for value in levels if value <= maximum + 1e-8},
        reverse=True,
    )


def select_candidate(source, strength, detail_mode, content_risk, mask_soft, mask_bool):
    """Choose between the original guided route and gated NLM candidates."""
    source_u8 = quantize(source)
    guided_u8, guided = select_guided_candidate(
        source,
        strength,
        detail_mode,
        content_risk,
        mask_soft,
        mask_bool,
    )
    guided_candidates = [(guided_u8, guided)]
    # Higher public strengths must retain every lower guided candidate that
    # was previously available. Otherwise a new strong profile can displace
    # a cleaner conservative result even when its own score is lower.
    for lower_ceiling in (60, 35, 20):
        if 0 < lower_ceiling < strength:
            lower_u8, lower_selection = select_guided_candidate(
                source,
                lower_ceiling,
                detail_mode,
                content_risk,
                mask_soft,
                mask_bool,
            )
            guided_candidates.append((lower_u8, lower_selection))
    guided["backend"] = "guided"
    guided["opencv_available"] = cv2 is not None
    if cv2 is None or strength <= 0:
        if guided["accepted"] == "no-op":
            guided["backend"] = "no-op"
        else:
            guided["backend"] = "guided-fallback" if cv2 is None else "guided"
        return guided_u8, guided

    source_luma = float(guided["source_noise"]["luma_sigma_255"])
    source_chroma = float(guided["source_noise"]["chroma_sigma_255"])
    source_mean = float(source_u8.mean() / 255.0)
    nlm_allowed = (
        (
            content_risk == "standard"
            and (source_luma >= 1.25 or source_chroma >= 1.50)
        )
        or (
            content_risk == "high"
            and (source_luma >= 1.50 or source_chroma >= 1.80)
        )
        or (
            content_risk == "high"
            and source_mean < 0.35
            and detail_mode == "line-art"
            and source_luma >= 0.85
        )
    ) and content_risk != "sparse-lines"
    candidates = []
    for guided_candidate_u8, guided_selection in guided_candidates:
        if guided_selection["accepted"] == "no-op":
            continue
        guided_metrics = evaluate_candidate(
            source,
            source_u8,
            guided_candidate_u8,
            mask_bool,
            "guided",
            float(guided_selection.get("writeback_amount", 1.0)),
        )
        candidates.append(
            {
                "method": "guided",
                "amount": float(guided_selection.get("writeback_amount", 1.0)),
                "image": guided_candidate_u8,
                "metrics": guided_metrics,
                "trusted": bool(guided_metrics["fidelity"]["guardrail_pass"]),
                "effective_strength": int(guided_selection.get("effective_strength", 0)),
                "selection": guided_selection,
            }
        )

    nlm_runtime = None
    if nlm_allowed:
        routes, nlm_runtime = run_nlm_routes(source_u8, source, strength)
        selected_routes = ["ycbcr-nlm"]
        if content_risk == "standard":
            selected_routes.insert(0, "colored-nlm")
        for method in selected_routes:
            raw_u8 = routes[method]
            for amount in nlm_amounts(strength):
                candidate_u8 = np.clip(
                    np.rint(
                        source_u8.astype(np.float32)
                        + (raw_u8.astype(np.float32) - source_u8.astype(np.float32))
                        * amount
                    ),
                    0,
                    255,
                ).astype(np.uint8)
                if mask_soft is not None:
                    candidate = candidate_u8.astype(np.float32) / 255.0
                    candidate = candidate * (1.0 - mask_soft) + source * mask_soft
                    candidate_u8 = quantize(candidate)
                metrics = evaluate_candidate(
                    source,
                    source_u8,
                    candidate_u8,
                    mask_bool,
                    method,
                    amount,
                )
                candidates.append(
                    {
                        "method": method,
                        "amount": amount,
                        "image": candidate_u8,
                        "metrics": metrics,
                        "trusted": False,
                        "effective_strength": min(
                            strength,
                            int(round((60 if strength <= 60 else strength) * amount)),
                        ),
                    }
                )

    attempts = []
    passing = []
    for candidate in candidates:
        if candidate["trusted"]:
            passed, reasons = True, []
        else:
            passed, reasons = nlm_gate(
                candidate["metrics"],
                content_risk,
                source_luma,
                source_chroma,
            )
        score = candidate_score(candidate["metrics"])
        attempts.append(
            {
                "method": candidate["method"],
                "writeback_amount": candidate["amount"],
                "effective_strength": candidate["effective_strength"],
                "passed": passed,
                "reasons": reasons,
                "score": score,
                "fidelity": candidate["metrics"]["fidelity"],
                "cleanup": {
                    "luma_noise_reduction_percent": candidate["metrics"]["cleanup"]["luma_noise_reduction_percent"],
                    "chroma_noise_reduction_percent": candidate["metrics"]["cleanup"]["chroma_noise_reduction_percent"],
                },
                "texture": candidate["metrics"]["texture"],
            }
        )
        if passed:
            passing.append((score, candidate))

    if not passing:
        if guided["accepted"] == "no-op":
            guided["backend"] = "no-op"
        guided["hybrid_attempts"] = attempts
        guided["nlm_parameters"] = nlm_runtime
        return guided_u8, guided

    _, winner = max(passing, key=lambda item: item[0])
    if winner["method"] == "guided":
        selected = winner["selection"]
        selected["backend"] = "guided"
        selected["opencv_available"] = True
        selected["hybrid_attempts"] = attempts
        selected["nlm_parameters"] = nlm_runtime
        return winner["image"], selected
    return winner["image"], {
        "accepted": winner["method"],
        "backend": winner["method"],
        "reason": "highest-scoring deterministic candidate that passed cleanup and preservation gates",
        "writeback_amount": winner["amount"],
        "effective_strength": winner["effective_strength"],
        "accepted_fidelity": winner["metrics"]["fidelity"],
        "accepted_cleanup": winner["metrics"]["cleanup"],
        "accepted_texture": winner["metrics"]["texture"],
        "attempts": guided.get("attempts", []),
        "hybrid_attempts": attempts,
        "source_noise": guided["source_noise"],
        "nlm_parameters": nlm_runtime,
        "opencv_available": True,
    }


def font(size, bold=False):
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def fit(image, size):
    copy = image.copy()
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", size, (15, 20, 28))
    canvas.paste(copy, ((size[0] - copy.width) // 2, (size[1] - copy.height) // 2))
    return canvas


def pick_crop(source_u8, output_u8):
    height, width = source_u8.shape[:2]
    crop = max(96, int(min(width, height) * 0.30))
    crop = min(crop, width, height)
    delta = np.mean(np.abs(source_u8.astype(np.float32) - output_u8.astype(np.float32)), axis=2)
    best = (0.0, 0, 0)
    for y in np.linspace(0, height - crop, 7).astype(int):
        for x in np.linspace(0, width - crop, 9).astype(int):
            score = float(delta[y : y + crop, x : x + crop].mean())
            if score > best[0]:
                best = (score, x, y)
    return (best[1], best[2], best[1] + crop, best[2] + crop)


def make_comparison(source_image, output_image, path, result):
    width = 1600
    margin = 42
    gap = 26
    panel_w = (width - margin * 2 - gap) // 2
    full_h = 520
    zoom_h = 430
    height = 1150
    board = Image.new("RGB", (width, height), (8, 13, 20))
    draw = ImageDraw.Draw(board)
    draw.text((margin, 28), "一键去噪 · 自动保真结果", font=font(42, True), fill=(240, 244, 250))
    accepted = result.get("accepted", "no-op")
    effective = result.get("effective_strength", 0)
    draw.text(
        (margin, 82),
        f"接受档位：{accepted}  |  实际强度：{effective}",
        font=font(22),
        fill=(118, 220, 174),
    )
    top = 128
    original_full = fit(source_image, (panel_w, full_h))
    output_full = fit(output_image, (panel_w, full_h))
    board.paste(original_full, (margin, top))
    board.paste(output_full, (margin + panel_w + gap, top))
    draw.text((margin + 14, top + 14), "原图", font=font(26, True), fill=(255, 198, 86))
    draw.text(
        (margin + panel_w + gap + 14, top + 14),
        "一键去噪",
        font=font(26, True),
        fill=(84, 220, 198),
    )
    source_u8 = np.asarray(source_image.convert("RGB"), dtype=np.uint8)
    output_u8 = np.asarray(output_image.convert("RGB"), dtype=np.uint8)
    box = pick_crop(source_u8, output_u8)
    zoom_top = top + full_h + 66
    original_zoom = fit(source_image.crop(box), (panel_w, zoom_h))
    output_zoom = fit(output_image.crop(box), (panel_w, zoom_h))
    board.paste(original_zoom, (margin, zoom_top))
    board.paste(output_zoom, (margin + panel_w + gap, zoom_top))
    draw.text((margin + 14, zoom_top + 14), "原图 100% 局部", font=font(24, True), fill=(255, 198, 86))
    draw.text(
        (margin + panel_w + gap + 14, zoom_top + 14),
        "去噪后 100% 局部",
        font=font(24, True),
        fill=(84, 220, 198),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    board.save(path)


def main():
    parser = argparse.ArgumentParser(description="One-click adaptive AI image denoise.")
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--strength", type=int, default=60)
    parser.add_argument(
        "--detail-mode",
        choices=["auto", "natural", "line-art"],
        default="auto",
    )
    parser.add_argument(
        "--content-risk",
        choices=["standard", "high", "sparse-lines"],
        default="standard",
        help="Internal routing hint; use high for faces/hands/text and sparse-lines for glow, wires, circuits, stars, or filaments.",
    )
    parser.add_argument("--protected-mask")
    parser.add_argument("--report")
    parser.add_argument("--comparison")
    args = parser.parse_args()

    strength = int(np.clip(args.strength, 0, 100))
    source_image = Image.open(args.source).convert("RGB")
    source = np.asarray(source_image, dtype=np.float32) / 255.0
    mode = args.detail_mode
    classifier = None
    if mode == "auto":
        mode, classifier = classify_detail_mode(source_image)
    mask_soft, mask_bool = load_mask(args.protected_mask, source_image.size)
    output_u8, selection = select_candidate(
        source,
        strength,
        mode,
        args.content_risk,
        mask_soft,
        mask_bool,
    )
    output_image = Image.fromarray(output_u8, "RGB")
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_args = {"quality": 96, "subsampling": 0} if output_path.suffix.lower() in {".jpg", ".jpeg"} else {}
    output_image.save(output_path, **save_args)

    result = {
        "source": str(Path(args.source).resolve()),
        "output": str(output_path.resolve()),
        "requested_strength": strength,
        "detail_mode": mode,
        "detail_classifier": classifier,
        "content_risk": args.content_risk,
        "protected_fraction": float(mask_bool.mean()) if mask_bool is not None else 0.0,
        **selection,
    }
    if args.comparison:
        comparison_path = Path(args.comparison)
        make_comparison(source_image, output_image, comparison_path, result)
        result["comparison"] = str(comparison_path.resolve())
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
