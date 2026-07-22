#!/usr/bin/env python3
"""Split an interleaved Bayer capture into separate short/long still arrays."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    manifest = json.loads((args.run_dir / "manifest.json").read_text())
    with (args.run_dir / manifest["metadata_file"]).open(newline="") as source:
        rows = list(csv.DictReader(source))

    frame_size = int(manifest["stream"]["frame_size"])
    raw_path = args.run_dir / manifest["raw_file"]["name"]
    source_root = args.run_dir / "sources"
    short_dir = source_root / "short"
    long_dir = source_root / "long"
    short_dir.mkdir(parents=True, exist_ok=True)
    long_dir.mkdir(parents=True, exist_ok=True)

    arrays = {"short": [], "long": []}
    counts = {"short": 0, "long": 0}
    previous_kind = None
    exposure_values = sorted({int(row["actual_us"]) for row in rows})
    if len(exposure_values) != 2:
        raise RuntimeError(f"expected two exposure values, got {exposure_values}")
    short_exposure, long_exposure = exposure_values

    with raw_path.open("rb") as raw:
        for interleaved_index, row in enumerate(rows):
            actual_us = int(row["actual_us"])
            if actual_us == short_exposure:
                kind = "short"
                output_dir = short_dir
            elif actual_us == long_exposure:
                kind = "long"
                output_dir = long_dir
            else:
                raise RuntimeError(
                    f"unexpected exposure {actual_us} at frame {interleaved_index}"
                )
            if previous_kind == kind:
                raise RuntimeError("source frames do not alternate")
            previous_kind = kind

            source_index = counts[kind]
            counts[kind] += 1
            filename = f"{kind}_{source_index:03d}.raw16"
            raw.seek(int(row["byte_offset"]))
            frame = raw.read(frame_size)
            if len(frame) != frame_size:
                raise RuntimeError("short read from Bayer master")
            (output_dir / filename).write_bytes(frame)

            arrays[kind].append(
                {
                    "index": source_index,
                    "filename": f"{kind}/{filename}",
                    "interleaved_index": interleaved_index,
                    "sensor_sequence": int(row["sensor_sequence"]),
                    "actual_exposure_us": actual_us,
                    "sensor_timestamp_ns": int(row["sensor_timestamp_ns"]),
                    "bytes": len(frame),
                    "sha256": hashlib.sha256(frame).hexdigest(),
                }
            )

    if counts != {"short": 60, "long": 60}:
        raise RuntimeError(f"unexpected source counts: {counts}")

    split_manifest = {
        "source_master": raw_path.name,
        "source_master_sha256": manifest["raw_file"]["sha256"],
        "stream": manifest["stream"],
        "layout": "little-endian SBGGR16; RAW10 codes left-shifted by 6 bits",
        "short": {
            "actual_exposure_us": short_exposure,
            "frame_count": counts["short"],
            "frames": arrays["short"],
        },
        "long": {
            "actual_exposure_us": long_exposure,
            "frame_count": counts["long"],
            "frames": arrays["long"],
        },
    }
    (source_root / "arrays.json").write_text(
        json.dumps(split_manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"short": counts["short"], "long": counts["long"]}))


if __name__ == "__main__":
    main()
