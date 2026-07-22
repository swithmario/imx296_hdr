#!/usr/bin/env python3
"""Stack independent calibrated Bayer stills into one linear HDR radiance mosaic."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, TiffImagePlugin


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bracket", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--read-noise-counts", type=float, default=0.5)
    parser.add_argument("--taper-start", type=float, default=900.0)
    parser.add_argument("--taper-end", type=float, default=1000.0)
    args = parser.parse_args()
    if not 0 <= args.taper_start < args.taper_end <= 1023:
        raise ValueError("invalid saturation taper")

    points = sorted(args.bracket.glob("*us"), key=lambda p: int(p.name[:-2]))
    if len(points) < 2:
        raise RuntimeError("expected at least two exposure points")
    output_dir = args.output_dir or args.bracket / "stacked_linear_radiance"
    output_dir.mkdir(parents=True, exist_ok=True)

    numerator = np.zeros((1088, 1456), dtype=np.float64)
    denominator = np.zeros((1088, 1456), dtype=np.float64)
    contributors = np.zeros((1088, 1456), dtype=np.uint8)
    longest_exposure = np.zeros((1088, 1456), dtype=np.float32)
    records = []

    for point in points:
        manifest = json.loads((point / "manifest.json").read_text())
        row = next(csv.DictReader((point / manifest["metadata_file"]).open()))
        exposure_us = int(row["actual_us"])
        exposure_s = exposure_us / 1_000_000.0
        stream = manifest["stream"]
        raw = (np.fromfile(point / manifest["raw_file"]["name"], dtype="<u2")
               .reshape(int(stream["height"]), int(stream["stride"]) // 2)
               [:, :int(stream["width"])].astype(np.float64) / 64.0)
        radiance_path = point / "linear_radiance/sources/frame_000.raw32f"
        radiance = np.fromfile(radiance_path, dtype="<f4").reshape(1088, 1456)

        # The Poisson term in sensor-count units is approximated by measured
        # signal = radiance * time. Inverse radiance variance is therefore
        # proportional to t^2 / (read_noise^2 + max(signal, 0)).
        signal = radiance.astype(np.float64) * exposure_s
        inverse_variance = exposure_s**2 / (
            args.read_noise_counts**2 + np.maximum(signal, 0.0)
        )
        saturation_taper = np.clip(
            (args.taper_end - raw) / (args.taper_end - args.taper_start), 0.0, 1.0
        )
        weight = inverse_variance * saturation_taper**2
        valid = weight > 0
        numerator[valid] += radiance[valid] * weight[valid]
        denominator[valid] += weight[valid]
        contributors[valid] += 1
        longest_exposure[valid] = exposure_s
        records.append({
            "actual_exposure_us": exposure_us,
            "raw_saturated_pixels": int(np.count_nonzero(raw >= 1023)),
            "accepted_pixels": int(np.count_nonzero(valid)),
            "source": str(point.relative_to(args.bracket)),
        })

    uncovered = denominator == 0
    if np.any(uncovered):
        raise RuntimeError(f"{int(np.count_nonzero(uncovered))} pixels have no valid exposure")
    stacked = (numerator / denominator).astype("<f4")
    stack_path = output_dir / "radiance_bggr.raw32f"
    stack_path.write_bytes(stacked.tobytes())
    tiff_path = output_dir / "radiance_bggr_float32.tiff"
    tiff_info = TiffImagePlugin.ImageFileDirectory_v2()
    tiff_info[270] = (
        "IMX296 BGGR Bayer linear radiance; float32 RAW10 counts/second; "
        "virtual-dark subtracted; no demosaic, gamma, tone map, clamp, CCM, "
        "white balance, or display scaling"
    )
    tiff_info[305] = "imx296-hdr stack_linear_radiance.py"
    Image.fromarray(stacked, mode="F").save(
        tiff_path, format="TIFF", compression="tiff_deflate", tiffinfo=tiff_info
    )
    contributors_path = output_dir / "contributor_count.raw8"
    contributors_path.write_bytes(contributors.tobytes())
    exposure_path = output_dir / "longest_accepted_exposure_s.raw32f"
    exposure_path.write_bytes(longest_exposure.astype("<f4").tobytes())

    output = {
        "width": 1456,
        "height": 1088,
        "cfa": "BGGR",
        "format": "little-endian float32 linear radiance, RAW10 counts per second",
        "stack": stack_path.name,
        "stack_sha256": hashlib.sha256(stack_path.read_bytes()).hexdigest(),
        "float32_tiff": tiff_path.name,
        "float32_tiff_sha256": hashlib.sha256(tiff_path.read_bytes()).hexdigest(),
        "weighting": "inverse approximate radiance variance times squared saturation taper",
        "read_noise_counts_assumed": args.read_noise_counts,
        "saturation_taper_raw10": [args.taper_start, args.taper_end],
        "nonlinear_output_processing": "none",
        "negative_values": "retained",
        "diagnostics": {
            "contributor_count": contributors_path.name,
            "longest_accepted_exposure_s": exposure_path.name,
            "minimum_contributors": int(contributors.min()),
            "maximum_contributors": int(contributors.max()),
        },
        "sources": records,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "stack": str(stack_path),
        "sha256": output["stack_sha256"],
        "min_contributors": output["diagnostics"]["minimum_contributors"],
        "max_contributors": output["diagnostics"]["maximum_contributors"],
    }, indent=2))


if __name__ == "__main__":
    main()
