#!/usr/bin/env python3
"""Edge-aware luminance/chroma denoising with deterministic fidelity metrics."""

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


PROFILES = {
    "conservative": {
        "luma_radius": 2,
        "luma_eps": 0.00035,
        "luma_mix": 0.52,
        "chroma_radius": 4,
        "chroma_eps": 0.0035,
        "chroma_mix": 0.68,
        "impulse_mix": 0.40,
        "edge_keep": 0.88,
        "texture_keep": 0.42,
    },
    "auto": {
        "luma_radius": 3,
        "luma_eps": 0.00070,
        "luma_mix": 0.74,
        "chroma_radius": 7,
        "chroma_eps": 0.0065,
        "chroma_mix": 0.86,
        "impulse_mix": 0.68,
        "edge_keep": 0.82,
        "texture_keep": 0.50,
    },
    "strong": {
        "luma_radius": 5,
        "luma_eps": 0.00120,
        "luma_mix": 0.94,
        "chroma_radius": 11,
        "chroma_eps": 0.0120,
        "chroma_mix": 0.97,
        "impulse_mix": 0.92,
        "edge_keep": 0.76,
        "texture_keep": 0.58,
    },
}


def box_mean(array, radius):
    """Fast reflected box mean with bounded float32 working memory."""
    if radius <= 0:
        return array.copy()
    width = radius * 2 + 1
    horizontal_pad = np.pad(array, ((0, 0), (radius, radius)), mode="reflect")
    horizontal_sum = np.cumsum(horizontal_pad, axis=1, dtype=np.float32)
    horizontal_sum = np.pad(horizontal_sum, ((0, 0), (1, 0)), mode="constant")
    horizontal = (horizontal_sum[:, width:] - horizontal_sum[:, :-width]) / width
    del horizontal_pad, horizontal_sum

    vertical_pad = np.pad(horizontal, ((radius, radius), (0, 0)), mode="reflect")
    vertical_sum = np.cumsum(vertical_pad, axis=0, dtype=np.float32)
    vertical_sum = np.pad(vertical_sum, ((1, 0), (0, 0)), mode="constant")
    result = (vertical_sum[width:] - vertical_sum[:-width]) / width
    return result.astype(np.float32, copy=False)


def guided_filter(guide, source, radius, epsilon):
    mean_g = box_mean(guide, radius)
    mean_s = box_mean(source, radius)
    corr_g = box_mean(guide * guide, radius)
    corr_gs = box_mean(guide * source, radius)
    variance_g = np.maximum(corr_g - mean_g * mean_g, 0.0)
    covariance_gs = corr_gs - mean_g * mean_s
    a = covariance_gs / (variance_g + epsilon)
    b = mean_s - a * mean_g
    return box_mean(a, radius) * guide + box_mean(b, radius)


def rgb_to_ycbcr(rgb):
    red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    y = 0.299 * red + 0.587 * green + 0.114 * blue
    cb = (blue - y) * 0.564 + 0.5
    cr = (red - y) * 0.713 + 0.5
    return y.astype(np.float32), cb.astype(np.float32), cr.astype(np.float32)


def ycbcr_to_rgb(y, cb, cr):
    red = y + 1.403 * (cr - 0.5)
    blue = y + 1.773 * (cb - 0.5)
    green = (y - 0.299 * red - 0.114 * blue) / 0.587
    return np.clip(np.stack([red, green, blue], axis=2), 0.0, 1.0)


def gaussian(array, radius):
    image = Image.fromarray(np.clip(array * 255.0, 0, 255).astype(np.uint8), "L")
    return (
        np.asarray(image.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32)
        / 255.0
    )


def median3(array):
    image = Image.fromarray(np.clip(array * 255.0, 0, 255).astype(np.uint8), "L")
    return (
        np.asarray(image.filter(ImageFilter.MedianFilter(3)), dtype=np.float32)
        / 255.0
    )


def gradient(array):
    dy, dx = np.gradient(array)
    return np.hypot(dx, dy)


def correlation(first, second, mask=None):
    if mask is not None:
        first, second = first[mask], second[mask]
    first, second = first.ravel(), second.ravel()
    if first.size < 2 or np.std(first) == 0 or np.std(second) == 0:
        return 1.0 if np.allclose(first, second) else 0.0
    return float(np.corrcoef(first, second)[0, 1])


