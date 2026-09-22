"""Display formatting for templates — mirrors mobile/lib/core/units so the
web UI shows the same km/h-and-min/km convention as the app (see CLAUDE.md
"Conventions")."""


def format_kmh(speed_mps: float | None) -> str:
    if speed_mps is None:
        return "—"
    return f"{speed_mps * 3.6:.1f} km/h"


def format_distance_km(meters: float | None) -> str:
    if meters is None:
        return "—"
    return f"{meters / 1000:.2f} km"


def format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    total = round(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_pace(speed_mps: float | None) -> str:
    """min/km, the app's secondary unit — see mobile/lib/core/units."""
    if speed_mps is None or speed_mps <= 0:
        return "—"
    seconds_per_km = 1000 / speed_mps
    minutes, secs = divmod(round(seconds_per_km), 60)
    return f"{minutes}:{secs:02d} /km"


def format_split_target(target_speed_mps: float | None, targets_as: str | None) -> str:
    """A split's target, in whichever unit the phone's Splits screen was set
    to (issue #100) — "speed" as km/h (format_kmh), anything else (including
    None, an older activity with no explicit preference) as pace, mirroring
    mobile's own pace-first default (docs/SPLIT-TARGETS-PLAN.md D4)."""
    if target_speed_mps is None:
        return "—"
    return format_kmh(target_speed_mps) if targets_as == "speed" else format_pace(target_speed_mps)


# Mirrors splitVerdict's tolerance (app/analysis/v1.py's
# _SPLIT_TARGET_TOLERANCE, mobile's splitTargetTolerance) — duplicated here
# rather than imported so the on/off-target decision below uses the exact
# same ±5% ratio the cell's own colour class (verdict) was computed with.
# Using a separate near-zero absolute threshold (the original version of
# this function) let the two disagree: a split well inside the 5% band
# would render green (on target) but still show a nonzero correction arrow.
_SPEED_DELTA_TOLERANCE = 0.05


_SPLIT_TYPE_LABELS = {
    "distance_km": "km",
    "distance_mi": "mi",
    "time_min": "min",
}


def format_split_plan_summary(plan: dict[str, object]) -> str:
    """A one-line human summary of a saved SplitConfig's plan (issue #126),
    e.g. "Rolling, every 1 km @ 5:00 /km" or "Custom, 6 splits" — used on the
    split configs list page. Mirrors the equivalent summary mobile's home
    screen shows for the current plan (docs/SPLIT-TARGETS-PLAN.md §5.4)."""
    split_type = str(plan.get("split_type") or "distance_km")
    unit = _SPLIT_TYPE_LABELS.get(split_type, split_type)
    custom_splits = plan.get("custom_splits") or []
    if custom_splits:
        count = len(custom_splits) if isinstance(custom_splits, list) else 0
        return f"Custom, {count} split{'s' if count != 1 else ''}"

    split_value = plan.get("split_value") or 1
    rolling_target_mps_raw = plan.get("rolling_target_mps")
    targets_as = plan.get("targets_as")
    base = f"Rolling, every {split_value} {unit}"
    if rolling_target_mps_raw is None:
        return base
    rolling_target_mps = (
        rolling_target_mps_raw
        if isinstance(rolling_target_mps_raw, int | float)
        else float(str(rolling_target_mps_raw))
    )
    target_str = format_split_target(
        float(rolling_target_mps), str(targets_as) if targets_as else None
    )
    return f"{base} @ {target_str}"


def format_speed_delta(
    avg_speed_mps: float | None, target_speed_mps: float | None, targets_as: str | None
) -> str:
    """The correction the runner must make to hit target_speed_mps, mirroring
    mobile's formatSpeedDelta (mobile/lib/core/units/units.dart) and issue
    #99 D7: the arrow points the way to go, not the way they were off — too
    fast means slow down (▼), too slow means speed up (▲). Empty string when
    there's nothing to show (no target, or no avg yet)."""
    if target_speed_mps is None or avg_speed_mps is None or avg_speed_mps <= 0:
        return ""
    ratio = avg_speed_mps / target_speed_mps
    if 1 - _SPEED_DELTA_TOLERANCE <= ratio <= 1 + _SPEED_DELTA_TOLERANCE:
        return "on target"
    too_fast = ratio > 1
    if targets_as == "speed":
        delta_kmh = abs(avg_speed_mps - target_speed_mps) * 3.6
        arrow = "▼" if too_fast else "▲"
        return f"{arrow} {delta_kmh:.1f} km/h {'fast' if too_fast else 'slow'}"
    # Pace: a *faster* runner has a *lower* seconds-per-km number, so "fast"
    # (too fast, slow down) corresponds to a negative pace delta.
    avg_pace_s = 1000 / avg_speed_mps
    target_pace_s = 1000 / target_speed_mps
    delta_s = round(abs(avg_pace_s - target_pace_s))
    arrow = "▼" if too_fast else "▲"
    return f"{arrow} {delta_s} s/km {'fast' if too_fast else 'slow'}"
