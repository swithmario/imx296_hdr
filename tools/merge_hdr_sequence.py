#!/usr/bin/env python3
"""Merge verified alternating IMX296 Bayer frames into a 30 fps HDR preview."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path

import numpy as np


BLACK_CODE = 60.0
WHITE_BALANCE = np.array([2.428159, 1.0, 2.205721], dtype=np.float32)
CCM = np.array(
    [
        [1.998794, -0.692318, -0.306485],
        [-0.466577, 2.065926, -0.599351],
        [-0.089408, -0.597580, 1.686988],
    ],
    dtype=np.float32,
)


def read_frame(raw, offset: int, frame_size: int, height: int, stride: int, width: int):
    raw.seek(offset)
    data = raw.read(frame_size)
    if len(data) != frame_size:
        raise RuntimeError("short read from RAW sequence")
    words_per_row = stride // 2
    # The CFE stores RAW10 codes left-shifted by six in little-endian uint16.
    return (
        np.frombuffer(data, dtype="<u2")
        .reshape(height, words_per_row)[:, :width]
        .astype(np.float32)
        / 64.0
    )


def merge_mosaic(short, long, short_us: float, long_us: float):
    short_radiance = np.maximum(short - BLACK_CODE, 0.0) / short_us
    long_radiance = np.maximum(long - BLACK_CODE, 0.0) / long_us
    # Prefer the cleaner long exposure until it approaches RAW10 saturation,
    # then cross-fade smoothly to the short exposure.
    long_weight = np.clip((980.0 - long) / 160.0, 0.0, 1.0)
    return long_radiance * long_weight + short_radiance * (1.0 - long_weight)


def demosaic_bggr(mosaic):
    """Small bilinear BGGR demosaic operating on linear radiance samples."""
    p = np.pad(mosaic, 1, mode="edge")
    c = p[1:-1, 1:-1]
    left, right = p[1:-1, :-2], p[1:-1, 2:]
    up, down = p[:-2, 1:-1], p[2:, 1:-1]
    ul, ur = p[:-2, :-2], p[:-2, 2:]
    dl, dr = p[2:, :-2], p[2:, 2:]

    r = np.empty_like(c)
    g = np.empty_like(c)
    b = np.empty_like(c)

    # BGGR: B at even/even, R at odd/odd.
    b[0::2, 0::2] = c[0::2, 0::2]
    b[0::2, 1::2] = (left[0::2, 1::2] + right[0::2, 1::2]) * 0.5
    b[1::2, 0::2] = (up[1::2, 0::2] + down[1::2, 0::2]) * 0.5
    b[1::2, 1::2] = (
        ul[1::2, 1::2] + ur[1::2, 1::2] + dl[1::2, 1::2] + dr[1::2, 1::2]
    ) * 0.25

    r[1::2, 1::2] = c[1::2, 1::2]
    r[1::2, 0::2] = (left[1::2, 0::2] + right[1::2, 0::2]) * 0.5
    r[0::2, 1::2] = (up[0::2, 1::2] + down[0::2, 1::2]) * 0.5
    r[0::2, 0::2] = (
        ul[0::2, 0::2] + ur[0::2, 0::2] + dl[0::2, 0::2] + dr[0::2, 0::2]
    ) * 0.25

    g[0::2, 1::2] = c[0::2, 1::2]
    g[1::2, 0::2] = c[1::2, 0::2]
    axial = (left + right + up + down) * 0.25
    g[0::2, 0::2] = axial[0::2, 0::2]
    g[1::2, 1::2] = axial[1::2, 1::2]

    return np.stack((r, g, b), axis=-1)


def colour_correct(rgb):
    balanced = rgb * WHITE_BALANCE
    return np.maximum(balanced @ CCM.T, 0.0)


def to_srgb8(rgb, white: float):
    exposed = rgb * (4.0 / white)
    mapped = exposed / (1.0 + exposed)
    srgb = np.where(
        mapped <= 0.0031308,
        mapped * 12.92,
        1.055 * np.power(mapped, 1.0 / 2.4) - 0.055,
    )
    return np.clip(srgb * 255.0 + 0.5, 0, 255).astype(np.uint8)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    manifest = json.loads((args.run_dir / "manifest.json").read_text())
    with (args.run_dir / manifest["metadata_file"]).open(newline="") as source:
        rows = list(csv.DictReader(source))

    if len(rows) % 2:
        raise RuntimeError("metadata has an odd frame count")
    exposure_pair = [int(rows[0]["actual_us"]), int(rows[1]["actual_us"])]
    if exposure_pair[0] >= exposure_pair[1]:
        raise RuntimeError("the first retained frame must be the short exposure")
    for index, row in enumerate(rows):
        expected = exposure_pair[index % 2]
        if int(row["actual_us"]) != expected:
            raise RuntimeError(
                f"frame {index} exposure is {row['actual_us']}, expected {expected}"
            )

    stream = manifest["stream"]
    width, height = int(stream["width"]), int(stream["height"])
    stride, frame_size = int(stream["stride"]), int(stream["frame_size"])
    output = args.output or args.run_dir / "hdr_30fps.mp4"

    raw_path = args.run_dir / manifest["raw_file"]["name"]
    with raw_path.open("rb") as raw:
        short = read_frame(raw, int(rows[0]["byte_offset"]), frame_size, height, stride, width)
        long = read_frame(raw, int(rows[1]["byte_offset"]), frame_size, height, stride, width)
        first = colour_correct(
            demosaic_bggr(
                merge_mosaic(short, long, float(rows[0]["actual_us"]), float(rows[1]["actual_us"]))
            )
        )
        white = max(float(np.percentile(first[::4, ::4], 99.5)), 1e-6)

        command = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pixel_format", "rgb24",
            "-video_size", f"{width}x{height}", "-framerate", "30",
            "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium",
            "-crf", "14", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(output),
        ]
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
        assert encoder.stdin is not None
        try:
            for pair in range(0, len(rows), 2):
                short_row, long_row = rows[pair], rows[pair + 1]
                short = read_frame(
                    raw, int(short_row["byte_offset"]), frame_size, height, stride, width
                )
                long = read_frame(
                    raw, int(long_row["byte_offset"]), frame_size, height, stride, width
                )
                mosaic = merge_mosaic(
                    short, long, float(short_row["actual_us"]), float(long_row["actual_us"])
                )
                rgb = colour_correct(demosaic_bggr(mosaic))
                # The module is registered with a 180-degree mounting rotation.
                frame = np.ascontiguousarray(np.rot90(to_srgb8(rgb, white), 2))
                encoder.stdin.write(frame.tobytes())
        finally:
            encoder.stdin.close()
        if encoder.wait() != 0:
            raise RuntimeError("ffmpeg encoding failed")

    merge_manifest = {
        "output": output.name,
        "output_fps": 30,
        "output_frames": len(rows) // 2,
        "source_raw": raw_path.name,
        "source_sha256": manifest["raw_file"]["sha256"],
        "source_format": stream["pixel_format"],
        "actual_exposures_us": exposure_pair,
        "black_code_raw10": BLACK_CODE,
        "tone_map_white_radiance": white,
        "demosaic": "bilinear BGGR",
        "encoder": "H.264 CRF 14 yuv420p",
    }
    (args.run_dir / "hdr_30fps.json").write_text(
        json.dumps(merge_manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(merge_manifest, indent=2))


if __name__ == "__main__":
    main()
