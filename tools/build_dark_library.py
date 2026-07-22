#!/usr/bin/env python3
"""Validate ten-frame dark sets and build float32 per-pixel mean masters."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    args = parser.parse_args()

    points = []
    for point_dir in sorted(args.library.glob("*us"), key=lambda p: int(p.name[:-2])):
        manifest = json.loads((point_dir / "manifest.json").read_text())
        rows = list(csv.DictReader((point_dir / manifest["metadata_file"]).open()))
        if len(rows) != 10:
            raise RuntimeError(f"{point_dir}: expected 10 frames, got {len(rows)}")
        actual = {int(row["actual_us"]) for row in rows}
        if len(actual) != 1:
            raise RuntimeError(f"{point_dir}: inconsistent exposures {sorted(actual)}")

        stream = manifest["stream"]
        width, height = int(stream["width"]), int(stream["height"])
        stride, frame_size = int(stream["stride"]), int(stream["frame_size"])
        words_per_row = stride // 2
        total = np.zeros((height, width), dtype=np.uint64)
        with (point_dir / manifest["raw_file"]["name"]).open("rb") as raw:
            for row in rows:
                raw.seek(int(row["byte_offset"]))
                frame = raw.read(frame_size)
                if len(frame) != frame_size:
                    raise RuntimeError(f"{point_dir}: short RAW read")
                image = np.frombuffer(frame, dtype="<u2").reshape(height, words_per_row)
                total += image[:, :width]

        mean = (total / len(rows)).astype("<f4")
        master_path = point_dir / "mean_dark.raw32f"
        master_path.write_bytes(mean.tobytes())
        digest = hashlib.sha256(master_path.read_bytes()).hexdigest()
        points.append(
            {
                "requested_exposure_us": int(point_dir.name[:-2]),
                "actual_exposure_us": next(iter(actual)),
                "frames_averaged": 10,
                "analogue_gain": 1.0,
                "master": str(master_path.relative_to(args.library)),
                "master_format": "little-endian float32, 1456x1088, no padding",
                "sha256": digest,
            }
        )

    if len(points) < 2:
        raise RuntimeError(f"expected at least two exposure points, got {len(points)}")
    output = {
        "method": "per-pixel arithmetic mean of 10 native Bayer dark frames",
        "interpolation": "linear per pixel between bracketing actual exposure times",
        "points": points,
    }
    (args.library / "dark_library.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
