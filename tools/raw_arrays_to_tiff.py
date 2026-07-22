#!/usr/bin/env python3
"""Wrap exact SBGGR16 source frames in self-describing 16-bit TIFF files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, TiffImagePlugin


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sources", type=Path)
    args = parser.parse_args()

    manifest = json.loads((args.sources / "arrays.json").read_text())
    stream = manifest["stream"]
    width = int(stream["width"])
    height = int(stream["height"])
    words_per_row = int(stream["stride"]) // 2

    for kind in ("short", "long"):
        output_dir = args.sources / f"{kind}_tiff"
        output_dir.mkdir(parents=True, exist_ok=True)
        exposure = int(manifest[kind]["actual_exposure_us"])

        for item in manifest[kind]["frames"]:
            source = args.sources / item["filename"]
            frame = np.fromfile(source, dtype="<u2").reshape(height, words_per_row)
            # Remove only row padding. Pixel values remain bit-for-bit unchanged.
            image = np.ascontiguousarray(frame[:, :width])

            info = TiffImagePlugin.ImageFileDirectory_v2()
            info[270] = (
                f"IMX296 SBGGR Bayer; exposure={exposure} us; "
                "RAW10 sensor codes left-shifted by 6; no demosaic or tone mapping"
            )
            info[305] = "rpicam software HDR experiment"
            output = output_dir / (source.stem + ".tiff")
            Image.fromarray(image, mode="I;16").save(
                output,
                format="TIFF",
                compression="tiff_deflate",
                tiffinfo=info,
            )

    print("created 60 short TIFFs and 60 long TIFFs")


if __name__ == "__main__":
    main()
