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
