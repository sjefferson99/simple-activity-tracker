"""Form parsing for the split configs web editor (issue #126) — converts the
human-entered fields on split_config_form.html (pace as "mm:ss", speed as a
plain km/h number, sizes as decimal km/mi or "mm:ss") into the SplitPlanIn
shape the API/repository layer expects (m/s, metres/seconds). Kept separate
from app/web/formatting.py, which is output-only (model → display string);
this module is the reverse direction, and is web-only — the JSON API takes
SplitPlanIn's fields directly in their stored units, no parsing needed
there.

Mirrors mobile's core/units/units.dart parsing helpers (parsePace/
parseMinSec) closely enough to give the same acceptance behaviour, but is
not a port — this only needs to handle what an HTML form can submit.
"""

import re

from app.validation import ValidationFailedError

_MM_SS_RE = re.compile(r"^(\d+):([0-5]?\d)$")

_METERS_PER_MILE = 1609.344


class SplitConfigFormError(ValidationFailedError):
    """A human-readable error for one named form field — callers attach
    `field` to know which input to blame in the re-rendered form."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def parse_mm_ss(raw: str, *, field: str) -> float:
    """ "mm:ss" or a bare number of seconds/minutes — mirrors mobile's
    parseMinSec(bareNumberAsSeconds: false) default (a bare number without a
    colon is minutes, e.g. "5" -> 300s), used for time-kind split sizes."""
    stripped = raw.strip()
    match = _MM_SS_RE.match(stripped)
    if match:
        minutes, seconds = int(match.group(1)), int(match.group(2))
        return float(minutes * 60 + seconds)
    try:
        return float(stripped) * 60.0
    except ValueError:
        raise SplitConfigFormError(field, "Enter a duration as minutes or mm:ss") from None


def parse_pace_to_mps(raw: str, *, field: str, meters_per_unit: float) -> float:
    """ "mm:ss" pace per km/mi -> m/s. meters_per_unit is 1000 for km, the
    mile constant for mi (i.e. whatever the plan's own distance unit is —
    see docs/SPLIT-CONFIGS-PLAN.md; targets are always stored as m/s
    regardless of the unit they were entered in, same as mobile's
    SplitPlan)."""
    stripped = raw.strip()
    match = _MM_SS_RE.match(stripped)
    if not match:
        raise SplitConfigFormError(field, "Enter a pace as mm:ss")
    minutes, seconds = int(match.group(1)), int(match.group(2))
    total_seconds = minutes * 60 + seconds
    if total_seconds <= 0:
        raise SplitConfigFormError(field, "Pace must be greater than zero")
    return meters_per_unit / total_seconds


def parse_kmh_to_mps(raw: str, *, field: str) -> float:
    stripped = raw.strip()
    try:
        kmh = float(stripped)
    except ValueError:
        raise SplitConfigFormError(field, "Enter a speed in km/h") from None
    if kmh <= 0:
        raise SplitConfigFormError(field, "Speed must be greater than zero")
    return kmh / 3.6


def parse_target_to_mps(raw: str, *, field: str, targets_as: str, distance_unit: str) -> float:
    """Dispatches to parse_pace_to_mps or parse_kmh_to_mps per the form's
    "targets as" choice. distance_unit is "km" or "mi" (irrelevant when
    targets_as == "speed", which is always km/h)."""
    if targets_as == "speed":
        return parse_kmh_to_mps(raw, field=field)
    meters_per_unit = _METERS_PER_MILE if distance_unit == "mi" else 1000.0
    return parse_pace_to_mps(raw, field=field, meters_per_unit=meters_per_unit)


def parse_distance_size_to_meters(raw: str, *, field: str, distance_unit: str) -> float:
    """A custom distance split's size, entered as decimal km/mi."""
    stripped = raw.strip()
    try:
        value = float(stripped)
    except ValueError:
        raise SplitConfigFormError(field, "Enter a distance") from None
    if value <= 0:
        raise SplitConfigFormError(field, "Distance must be greater than zero")
    meters_per_unit = _METERS_PER_MILE if distance_unit == "mi" else 1000.0
    return value * meters_per_unit
