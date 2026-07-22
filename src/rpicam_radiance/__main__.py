"""Command-line entry point."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json

from .config import load_project_config


def main() -> None:
    parser = argparse.ArgumentParser(prog="rpicam_radiance")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="print the resolved bracket plan")
    plan_parser.add_argument("config")
    args = parser.parse_args()

    config = load_project_config(args.config)
    output = {
        "project": {
            "name": config.name,
            "module_name": config.module_name,
            "expected_linux_sensor": config.expected_linux_sensor,
        },
        "capture_requirements": config.requirements,
        "bracket": config.bracket.as_dict(),
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

