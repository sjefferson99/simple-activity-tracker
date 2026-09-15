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
    if targets_as == "speed":
        delta_kmh = (avg_speed_mps - target_speed_mps) * 3.6
        if abs(delta_kmh) < 0.05:
            return "on target"
        arrow = "▼" if delta_kmh > 0 else "▲"
        return f"{arrow} {abs(delta_kmh):.1f} km/h {'fast' if delta_kmh > 0 else 'slow'}"
    # Pace: a *faster* runner has a *lower* seconds-per-km number, so "fast"
    # (too fast, slow down) corresponds to a negative pace delta.
    avg_pace_s = 1000 / avg_speed_mps
    target_pace_s = 1000 / target_speed_mps
    delta_s = round(avg_pace_s - target_pace_s)
    if delta_s == 0:
        return "on target"
    arrow = "▼" if delta_s < 0 else "▲"
    return f"{arrow} {abs(delta_s)} s/km {'fast' if delta_s < 0 else 'slow'}"
