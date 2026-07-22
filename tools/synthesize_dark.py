#!/usr/bin/env python3
"""Interpolate a virtual float32 dark master for an arbitrary exposure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("exposure_us", type=int)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    manifest = json.loads((args.library / "dark_library.json").read_text())
    points = sorted(manifest["points"], key=lambda p: p["actual_exposure_us"])
    lower = max((p for p in points if p["actual_exposure_us"] <= args.exposure_us),
                key=lambda p: p["actual_exposure_us"], default=None)
    upper = min((p for p in points if p["actual_exposure_us"] >= args.exposure_us),
                key=lambda p: p["actual_exposure_us"], default=None)
    if lower is None or upper is None:
        raise ValueError("requested exposure is outside the calibrated range")

    lo = np.fromfile(args.library / lower["master"], dtype="<f4").reshape(1088, 1456)
    if lower is upper:
        result = lo
    else:
        hi = np.fromfile(args.library / upper["master"], dtype="<f4").reshape(1088, 1456)
        weight = ((args.exposure_us - lower["actual_exposure_us"]) /
                  (upper["actual_exposure_us"] - lower["actual_exposure_us"]))
        result = lo + (hi - lo) * weight
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.astype("<f4").tofile(args.output)


if __name__ == "__main__":
    main()
