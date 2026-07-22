"""Load the camera-independent project configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from .exposure import BracketPlan, build_bracket


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    module_name: str
    expected_linux_sensor: str
    bracket: BracketPlan
    requirements: dict[str, bool]


def load_project_config(path: str | Path) -> ProjectConfig:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    project = raw["project"]
    bracket = raw["bracket"]
    capture = raw["capture"]

    return ProjectConfig(
        name=str(project["name"]),
        module_name=str(project["module_name"]),
        expected_linux_sensor=str(project["expected_linux_sensor"]),
        bracket=build_bracket(
            bracket["shutter_angles_deg"],
            float(project["reference_fps"]),
            float(bracket["analogue_gain"]),
        ),
        requirements={key: bool(value) for key, value in capture.items()},
    )

