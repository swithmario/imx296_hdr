#!/usr/bin/env python3
"""Render a linearly colour-corrected preview from a Bayer radiance stack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from export_still_bracket_tiffs import demosaic_bggr, percentile_minmax, write_rgb48_tiff


WHITE_BALANCE = np.array([2.428159, 1.0, 2.205721], dtype=np.float32)
CCM = np.array(
    [
        [1.998794, -0.692318, -0.306485],
        [-0.466577, 2.065926, -0.599351],
        [-0.089408, -0.597580, 1.686988],
    ],
    dtype=np.float32,
)

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def coordinate_safe_tonemap(rgb: np.ndarray, white: float) -> np.ndarray:
    """Tone-map luminance and preserve chroma direction inside the RGB cube.

    Hue is not represented as an angle, so the zero-chroma coordinate
    singularity never appears. Relative Cartesian chroma is regularized at
    zero luminance, then contracted only as much as required to intersect the
    valid constant-luminance section of the display RGB cube.
    """
    luminance = np.maximum(rgb @ LUMA, 0.0)
    relative_chroma = (rgb - luminance[..., None]) / np.maximum(
        luminance[..., None], white * 1e-8
    )
    exposed = luminance * (4.0 / white)
    display_luminance = exposed / (1.0 + exposed)
    delta = display_luminance[..., None] * relative_chroma

    # Find the largest step from the neutral axis along the same chroma vector
    # that keeps every channel inside [0, 1]. This preserves hue direction and
    # automatically tends to neutral at the highlight vertex.
    positive_limit = np.where(
        delta > 0.0,
        (1.0 - display_luminance[..., None]) / np.maximum(delta, 1e-20),
        np.inf,
    )
    negative_limit = np.where(
        delta < 0.0,
        display_luminance[..., None] / np.maximum(-delta, 1e-20),
        np.inf,
    )
    chroma_scale = np.minimum(
        1.0, np.minimum(positive_limit, negative_limit).min(axis=-1)
    )
    display_linear = display_luminance[..., None] + delta * chroma_scale[..., None]
    display_linear = np.clip(display_linear, 0.0, 1.0)
    return np.where(
        display_linear <= 0.0031308,
        display_linear * 12.92,
        1.055 * np.power(display_linear, 1.0 / 2.4) - 0.055,
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
    normalized, lower, upper = percentile_minmax(corrected, tail_percent=0.01)
    view = np.rint(normalized * 65535.0).astype(np.uint16)
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
    srgb = coordinate_safe_tonemap(corrected, white)
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
            "one shared 0.01st-99.99th percentile affine mapping across all RGB channels",
            "rotate 180 degrees",
        ],
        "white_balance_rgb": WHITE_BALANCE.tolist(),
        "colour_correction_matrix": CCM.tolist(),
        "corrected_input_min": lower,
        "corrected_input_max": upper,
        "minmax_discarded_tail_percent_each": 0.01,
        "robust_shared_percentiles": [0.1, 99.9],
        "robust_shared_window": [robust_lower, robust_upper],
        "tonemap": {
            "exposure_multiplier_relative_to_positive_99_5_percentile": 4.0,
            "white_radiance": white,
            "operator": "Reinhard x/(1+x) on luminance only",
            "chroma_coordinates": "regularized Cartesian offset from neutral axis",
            "gamut_mapping": (
                "radial intersection along unchanged chroma direction with the "
                "constant-luminance section of the linear RGB cube"
            ),
            "display_transfer": "sRGB",
        },
        "negative_values": (
            "retained through colour correction; only the lowest 0.01% are "
            "clipped in the min-max viewing derivative"
        ),
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
