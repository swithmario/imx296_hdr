#!/usr/bin/env python3
"""Dark-calibrate RAW Bayer frames and write linear float32 radiance arrays."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np


def virtual_dark(
    library: Path, points: list[dict], exposure_us: int, allow_nearest: bool = False
) -> np.ndarray:
    lower = max((p for p in points if p["actual_exposure_us"] <= exposure_us),
                key=lambda p: p["actual_exposure_us"], default=None)
    upper = min((p for p in points if p["actual_exposure_us"] >= exposure_us),
                key=lambda p: p["actual_exposure_us"], default=None)
    if lower is None or upper is None:
        if allow_nearest:
            nearest = min(points, key=lambda p: abs(p["actual_exposure_us"] - exposure_us))
            return np.fromfile(library / nearest["master"], dtype="<f4").reshape(1088, 1456)
        raise ValueError(f"exposure {exposure_us} us is outside dark calibration range")
    lo = np.fromfile(library / lower["master"], dtype="<f4").reshape(1088, 1456)
    if lower is upper:
        return lo
    hi = np.fromfile(library / upper["master"], dtype="<f4").reshape(1088, 1456)
    weight = ((exposure_us - lower["actual_exposure_us"]) /
              (upper["actual_exposure_us"] - lower["actual_exposure_us"]))
    return lo + (hi - lo) * weight


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("dark_library", type=Path)
    parser.add_argument(
        "--allow-nearest-dark", action="store_true",
        help="use the nearest endpoint master outside the calibrated exposure range",
    )
    args = parser.parse_args()

    manifest = json.loads((args.run_dir / "manifest.json").read_text())
    dark_manifest = json.loads((args.dark_library / "dark_library.json").read_text())
    points = sorted(dark_manifest["points"], key=lambda p: p["actual_exposure_us"])
    rows = list(csv.DictReader((args.run_dir / manifest["metadata_file"]).open()))
    stream = manifest["stream"]
    width, height = int(stream["width"]), int(stream["height"])
    stride, frame_size = int(stream["stride"]), int(stream["frame_size"])
    if (width, height) != (1456, 1088):
        raise RuntimeError("dark library is calibrated for 1456x1088 only")

    output_root = args.run_dir / "linear_radiance"
    source_root = output_root / "sources"
    pair_root = output_root / "pairs"
    source_root.mkdir(parents=True, exist_ok=True)
    pair_root.mkdir(parents=True, exist_ok=True)
    raw_path = args.run_dir / manifest["raw_file"]["name"]
    calibrated = []
    source_records = []

    with raw_path.open("rb") as raw:
        for index, row in enumerate(rows):
            exposure_us = int(row["actual_us"])
            raw.seek(int(row["byte_offset"]))
            frame = raw.read(frame_size)
            image = (np.frombuffer(frame, dtype="<u2")
                     .reshape(height, stride // 2)[:, :width].astype(np.float32))
            dark = virtual_dark(
                args.dark_library, points, exposure_us, args.allow_nearest_dark
            )
            # RAW16 stores RAW10 codes left-shifted by six. Convert both to
            # RAW10 counts, subtract in Bayer space, then divide by seconds.
            radiance = ((image - dark) / 64.0) / (exposure_us / 1_000_000.0)
            radiance = radiance.astype("<f4")
            calibrated.append((image, radiance, exposure_us))
            path = source_root / f"frame_{index:03d}.raw32f"
            path.write_bytes(radiance.tobytes())
            source_records.append({
                "index": index,
                "actual_exposure_us": exposure_us,
                "file": str(path.relative_to(output_root)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })

    pair_records = []
    if len(calibrated) % 2 == 0:
        for pair_index in range(0, len(calibrated), 2):
            short_raw, short_rad, short_us = calibrated[pair_index]
            long_raw, long_rad, long_us = calibrated[pair_index + 1]
            if short_us >= long_us:
                break
            # Prefer long-exposure radiance until its uncalibrated RAW10 code
            # approaches saturation, then cross-fade to the short exposure.
            long_code = long_raw / 64.0
            long_weight = np.clip((980.0 - long_code) / 160.0, 0.0, 1.0)
            merged = (long_rad * long_weight + short_rad * (1.0 - long_weight)).astype("<f4")
            path = pair_root / f"pair_{pair_index // 2:03d}.raw32f"
            path.write_bytes(merged.tobytes())
            pair_records.append({
                "index": pair_index // 2,
                "short_exposure_us": short_us,
                "long_exposure_us": long_us,
                "file": str(path.relative_to(output_root)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })

    output_manifest = {
        "width": width,
        "height": height,
        "cfa": "BGGR",
        "format": "little-endian float32 Bayer radiance, counts per second",
        "processing": [
            "interpolate virtual dark per pixel at actual exposure",
            "subtract dark from native Bayer measurement",
            "divide by actual exposure seconds",
        ],
        "nonlinear_processing": "none",
        "negative_values": "retained; no post-subtraction clamp",
        "out_of_range_dark_policy": (
            "nearest endpoint master" if args.allow_nearest_dark else "error"
        ),
        "sources": source_records,
        "pairs": pair_records,
    }
    (output_root / "manifest.json").write_text(
        json.dumps(output_manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"sources": len(source_records), "pairs": len(pair_records)}))


if __name__ == "__main__":
    main()
