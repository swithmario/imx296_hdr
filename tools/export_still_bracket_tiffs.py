#!/usr/bin/env python3
"""Export exact RAW, calibrated radiance, and merged linear TIFF images."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, TiffImagePlugin


def tiff_info(description: str) -> TiffImagePlugin.ImageFileDirectory_v2:
    info = TiffImagePlugin.ImageFileDirectory_v2()
    info[270] = description
    info[305] = "imx296-hdr export_still_bracket_tiffs.py"
    return info


def demosaic_bggr(mosaic: np.ndarray) -> np.ndarray:
    p = np.pad(mosaic, 1, mode="edge")
    c = p[1:-1, 1:-1]
    left, right = p[1:-1, :-2], p[1:-1, 2:]
    up, down = p[:-2, 1:-1], p[2:, 1:-1]
    ul, ur = p[:-2, :-2], p[:-2, 2:]
    dl, dr = p[2:, :-2], p[2:, 2:]
    r, g, b = np.empty_like(c), np.empty_like(c), np.empty_like(c)
    b[0::2, 0::2] = c[0::2, 0::2]
    b[0::2, 1::2] = (left[0::2, 1::2] + right[0::2, 1::2]) * 0.5
    b[1::2, 0::2] = (up[1::2, 0::2] + down[1::2, 0::2]) * 0.5
    b[1::2, 1::2] = (ul[1::2, 1::2] + ur[1::2, 1::2] + dl[1::2, 1::2] + dr[1::2, 1::2]) * 0.25
    r[1::2, 1::2] = c[1::2, 1::2]
    r[1::2, 0::2] = (left[1::2, 0::2] + right[1::2, 0::2]) * 0.5
    r[0::2, 1::2] = (up[0::2, 1::2] + down[0::2, 1::2]) * 0.5
    r[0::2, 0::2] = (ul[0::2, 0::2] + ur[0::2, 0::2] + dl[0::2, 0::2] + dr[0::2, 0::2]) * 0.25
    g[0::2, 1::2] = c[0::2, 1::2]
    g[1::2, 0::2] = c[1::2, 0::2]
    axial = (left + right + up + down) * 0.25
    g[0::2, 0::2] = axial[0::2, 0::2]
    g[1::2, 1::2] = axial[1::2, 1::2]
    return np.stack((r, g, b), axis=-1)


def write_rgb48_tiff(path: Path, rgb16: np.ndarray) -> None:
    command = [
        "ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo",
        "-pixel_format", "rgb48le", "-video_size", "1456x1088", "-i", "-",
        "-frames:v", "1", "-compression_algo", "deflate", str(path),
    ]
    encoded = subprocess.run(command, input=rgb16.astype("<u2").tobytes(), check=False)
    if encoded.returncode:
        raise RuntimeError(f"ffmpeg failed to write 48-bit RGB TIFF: {path}")


def percentile_minmax(rgb: np.ndarray, tail_percent: float = 0.01):
    """Linearly map RGB using shared percentiles, ignoring extreme hot pixels."""
    lower, upper = map(
        float, np.percentile(rgb, [tail_percent, 100.0 - tail_percent])
    )
    if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
        raise RuntimeError("invalid percentile min-max interval")
    normalized = np.clip((rgb - lower) / (upper - lower), 0.0, 1.0)
    return normalized, lower, upper


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bracket", type=Path)
    parser.add_argument("--white-percentile", type=float, default=99.9)
    args = parser.parse_args()
    stack_dir = args.bracket / "stacked_linear_radiance"
    stack_manifest = json.loads((stack_dir / "manifest.json").read_text())
    stack = np.fromfile(stack_dir / stack_manifest["stack"], dtype="<f4").reshape(1088, 1456)
    positive = stack[stack > 0]
    white = float(np.percentile(positive, args.white_percentile))
    if not np.isfinite(white) or white <= 0:
        raise RuntimeError("invalid global radiance white scale")

    raw_dir = args.bracket / "raw_tiff"
    calibrated_dir = args.bracket / "calibrated_radiance_tiff"
    view_dir = args.bracket / "calibrated_linear_view_tiff"
    colour_preview_dir = args.bracket / "colour_minmax_preview_tiff"
    raw_dir.mkdir(exist_ok=True)
    calibrated_dir.mkdir(exist_ok=True)
    view_dir.mkdir(exist_ok=True)
    colour_preview_dir.mkdir(exist_ok=True)
    records = []

    points = sorted(args.bracket.glob("*us"), key=lambda p: int(p.name[:-2]))
    for point in points:
        manifest = json.loads((point / "manifest.json").read_text())
        rows = list(csv.DictReader((point / manifest["metadata_file"]).open()))
        stream = manifest["stream"]
        height, width = int(stream["height"]), int(stream["width"])
        stride, frame_size = int(stream["stride"]), int(stream["frame_size"])
        raw_file = (point / manifest["raw_file"]["name"]).open("rb")
        for frame_index, row in enumerate(rows):
            exposure_us = int(row["actual_us"])
            raw_file.seek(int(row["byte_offset"]))
            raw = (np.frombuffer(raw_file.read(frame_size), dtype="<u2")
                   .reshape(height, stride // 2)[:, :width])
            radiance = np.fromfile(
                point / f"linear_radiance/sources/frame_{frame_index:03d}.raw32f",
                dtype="<f4",
            ).reshape(height, width)
            stem = f"{exposure_us:08d}us_frame_{frame_index:03d}"

            raw_path = raw_dir / f"{stem}_raw_bggr16.tiff"
            Image.fromarray(np.ascontiguousarray(raw), mode="I;16").save(
                raw_path, format="TIFF", compression="tiff_deflate",
                tiffinfo=tiff_info(
                    f"IMX296 BGGR RAW; actual exposure {exposure_us} us; "
                    "RAW10 codes left-shifted by 6; exact measurement"
                ),
            )
            physical_path = calibrated_dir / f"{stem}_radiance_bggr_float32.tiff"
            Image.fromarray(radiance, mode="F").save(
                physical_path, format="TIFF", compression="tiff_deflate",
                tiffinfo=tiff_info(
                    f"IMX296 BGGR linear radiance; actual exposure {exposure_us} us; "
                    "float32 RAW10 counts/second; virtual-dark subtracted"
                ),
            )
            normalized = np.clip(radiance / white, 0.0, 1.0)
            view = np.rint(normalized * 65535.0).astype(np.uint16)
            view_path = view_dir / f"{stem}_radiance_bggr_linear16.tiff"
            Image.fromarray(view, mode="I;16").save(
                view_path, format="TIFF", compression="tiff_deflate",
                tiffinfo=tiff_info(
                    f"IMX296 BGGR linearly normalized radiance view; actual exposure {exposure_us} us; "
                    f"common white {white:.9g} counts/second; no gamma or tone curve"
                ),
            )
            colour = demosaic_bggr(radiance)
            colour_normalized, colour_min, colour_max = percentile_minmax(colour)
            colour16 = np.rint(colour_normalized * 65535.0).astype(np.uint16)
            colour16 = np.ascontiguousarray(np.rot90(colour16, 2))
            colour_path = colour_preview_dir / f"{stem}_radiance_rgb_minmax16.tiff"
            write_rgb48_tiff(colour_path, colour16)
            records.append({"actual_exposure_us": exposure_us,
                            "frame_index": frame_index,
                            "raw_tiff": str(raw_path.relative_to(args.bracket)),
                            "physical_radiance_tiff": str(physical_path.relative_to(args.bracket)),
                            "linear_view_tiff": str(view_path.relative_to(args.bracket)),
                            "colour_minmax_preview_tiff": str(colour_path.relative_to(args.bracket)),
                            "colour_preview_input_min": colour_min,
                            "colour_preview_input_max": colour_max})
        raw_file.close()

    rgb = demosaic_bggr(stack)
    rgb_normalized = np.clip(rgb / white, 0.0, 1.0)
    rgb16 = np.rint(rgb_normalized * 65535.0).astype(np.uint16)
    # Registered camera orientation is 180 degrees.
    rgb16 = np.ascontiguousarray(np.rot90(rgb16, 2))
    merged_path = stack_dir / "merged_linear_rgb16.tiff"
    write_rgb48_tiff(merged_path, rgb16)
    merged_minmax, merged_min, merged_max = percentile_minmax(rgb)
    merged_minmax16 = np.rint(merged_minmax * 65535.0).astype(np.uint16)
    merged_minmax16 = np.ascontiguousarray(np.rot90(merged_minmax16, 2))
    merged_minmax_path = stack_dir / "merged_radiance_rgb_minmax16.tiff"
    write_rgb48_tiff(merged_minmax_path, merged_minmax16)
    output = {"global_linear_white_counts_per_second": white,
              "white_percentile": args.white_percentile,
              "merged_linear_rgb16": str(merged_path.relative_to(args.bracket)),
              "merged_minmax_rgb16": str(merged_minmax_path.relative_to(args.bracket)),
              "merged_minmax_input_min": merged_min,
              "merged_minmax_input_max": merged_max,
              "minmax_discarded_tail_percent_each": 0.01,
              "stills": records}
    (args.bracket / "tiff_exports.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"raw_tiffs": len(records), "calibrated_tiffs": len(records),
                      "linear_view_tiffs": len(records),
                      "colour_minmax_previews": len(records),
                      "merged": str(merged_path),
                      "merged_minmax": str(merged_minmax_path),
                      "white": white}, indent=2))


if __name__ == "__main__":
    main()