def robust_sigma(residual, mask):
    values = np.abs(residual[mask])
    if values.size < 32:
        values = np.abs(residual).ravel()
    return float(np.median(values) / 0.6745)


def analyze_noise(rgb, flat_mask=None):
    y, cb, cr = rgb_to_ycbcr(rgb)
    base = gaussian(y, 1.2)
    edges = gradient(base)
    if flat_mask is None:
        flat_limit = max(float(np.percentile(edges, 45)), 0.006)
        flat = edges <= flat_limit
    else:
        flat = flat_mask
    luma_residual = y - gaussian(y, 0.75)
    cb_residual = cb - gaussian(cb, 1.2)
    cr_residual = cr - gaussian(cr, 1.2)
    chroma_sigma = math.sqrt(
        robust_sigma(cb_residual, flat) ** 2 + robust_sigma(cr_residual, flat) ** 2
    )
    return {
        "luma_sigma_255": robust_sigma(luma_residual, flat) * 255.0,
        "chroma_sigma_255": chroma_sigma * 255.0,
        "flat_fraction": float(flat.mean()),
        "edge_map": edges,
        "flat_mask": flat,
    }


def line_art_finalize(rgb, y, cb, cr, guide, y_seed, ultra=False):
    """Aggressively clean color fields, then restore coherent source linework."""
    local = gaussian(y, 2.5)
    dark_response = np.maximum(local - y, 0.0)
    edge_guide = gaussian(y, 0.7)
    grad_y, grad_x = np.gradient(edge_guide)
    magnitude = np.hypot(grad_x, grad_y)
    squared = magnitude * magnitude + 1e-8
    cos2 = (grad_x * grad_x - grad_y * grad_y) / squared
    sin2 = (2.0 * grad_x * grad_y) / squared
    mean_magnitude = box_mean(magnitude, 2)
    coherence = np.hypot(
        box_mean(magnitude * cos2, 2),
        box_mean(magnitude * sin2, 2),
    ) / (mean_magnitude + 1e-8)
    magnitude_floor = 0.060 if ultra else 0.045
    coherence_floor = 0.58 if ultra else 0.50
    dark_floor = 0.16 if ultra else 0.12
    dark_density_floor = 0.28 if ultra else 0.20
    dark_seed = dark_response >= dark_floor
    dark_connected = dark_seed & (
        box_mean(dark_seed.astype(np.float32), 1) >= dark_density_floor
    )
    coherent = (
        (magnitude >= magnitude_floor) & (coherence >= coherence_floor)
    ) | dark_connected

    mask_image = Image.fromarray((coherent * 255).astype(np.uint8), "L")
    mask_image = mask_image.filter(ImageFilter.MaxFilter(3))
    mask_image = mask_image.filter(ImageFilter.GaussianBlur(0.55))
    line_alpha = np.asarray(mask_image, dtype=np.float32) / 255.0
    coarse = gaussian(y, 1.5)
    coarse_mean = box_mean(coarse, 5)
    coarse_variance = np.maximum(
        box_mean(coarse * coarse, 5) - coarse_mean * coarse_mean,
        0.0,
    )
    structure_support = np.clip(
        (coarse_variance - 0.00012) / 0.00058,
        0.0,
        1.0,
    )
    line_alpha *= structure_support
    line_alpha = np.clip(line_alpha * 1.08, 0.0, 1.0)

    smooth_y = guided_filter(guide, y_seed, 9 if ultra else 7, 0.015 if ultra else 0.010)
    smooth_cb = guided_filter(guide, cb, 14 if ultra else 12, 0.018 if ultra else 0.014)
    smooth_cr = guided_filter(guide, cr, 14 if ultra else 12, 0.018 if ultra else 0.014)
    smooth_rgb = ycbcr_to_rgb(smooth_y, smooth_cb, smooth_cr)
    alpha = line_alpha[:, :, None]
    output = smooth_rgb * (1.0 - alpha) + rgb * alpha
    return output, {
        "line_art_mask_fraction": float(np.mean(line_alpha >= 0.5)),
        "line_art_mean_alpha": float(line_alpha.mean()),
    }


