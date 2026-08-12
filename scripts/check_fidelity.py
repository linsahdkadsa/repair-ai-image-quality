#!/usr/bin/env python3
import argparse
import json

import numpy as np
from PIL import Image, ImageFilter


def load_rgb(path, size=None):
    image = Image.open(path).convert("RGB")
    if size and image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    return image, np.asarray(image).astype(np.float32)


def load_mask(path, size):
    if not path:
        return None
    mask = Image.open(path).convert("L")
    if mask.size != size:
        mask = mask.resize(size, Image.Resampling.NEAREST)
    return np.asarray(mask) > 127


def luminance(array):
    return 0.2126 * array[:, :, 0] + 0.7152 * array[:, :, 1] + 0.0722 * array[:, :, 2]


def correlation(a, b):
    a = a.ravel()
    b = b.ravel()
    if a.size < 2 or np.std(a) == 0 or np.std(b) == 0:
        return 1.0 if np.allclose(a, b) else 0.0
    return float(np.corrcoef(a, b)[0, 1])


def main():
    parser = argparse.ArgumentParser(
        description="Measure appearance fidelity between a source and repaired image."
    )
    parser.add_argument("source")
    parser.add_argument("candidate")
    parser.add_argument(
        "--protected-mask",
        help="Optional white-on-black mask for regions expected to remain nearly unchanged.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--preset",
        choices=["default", "strong-denoise"],
        default="default",
        help="Use stricter edge/coarse-light gates for strong denoise outputs.",
    )
    args = parser.parse_args()

    source_image, source = load_rgb(args.source)
    candidate_original = Image.open(args.candidate)
    same_size = candidate_original.size == source_image.size
    _, candidate = load_rgb(args.candidate, source_image.size)
    mask = load_mask(args.protected_mask, source_image.size)

    delta = np.abs(source - candidate)
    y_source = luminance(source)
    y_candidate = luminance(candidate)
    edge_source = np.hypot(*np.gradient(y_source))
    edge_candidate = np.hypot(*np.gradient(y_candidate))
    blur_source = np.asarray(
        Image.fromarray(y_source.astype("uint8")).filter(ImageFilter.GaussianBlur(3))
    ).astype(np.float32)
    blur_candidate = np.asarray(
        Image.fromarray(y_candidate.astype("uint8")).filter(ImageFilter.GaussianBlur(3))
    ).astype(np.float32)

    result = {
        "source_size": source_image.size,
        "candidate_size": candidate_original.size,
        "same_size": same_size,
        "rgb_mae_255": float(delta.mean()),
        "rgb_p90_255": float(np.percentile(delta, 90)),
        "edge_correlation": correlation(edge_source, edge_candidate),
        "coarse_luminance_correlation": correlation(blur_source, blur_candidate),
    }

    if mask is not None:
        protected_delta = delta[mask]
        result["protected_pixel_count"] = int(mask.sum())
        result["protected_rgb_mae_255"] = (
            float(protected_delta.mean()) if protected_delta.size else 0.0
        )
        result["protected_rgb_p90_255"] = (
            float(np.percentile(protected_delta, 90)) if protected_delta.size else 0.0
        )

    edge_floor = 0.95 if args.preset == "strong-denoise" else 0.70
    coarse_floor = 0.995 if args.preset == "strong-denoise" else 0.985
    result["preset"] = args.preset
    result["thresholds"] = {
        "rgb_mae_255_max": 12.0,
        "edge_correlation_min": edge_floor,
        "coarse_luminance_correlation_min": coarse_floor,
        "protected_rgb_mae_255_max": 3.0,
    }
    result["guardrail_pass"] = (
        same_size
        and result["rgb_mae_255"] <= 12
        and result["edge_correlation"] >= edge_floor
        and result["coarse_luminance_correlation"] >= coarse_floor
        and result.get("protected_rgb_mae_255", 0.0) <= 3.0
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
