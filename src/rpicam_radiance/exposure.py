"""Shutter-angle calculations independent of camera hardware."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from math import log2
from typing import Iterable


MICROSECONDS_PER_SECOND = Decimal("1000000")
FULL_CIRCLE_DEGREES = Decimal("360")


@dataclass(frozen=True)
class Exposure:
    index: int
    shutter_angle_deg: float
    exposure_us: int
    analogue_gain: float

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True)
class BracketPlan:
    reference_fps: float
    frame_period_us: float
    exposures: tuple[Exposure, ...]

    @property
    def integration_total_us(self) -> int:
        return sum(exposure.exposure_us for exposure in self.exposures)

    @property
    def angle_total_deg(self) -> float:
        return sum(exposure.shutter_angle_deg for exposure in self.exposures)

    @property
    def exposure_span_stops(self) -> float:
        values = [exposure.exposure_us for exposure in self.exposures]
        return log2(max(values) / min(values))

    @property
    def raw_frames_per_reference_second(self) -> float:
        return self.reference_fps * len(self.exposures)

    def as_dict(self) -> dict[str, object]:
        return {
            "reference_fps": self.reference_fps,
            "frame_period_us": self.frame_period_us,
            "angle_total_deg": self.angle_total_deg,
            "integration_total_us": self.integration_total_us,
            "exposure_span_stops": self.exposure_span_stops,
            "raw_frames_per_reference_second": self.raw_frames_per_reference_second,
            "warning": (
                "Shutter angles define exposure times only; they do not guarantee "
                "the reference HDR cadence. Sensor frame duration, readout, control "
                "latency, and rejected transition frames must be measured."
            ),
            "exposures": [exposure.as_dict() for exposure in self.exposures],
        }


def shutter_angle_to_exposure_us(angle_deg: float, reference_fps: float) -> int:
    """Convert a shutter angle to the nearest whole microsecond."""

    angle = Decimal(str(angle_deg))
    fps = Decimal(str(reference_fps))
    if not Decimal("0") < angle <= FULL_CIRCLE_DEGREES:
        raise ValueError("shutter angle must be greater than 0 and at most 360 degrees")
    if fps <= 0:
        raise ValueError("reference_fps must be positive")

    exposure_us = MICROSECONDS_PER_SECOND * angle / (FULL_CIRCLE_DEGREES * fps)
    return int(exposure_us.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def build_bracket(
    angles_deg: Iterable[float],
    reference_fps: float,
    analogue_gain: float = 1.0,
) -> BracketPlan:
    """Build and validate an ordered shutter-angle bracket."""

    angles = tuple(float(angle) for angle in angles_deg)
    if not angles:
        raise ValueError("at least one shutter angle is required")
    if any(right <= left for left, right in zip(angles, angles[1:])):
        raise ValueError("shutter angles must be strictly increasing")
    if analogue_gain <= 0:
        raise ValueError("analogue_gain must be positive")

    exposures = tuple(
        Exposure(
            index=index,
            shutter_angle_deg=angle,
            exposure_us=shutter_angle_to_exposure_us(angle, reference_fps),
            analogue_gain=float(analogue_gain),
        )
        for index, angle in enumerate(angles)
    )
    return BracketPlan(
        reference_fps=float(reference_fps),
        frame_period_us=float(MICROSECONDS_PER_SECOND / Decimal(str(reference_fps))),
        exposures=exposures,
    )

