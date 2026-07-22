#!/usr/bin/env python3
"""Merge a metadata-verified five-exposure IMX296 RAW video sequence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

from calibrate_linear_radiance import virtual_dark
from export_still_bracket_tiffs import demosaic_bggr
from render_colour_response import CCM, WHITE_BALANCE, coordinate_safe_tonemap


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("dark_library", type=Path)
    parser.add_argument("--clip-code", type=int, default=1000)
    args = parser.parse_args()

    manifest = json.loads((args.run_dir / "manifest.json").read_text())
    rows = list(csv.DictReader((args.run_dir / manifest["metadata_file"]).open()))
    bracket_size = int(manifest["capture"].get("bracket_size", 0))
    if bracket_size != 5 or len(rows) % bracket_size:
        raise RuntimeError("capture is not a whole five-exposure sequence")
    exposure_cycle = [int(rows[index]["actual_us"]) for index in range(bracket_size)]
    exposures = sorted(set(exposure_cycle))
    if len(exposures) != bracket_size:
        raise RuntimeError(f"invalid first bracket: {exposures}")
    for index, row in enumerate(rows):
        expected = exposure_cycle[index % bracket_size]
        if int(row["actual_us"]) != expected:
            raise RuntimeError(
                f"frame {index}: exposure {row['actual_us']}, expected {expected}"
            )

    stream = manifest["stream"]
    width, height = int(stream["width"]), int(stream["height"])
    stride, frame_size = int(stream["stride"]), int(stream["frame_size"])
    if (width, height) != (1456, 1088):
        raise RuntimeError("expected the full-resolution IMX296 stream")

    dark_manifest = json.loads((args.dark_library / "dark_library.json").read_text())
    dark_points = sorted(
        dark_manifest["points"], key=lambda point: point["actual_exposure_us"]
    )
    darks = {
        exposure: virtual_dark(args.dark_library, dark_points, exposure, True)
        for exposure in exposures
    }

    frame_intervals = [
        (int(rows[index]["sensor_timestamp_ns"]) -
         int(rows[index - 1]["sensor_timestamp_ns"])) / 1e9
        for index in range(1, len(rows))
    ]
    sensor_interval = float(np.median(frame_intervals))
    output_fps = 1.0 / (sensor_interval * bracket_size)
    cycles = len(rows) // bracket_size
    output_dir = args.run_dir / "merged_hdr5"
    output_dir.mkdir(exist_ok=True)
    radiance_path = output_dir / "linear_radiance_bggr_60frames.raw32f"
    video_path = output_dir / "hdr5_tonemapped.mp4"

    def read_frame(raw_file, row):
        raw_file.seek(int(row["byte_offset"]))
        data = raw_file.read(frame_size)
        if len(data) != frame_size:
            raise RuntimeError("short RAW frame read")
        return np.frombuffer(data, dtype="<u2").reshape(
            height, stride // 2
        )[:, :width]

    def merge_cycle(raw_file, cycle_rows):
        weighted = np.zeros((height, width), dtype=np.float64)
        weights = np.zeros((height, width), dtype=np.float64)
        contributors = np.zeros((height, width), dtype=np.uint8)
        clipped = []
        for row in cycle_rows:
            exposure = int(row["actual_us"])
            raw16 = read_frame(raw_file, row)
            raw10 = raw16 >> 6
            radiance = ((raw16.astype(np.float32) - darks[exposure]) / 64.0) / (
                exposure / 1_000_000.0
            )
            finite = raw10 < args.clip_code
            weight = float(exposure) ** 2
            weighted[finite] += radiance[finite] * weight
            weights[finite] += weight
            contributors[finite] += 1
            clipped.append(int(np.count_nonzero(~finite)))
        if np.any(weights == 0):
            raise RuntimeError("a cycle contains pixels clipped in every exposure")
        return (weighted / weights).astype("<f4"), contributors, clipped

    raw_path = args.run_dir / manifest["raw_file"]["name"]
    radiance_digest = hashlib.sha256()
    records = []
    with raw_path.open("rb") as raw_file:
        first, _, _ = merge_cycle(raw_file, rows[:bracket_size])
        corrected = (demosaic_bggr(first) * WHITE_BALANCE) @ CCM.T
        positive = corrected[corrected > 0]
        white = max(float(np.percentile(positive, 99.5)), 1e-6)

        command = [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo",
            "-pixel_format", "rgb24", "-video_size", f"{width}x{height}",
            "-framerate", f"{output_fps:.9f}", "-i", "-", "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "14",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video_path),
        ]
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
        assert encoder.stdin is not None
        with radiance_path.open("wb") as radiance_file:
            try:
                for cycle in range(cycles):
                    start = cycle * bracket_size
                    mosaic, contributors, clipped = merge_cycle(
                        raw_file, rows[start:start + bracket_size]
                    )
                    payload = mosaic.tobytes()
                    radiance_file.write(payload)
                    radiance_digest.update(payload)
                    corrected = (demosaic_bggr(mosaic) * WHITE_BALANCE) @ CCM.T
                    srgb = coordinate_safe_tonemap(corrected, white)
                    frame = np.ascontiguousarray(
                        np.rot90(np.rint(srgb * 255.0).astype(np.uint8), 2)
                    )
                    encoder.stdin.write(frame.tobytes())
                    records.append({
                        "cycle": cycle,
                        "clipped_pixels_by_exposure": clipped,
                        "minimum_contributors": int(contributors.min()),
                        "maximum_contributors": int(contributors.max()),
                    })
            finally:
                encoder.stdin.close()
        if encoder.wait() != 0:
            raise RuntimeError("ffmpeg encoding failed")

    output = {
        "source_raw": str(raw_path.relative_to(args.run_dir)),
        "source_sha256": manifest["raw_file"]["sha256"],
        "source_frames": len(rows),
        "actual_exposures_us": exposures,
        "recorded_exposure_cycle_us": exposure_cycle,
        "verified_sequence": True,
        "sensor_frame_interval_s": sensor_interval,
        "bracket_temporal_span_s": sensor_interval * (bracket_size - 1),
        "output_frames": cycles,
        "output_fps": output_fps,
        "output_duration_s": cycles / output_fps,
        "linear_radiance_stream": radiance_path.name,
        "linear_radiance_sha256": radiance_digest.hexdigest(),
        "linear_radiance_format": "60 concatenated 1456x1088 little-endian float32 BGGR frames; RAW10 counts/second",
        "video": video_path.name,
        "clip_mask": f"native RAW10 code >= {args.clip_code}",
        "merge": "exposure-squared weighted mean of finite samples per cycle",
        "dark_calibration": "per-pixel interpolated virtual dark; nearest 992 us master below library range",
        "tone_map_white_radiance": white,
        "viewing_derivative": "bilinear demosaic, stored WB/CCM, coordinate-safe luminance tone map, sRGB, H.264 CRF 14",
        "cycles": records,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: output[key] for key in (
        "actual_exposures_us", "output_frames", "output_fps",
        "output_duration_s", "linear_radiance_sha256", "video"
    )}, indent=2))


if __name__ == "__main__":
    main()