def denoise(rgb, profile_name, detail_mode="natural"):
    profile = PROFILES[profile_name]
    y, cb, cr = rgb_to_ycbcr(rgb)

    # Estimate true edge locations from a lightly smoothed luminance guide.
    guide = gaussian(y, 0.85)
    edge = gradient(guide)
    edge_weight = np.clip((edge - 0.010) / 0.075, 0.0, 1.0)

    # Remove isolated luminance impulses before the continuous noise pass.
    median = median3(y)
    impulse = np.abs(y - median)
    impulse_threshold = max(0.010, float(np.median(impulse)) * 3.2)
    impulse_weight = np.clip(
        (impulse - impulse_threshold) / max(impulse_threshold * 2.0, 1e-6),
        0.0,
        1.0,
    )
    impulse_weight *= 1.0 - edge_weight * 0.92
    y_seed = y + (median - y) * impulse_weight * profile["impulse_mix"]

    # Self-guidance preserves fine ink, hair, fabric and micro-geometry much
    # better than a blurred guide while still averaging stochastic residue.
    y_filtered = guided_filter(
        y_seed,
        y_seed,
        profile["luma_radius"],
        profile["luma_eps"],
    )
    residual = y_seed - median
    quiet = edge <= max(float(np.percentile(edge, 45)), 0.006)
    estimated_sigma = max(robust_sigma(residual, quiet), 1.0 / 255.0)
    local_mean = box_mean(y_seed, 2)
    local_variance = np.maximum(box_mean(y_seed * y_seed, 2) - local_mean**2, 0.0)
    signal_variance = np.maximum(local_variance - estimated_sigma**2, 0.0)
    texture_weight = np.clip(
        signal_variance / max(estimated_sigma**2 * 8.0, 1e-7),
        0.0,
        1.0,
    )
    luma_mix = profile["luma_mix"] * (
        1.0 - edge_weight * profile["edge_keep"]
    )
    luma_mix *= 1.0 - texture_weight * profile["texture_keep"]
    y_out = y_seed + (y_filtered - y_seed) * luma_mix

    # Use luminance as the geometry guide so chroma can be cleaned much more
    # aggressively without bleeding across object or lighting boundaries.
    cb_filtered = guided_filter(
        guide,
        cb,
        profile["chroma_radius"],
        profile["chroma_eps"],
    )
    cr_filtered = guided_filter(
        guide,
        cr,
        profile["chroma_radius"],
        profile["chroma_eps"],
    )
    chroma_mix = profile["chroma_mix"] * (1.0 - edge_weight * 0.58)
    cb_out = cb + (cb_filtered - cb) * chroma_mix
    cr_out = cr + (cr_filtered - cr) * chroma_mix

    output = ycbcr_to_rgb(y_out, cb_out, cr_out)
    extra_info = {}
    if detail_mode in {"line-art", "line-art-ultra"}:
        natural_output = output
        line_art_output, extra_info = line_art_finalize(
            rgb,
            y,
            cb,
            cr,
            guide,
            y_seed,
            ultra=detail_mode == "line-art-ultra",
        )
        # The line-art finalizer is deliberately stronger than the natural
        # route, but it must still obey the public controller. Previously it
        # replaced the profile result wholesale, so conservative and strong
        # produced nearly identical line-art outputs.
        line_art_strength_mix = {
            "conservative": 0.25,
            "auto": 0.60,
            "strong": 1.00,
        }[profile_name]
        output = natural_output + (
            line_art_output - natural_output
        ) * line_art_strength_mix
        extra_info["line_art_strength_mix"] = line_art_strength_mix
    return output, {
        "profile": profile_name,
        "detail_mode": detail_mode,
        "impulse_threshold_255": impulse_threshold * 255.0,
        "mean_luma_mix": float(luma_mix.mean()),
        "mean_chroma_mix": float(chroma_mix.mean()),
        "estimated_luma_noise_255": estimated_sigma * 255.0,
        **extra_info,
    }


def psnr(reference, candidate):
    mse = float(np.mean((reference - candidate) ** 2))
    return 99.0 if mse <= 1e-12 else 10.0 * math.log10(1.0 / mse)


