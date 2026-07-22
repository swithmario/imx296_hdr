#!/usr/bin/env python3
"""NaN-mask clipped RAW samples and average linear Bayer radiance frames."""

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
    parser.add_argument(
        "--clip-code", type=int, default=1023,
        help="RAW10 codes at or above this value become NaN (default: 1023)",
    )
    args = parser.parse_args()
    if not 1 <= args.clip_code <= 1023:
        raise ValueError("clip code must be in [1, 1023]")

    points = sorted(args.bracket.glob("*us"), key=lambda p: int(p.name[:-2]))
    if len(points) < 2:
        raise RuntimeError("expected at least two exposure points")
    output_dir = args.output_dir or args.bracket / "stacked_linear_radiance"
    output_dir.mkdir(parents=True, exist_ok=True)

    finite_sum = np.zeros((1088, 1456), dtype=np.float64)
    contributors = np.zeros((1088, 1456), dtype=np.uint16)
    records = []

    for point in points:
        manifest = json.loads((point / "manifest.json").read_text())
        rows = list(csv.DictReader((point / manifest["metadata_file"]).open()))
        stream = manifest["stream"]
        width, height = int(stream["width"]), int(stream["height"])
        stride, frame_size = int(stream["stride"]), int(stream["frame_size"])
        if (width, height) != (1456, 1088):
            raise RuntimeError("only 1456x1088 captures are supported")
        raw_path = point / manifest["raw_file"]["name"]
        exposure_records = []
        with raw_path.open("rb") as raw_file:
            for index, row in enumerate(rows):
                raw_file.seek(int(row["byte_offset"]))
                raw16 = (np.frombuffer(raw_file.read(frame_size), dtype="<u2")
                         .reshape(height, stride // 2)[:, :width])
                raw10 = raw16 >> 6
                radiance_path = point / f"linear_radiance/sources/frame_{index:03d}.raw32f"
                radiance = np.fromfile(radiance_path, dtype="<f4").reshape(height, width)

                # Clipped measurements do not represent radiance. Express that
                # explicitly as NaN, then add only finite samples to the mean.
                masked = radiance.astype(np.float64)
                masked[raw10 >= args.clip_code] = np.nan
                finite = np.isfinite(masked)
                finite_sum[finite] += masked[finite]
                contributors[finite] += 1
                exposure_records.append({
                    "index": index,
                    "actual_exposure_us": int(row["actual_us"]),
                    "clipped_pixels": int(np.count_nonzero(~finite)),
                    "finite_pixels": int(np.count_nonzero(finite)),
                })
        records.append({
            "requested_exposure": point.name,
            "source": str(point.relative_to(args.bracket)),
            "frames": exposure_records,
        })

    uncovered = contributors == 0
    if np.any(uncovered):
        raise RuntimeError(f"{int(np.count_nonzero(uncovered))} pixels have no finite exposure")
    stacked = (finite_sum / contributors).astype("<f4")
    stack_path = output_dir / "radiance_bggr_nanmean.raw32f"
    stack_path.write_bytes(stacked.tobytes())
    tiff_path = output_dir / "radiance_bggr_nanmean_float32.tiff"
    tiff_info = TiffImagePlugin.ImageFileDirectory_v2()
    tiff_info[270] = (
        "IMX296 BGGR Bayer linear radiance; float32 RAW10 counts/second; "
        "virtual-dark subtracted; sensor-clipped samples replaced by NaN and "
        "excluded from finite mean; negatives retained; no demosaic, gamma, "
        "tone map, clamp, CCM, white balance, or display scaling"
    )
    tiff_info[305] = "imx296-hdr stack_linear_radiance.py"
    Image.fromarray(stacked, mode="F").save(
        tiff_path, format="TIFF", compression="tiff_deflate", tiffinfo=tiff_info
    )
    contributors_path = output_dir / "contributor_count_uint16.tiff"
    Image.fromarray(contributors).save(
        contributors_path, format="TIFF", compression="tiff_deflate"
    )

    output = {
        "width": 1456,
        "height": 1088,
        "cfa": "BGGR",
        "format": "little-endian float32 linear radiance, RAW10 counts per second",
        "stack": stack_path.name,
        "stack_sha256": hashlib.sha256(stack_path.read_bytes()).hexdigest(),
        "float32_tiff": tiff_path.name,
        "contributor_count_tiff": contributors_path.name,
        "merge": "arithmetic mean of finite radiance samples",
        "nan_mask": f"native RAW10 code >= {args.clip_code}",
        "clip_code_raw10": args.clip_code,
        "nonlinear_output_processing": "none",
        "negative_values": "retained",
        "minimum_contributors": int(contributors.min()),
        "maximum_contributors": int(contributors.max()),
        "sources": records,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "stack": str(stack_path),
        "sha256": output["stack_sha256"],
        "min_contributors": output["minimum_contributors"],
        "max_contributors": output["maximum_contributors"],
    }, indent=2))


if __name__ == "__main__":
    main()
