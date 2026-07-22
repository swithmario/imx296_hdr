#!/usr/bin/env python3
"""Render separate short/long Bayer arrays as viewable 16-bit RGB TIFFs."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

from merge_hdr_sequence import BLACK_CODE, demosaic_bggr


def render_linear(raw_path: Path, height: int, words_per_row: int, width: int):
    mosaic = (
        np.fromfile(raw_path, dtype="<u2")
        .reshape(height, words_per_row)[:, :width]
        .astype(np.float32)
        / 64.0
    )
    rgb = demosaic_bggr(np.maximum(mosaic - BLACK_CODE, 0.0))
    # Conservative scene-neutral balance. The earlier proof-capture CCM/gains
    # were measured under different illumination and produced magenta clipping.
    rgb *= np.array([1.6, 1.0, 1.1], dtype=np.float32)
    peak = np.max(rgb, axis=-1, keepdims=True)
    highlight_weight = np.clip((peak - 800.0) / 200.0, 0.0, 1.0)
    return rgb * (1.0 - highlight_weight) + peak * highlight_weight


def display_rgb16(rgb, white: float):
    exposed = rgb * (4.0 / white)
    mapped = exposed / (1.0 + exposed)
    srgb = np.where(
        mapped <= 0.0031308,
        mapped * 12.92,
        1.055 * np.power(mapped, 1.0 / 2.4) - 0.055,
    )
    frame = np.clip(srgb * 65535.0 + 0.5, 0, 65535).astype("<u2")
    return np.ascontiguousarray(np.rot90(frame, 2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sources", type=Path)
    args = parser.parse_args()

    manifest = json.loads((args.sources / "arrays.json").read_text())
    stream = manifest["stream"]
    width = int(stream["width"])
    height = int(stream["height"])
    words_per_row = int(stream["stride"]) // 2

    render_manifest = {}
    for kind in ("short", "long"):
        frames = manifest[kind]["frames"]
        first_path = args.sources / frames[0]["filename"]
        first = render_linear(first_path, height, words_per_row, width)
        white = max(float(np.percentile(first[::4, ::4], 99.5)), 1e-6)

        output_dir = args.sources / f"{kind}_color_tiff"
        output_dir.mkdir(parents=True, exist_ok=True)
        pattern = output_dir / f"{kind}_%03d.tiff"
        command = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pixel_format", "rgb48le",
            "-video_size", f"{width}x{height}", "-framerate", "1",
            "-i", "-", "-frames:v", str(len(frames)),
            "-start_number", "0", "-compression_algo", "deflate", str(pattern),
        ]
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
        assert encoder.stdin is not None
        try:
            for item in frames:
                rgb = render_linear(
                    args.sources / item["filename"], height, words_per_row, width
                )
                encoder.stdin.write(display_rgb16(rgb, white).tobytes())
        finally:
            encoder.stdin.close()
        if encoder.wait() != 0:
            raise RuntimeError(f"TIFF rendering failed for {kind}")

        render_manifest[kind] = {
            "directory": output_dir.name,
            "frame_count": len(frames),
            "actual_exposure_us": manifest[kind]["actual_exposure_us"],
            "independent_tone_map_white": white,
        }

    render_manifest["processing"] = (
        "bilinear BGGR demosaic; black subtraction; conservative scene-neutral "
        "white balance; neutral highlight handling; independent exposure scaling; "
        "global tone map; sRGB; 180-degree rotation"
    )
    (args.sources / "color_tiff.json").write_text(
        json.dumps(render_manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(render_manifest, indent=2))


if __name__ == "__main__":
    main()
