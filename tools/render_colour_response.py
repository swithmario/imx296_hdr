#!/usr/bin/env python3
"""Render a linearly colour-corrected preview from a Bayer radiance stack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from export_still_bracket_tiffs import demosaic_bggr, write_rgb48_tiff


WHITE_BALANCE = np.array([2.428159, 1.0, 2.205721], dtype=np.float32)
CCM = np.array(
    [
        [1.998794, -0.692318, -0.306485],
        [-0.466577, 2.065926, -0.599351],
        [-0.089408, -0.597580, 1.686988],
    ],
    dtype=np.float32,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bracket", type=Path)
    args = parser.parse_args()

    stack_dir = args.bracket / "stacked_linear_radiance"
    stack_manifest = json.loads((stack_dir / "manifest.json").read_text())
    mosaic = np.fromfile(
        stack_dir / stack_manifest["stack"], dtype="<f4"
    ).reshape(1088, 1456)
    sensor_rgb = demosaic_bggr(mosaic)
    corrected = (sensor_rgb * WHITE_BALANCE) @ CCM.T

    # Preserve negative calibrated/matrix values in the affine preview mapping.
    lower, upper = float(corrected.min()), float(corrected.max())
    if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
        raise RuntimeError("invalid corrected colour range")
    view = np.rint((corrected - lower) / (upper - lower) * 65535.0).astype(np.uint16)
    view = np.ascontiguousarray(np.rot90(view, 2))
    output = stack_dir / "merged_radiance_rgb_colour_response_minmax16.tiff"
    write_rgb48_tiff(output, view)

    robust_lower, robust_upper = map(
        float, np.percentile(corrected, [0.1, 99.9])
    )
    robust = np.clip(
        (corrected - robust_lower) / (robust_upper - robust_lower), 0.0, 1.0
    )
    robust_view = np.rint(robust * 65535.0).astype(np.uint16)
    robust_view = np.ascontiguousarray(np.rot90(robust_view, 2))
    robust_output = stack_dir / "merged_radiance_rgb_colour_response_robust_linear16.tiff"
    write_rgb48_tiff(robust_output, robust_view)

    positive = corrected[corrected > 0]
    white = max(float(np.percentile(positive, 99.5)), 1e-6)
    exposed = np.maximum(corrected, 0.0) * (4.0 / white)
    reinhard = exposed / (1.0 + exposed)
    srgb = np.where(
        reinhard <= 0.0031308,
        reinhard * 12.92,
        1.055 * np.power(reinhard, 1.0 / 2.4) - 0.055,
    )
    tone_view = np.rint(np.clip(srgb, 0.0, 1.0) * 65535.0).astype(np.uint16)
    tone_view = np.ascontiguousarray(np.rot90(tone_view, 2))
    tone_output = stack_dir / "merged_radiance_rgb_colour_response_tonemapped16.tiff"
    write_rgb48_tiff(tone_output, tone_view)

    record = {
        "output": output.name,
        "robust_linear_preview": robust_output.name,
        "tonemapped_preview": tone_output.name,
        "source": stack_manifest["stack"],
        "processing": [
            "bilinear BGGR demosaic in linear radiance",
            "multiply linear RGB by white-balance gains",
            "multiply by 3x3 colour correction matrix",
            "one affine min-max mapping across all RGB channels",
            "rotate 180 degrees",
        ],
        "white_balance_rgb": WHITE_BALANCE.tolist(),
        "colour_correction_matrix": CCM.tolist(),
        "corrected_input_min": lower,
        "corrected_input_max": upper,
        "robust_shared_percentiles": [0.1, 99.9],
        "robust_shared_window": [robust_lower, robust_upper],
        "tonemap": {
            "exposure_multiplier_relative_to_positive_99_5_percentile": 4.0,
            "white_radiance": white,
            "operator": "Reinhard x/(1+x)",
            "display_transfer": "sRGB",
        },
        "negative_values": "retained through colour correction and included in min-max scale",
        "full_range_and_robust_preview_gamma": "none",
        "full_range_and_robust_preview_tone_map": "none",
        "per_channel_normalization": "none",
    }
    (stack_dir / "colour_response_preview.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
