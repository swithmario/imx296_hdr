#!/usr/bin/env python3
"""Render a merged HDR5 sequence and its five sources as Mac ProRes movies."""

from __future__ import annotations

import argparse
import csv
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
    args = parser.parse_args()

    capture = json.loads((args.run_dir / "manifest.json").read_text())
    merged_dir = args.run_dir / "merged_hdr5"
    merged = json.loads((merged_dir / "manifest.json").read_text())
    rows = list(csv.DictReader((args.run_dir / capture["metadata_file"]).open()))
    exposure_cycle = merged["recorded_exposure_cycle_us"]
    exposures = merged["actual_exposures_us"]
    cycles = int(merged["output_frames"])
    fps = float(merged["output_fps"])
    white = float(merged["tone_map_white_radiance"])

    stream = capture["stream"]
    width, height = int(stream["width"]), int(stream["height"])
    stride, frame_size = int(stream["stride"]), int(stream["frame_size"])
    dark_manifest = json.loads((args.dark_library / "dark_library.json").read_text())
    dark_points = sorted(
        dark_manifest["points"], key=lambda point: point["actual_exposure_us"]
    )
    darks = {
        exposure: virtual_dark(args.dark_library, dark_points, exposure, True)
        for exposure in exposures
    }

    output_dir = merged_dir / "prores_mac"
    output_dir.mkdir(exist_ok=True)
    outputs = {"stacked": output_dir / "hdr5_stacked_prores422hq.mov"}
    outputs.update({
        exposure: output_dir / f"source_{exposure:06d}us_prores422hq.mov"
        for exposure in exposures
    })

    def encoder(path: Path):
        command = [
            "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo",
            "-pixel_format", "rgb48le", "-video_size", f"{width}x{height}",
            "-framerate", f"{fps:.9f}", "-i", "-", "-an", "-c:v",
            "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le",
            "-vendor", "apl0", str(path),
        ]
        process = subprocess.Popen(command, stdin=subprocess.PIPE)
        assert process.stdin is not None
        return process

    encoders = {key: encoder(path) for key, path in outputs.items()}

    def render(mosaic: np.ndarray) -> bytes:
        corrected = (demosaic_bggr(mosaic) * WHITE_BALANCE) @ CCM.T
        srgb = coordinate_safe_tonemap(corrected, white)
        rgb16 = np.ascontiguousarray(
            np.rot90(np.rint(np.clip(srgb, 0.0, 1.0) * 65535.0).astype("<u2"), 2)
        )
        return rgb16.tobytes()

    raw_path = args.run_dir / capture["raw_file"]["name"]
    radiance_path = merged_dir / merged["linear_radiance_stream"]
    try:
        with raw_path.open("rb") as raw, radiance_path.open("rb") as radiance:
            for cycle in range(cycles):
                merged_frame = np.frombuffer(
                    radiance.read(width * height * 4), dtype="<f4"
                ).reshape(height, width)
                encoders["stacked"].stdin.write(render(merged_frame))

                cycle_rows = rows[cycle * 5:(cycle + 1) * 5]
                for row in cycle_rows:
                    exposure = int(row["actual_us"])
                    raw.seek(int(row["byte_offset"]))
                    raw16 = np.frombuffer(
                        raw.read(frame_size), dtype="<u2"
                    ).reshape(height, stride // 2)[:, :width]
                    source_radiance = (
                        (raw16.astype(np.float32) - darks[exposure]) / 64.0
                    ) / (exposure / 1_000_000.0)
                    encoders[exposure].stdin.write(render(source_radiance))
    finally:
        for process in encoders.values():
            process.stdin.close()

    failures = []
    for key, process in encoders.items():
        if process.wait() != 0:
            failures.append(str(key))
    if failures:
        raise RuntimeError(f"ProRes encoders failed: {', '.join(failures)}")

    record = {
        "format": "Apple ProRes 422 HQ, 10-bit 4:2:2, QuickTime MOV",
        "width": width,
        "height": height,
        "frames_each": cycles,
        "fps": fps,
        "duration_s": cycles / fps,
        "common_tone_map_white_radiance": white,
        "stacked": str(outputs["stacked"].relative_to(args.run_dir)),
        "sources": [
            {"actual_exposure_us": exposure,
             "file": str(outputs[exposure].relative_to(args.run_dir))}
            for exposure in exposures
        ],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