def build_report(source, output, profile_info, reference=None):
    before = analyze_noise(source)
    after = analyze_noise(output, before["flat_mask"])
    y_before, _, _ = rgb_to_ycbcr(source)
    y_after, _, _ = rgb_to_ycbcr(output)
    edge_before = before["edge_map"]
    edge_after = after["edge_map"]
    edge_mask = edge_before >= np.percentile(edge_before, 75)
    report = {
        **profile_info,
        "rgb_mae_255": float(np.mean(np.abs(source - output)) * 255.0),
        "luma_noise_before_255": before["luma_sigma_255"],
        "luma_noise_after_255": after["luma_sigma_255"],
        "luma_noise_reduction_percent": (
            100.0
            * (before["luma_sigma_255"] - after["luma_sigma_255"])
            / max(before["luma_sigma_255"], 1e-6)
        ),
        "chroma_noise_before_255": before["chroma_sigma_255"],
        "chroma_noise_after_255": after["chroma_sigma_255"],
        "chroma_noise_reduction_percent": (
            100.0
            * (before["chroma_sigma_255"] - after["chroma_sigma_255"])
            / max(before["chroma_sigma_255"], 1e-6)
        ),
        "edge_correlation": correlation(edge_before, edge_after),
        "strong_edge_correlation": correlation(edge_before, edge_after, edge_mask),
        "coarse_luminance_correlation": correlation(
            gaussian(y_before, 3.0),
            gaussian(y_after, 3.0),
        ),
    }
    if reference is not None:
        report["reference_psnr_before_db"] = psnr(reference, source)
        report["reference_psnr_after_db"] = psnr(reference, output)
        report["reference_psnr_gain_db"] = (
            report["reference_psnr_after_db"] - report["reference_psnr_before_db"]
        )
        ref_y, _, _ = rgb_to_ycbcr(reference)
        report["reference_edge_correlation_before"] = correlation(
            gradient(gaussian(ref_y, 0.85)),
            edge_before,
        )
        report["reference_edge_correlation_after"] = correlation(
            gradient(gaussian(ref_y, 0.85)),
            edge_after,
        )
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Strong edge-aware denoise for AI-generated images."
    )
    parser.add_argument("source", help="Input image")
    parser.add_argument("output", help="Output PNG or JPEG")
    parser.add_argument(
        "--strength",
        choices=sorted(PROFILES),
        default="auto",
        help="Denoise profile (default: auto)",
    )
    parser.add_argument(
        "--detail-mode",
        choices=["natural", "line-art", "line-art-ultra"],
        default="natural",
        help="Use line-art for inked illustrations with broad color fields",
    )
    parser.add_argument(
        "--reference",
        help="Optional clean ground truth used only for evaluation",
    )
    parser.add_argument(
        "--protected-mask",
        help="Optional white-on-black mask whose white pixels must stay unchanged",
    )
    parser.add_argument(
        "--report",
        help="Optional JSON report path",
    )
    args = parser.parse_args()

    source_image = Image.open(args.source).convert("RGB")
    source = np.asarray(source_image, dtype=np.float32) / 255.0
    output, profile_info = denoise(source, args.strength, args.detail_mode)
    protected_fraction = 0.0
    if args.protected_mask:
        mask_image = Image.open(args.protected_mask).convert("L")
        if mask_image.size != source_image.size:
            mask_image = mask_image.resize(
                source_image.size,
                Image.Resampling.NEAREST,
            )
        mask = np.asarray(mask_image, dtype=np.float32) / 255.0
        mask = np.clip(mask, 0.0, 1.0)[:, :, None]
        protected_fraction = float(np.mean(mask[:, :, 0] > 0.5))
        output = output * (1.0 - mask) + source * mask

    output_image = Image.fromarray(
        np.clip(np.rint(output * 255.0), 0, 255).astype(np.uint8),
        "RGB",
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_args = {"quality": 96, "subsampling": 0} if output_path.suffix.lower() in {
        ".jpg",
        ".jpeg",
    } else {}
    output_image.save(output_path, **save_args)

    reference = None
    if args.reference:
        reference_image = Image.open(args.reference).convert("RGB")
        if reference_image.size != source_image.size:
            reference_image = reference_image.resize(
                source_image.size,
                Image.Resampling.LANCZOS,
            )
        reference = np.asarray(reference_image, dtype=np.float32) / 255.0

    report = build_report(source, output, profile_info, reference)
    report.update(
        {
            "source": str(Path(args.source).resolve()),
            "output": str(output_path.resolve()),
            "size": list(source_image.size),
            "protected_fraction": protected_fraction,
        }
    )
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
