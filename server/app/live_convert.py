"""Turning a live session into an activity (issue #130 phase D,
docs/LIVE-TRACKING-PLAN.md §4): for when the phone died, or never got its
final upload through, but the server already holds the route.

The GPX is written in the same shape as the phone's own RunGpxLog (same
`sat:` extensions, values and segments), so everything downstream (the
analyzer, the split-plan parser, download, export) treats a converted
activity exactly like an uploaded one. Only numbers and fixed vocabulary
values are ever written into it; nothing here is user-supplied text.
"""

from datetime import UTC, datetime
from typing import Any

from app.models.live import LivePoint, LiveSession

_SAT_NS = "https://simple-activity-tracker.local/gpx-extensions"
# Mirrors mobile's ActivityMode.supportsSplits: a split plan only belongs in a
# running or walking activity's GPX (issue #99 D8 / #109).
_SPLIT_ACTIVITY_TYPES = ("running", "walking")
_SPLIT_TYPES = ("distance_km", "distance_mi", "time_min")


def _num(value: float) -> str:
    """Like mobile's SplitPlan._num: no trailing ".0" on whole numbers."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _time(value: datetime) -> str:
    value = value.astimezone(UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def _split_extensions(live: LiveSession) -> list[str]:
    plan = live.split_plan
    if not plan or live.activity_type not in _SPLIT_ACTIVITY_TYPES:
        return []
    split_type = plan.get("split_type")
    split_value = plan.get("split_value")
    if split_type not in _SPLIT_TYPES or not isinstance(split_value, int) or split_value <= 0:
        return []
    lines = [
        f"    <sat:split_type>{split_type}</sat:split_type>",
        f"    <sat:split_value>{split_value}</sat:split_value>",
    ]
    custom = plan.get("custom_splits") or []
    rolling_target = plan.get("rolling_target_mps")
    if custom:
        entries = []
        for size, target in custom:
            entries.append(f"{_num(size)}@{_num(target)}" if target is not None else _num(size))
        lines.append(f"    <sat:split_plan>{';'.join(entries)}</sat:split_plan>")
    elif isinstance(rolling_target, int | float) and rolling_target > 0:
        lines.append(f"    <sat:split_target>{_num(rolling_target)}</sat:split_target>")
    targets_as = "speed" if plan.get("targets_as") == "speed" else "pace"
    lines.append(f"    <sat:split_targets_as>{targets_as}</sat:split_targets_as>")
    return lines


def _point_xml(point: LivePoint) -> list[str]:
    lines = [f'      <trkpt lat="{_num(point.lat)}" lon="{_num(point.lon)}">']
    if point.ele is not None:
        lines.append(f"        <ele>{_num(point.ele)}</ele>")
    lines.append(f"        <time>{_time(point.t)}</time>")
    lines.append("        <extensions>")
    if point.accuracy is not None:
        lines.append(f"          <sat:accuracy>{_num(point.accuracy)}</sat:accuracy>")
    lines.append(
        f"          <sat:has_accuracy>{'true' if point.accuracy is not None else 'false'}"
        "</sat:has_accuracy>"
    )
    if point.speed is not None:
        lines.append(f"          <sat:speed>{_num(point.speed)}</sat:speed>")
    lines.append(
        f"          <sat:has_speed>{'true' if point.speed is not None else 'false'}</sat:has_speed>"
    )
    lines.append("        </extensions>")
    lines.append("      </trkpt>")
    return lines


def live_session_gpx(live: LiveSession, points: list[LivePoint]) -> bytes:
    """GPX 1.1 bytes for the session's points, in index order, one track
    segment per live `segment` (each resume after a pause starts a new one,
    like the phone's own file)."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" '
        f'xmlns:sat="{_SAT_NS}" version="1.1" creator="Simple Activity Tracker (live)">',
    ]
    extensions = _split_extensions(live)
    if extensions:
        lines += ["  <extensions>", *extensions, "  </extensions>"]
    lines.append("  <trk>")
    current_segment: int | None = None
    for point in sorted(points, key=lambda p: p.idx):
        if point.segment != current_segment:
            if current_segment is not None:
                lines.append("    </trkseg>")
            lines.append("    <trkseg>")
            current_segment = point.segment
        lines += _point_xml(point)
    if current_segment is not None:
        lines.append("    </trkseg>")
    lines += ["  </trk>", "</gpx>", ""]
    return "\n".join(lines).encode("utf-8")


def live_session_summary(live: LiveSession, ended_at: datetime) -> dict[str, Any]:
    """A client_summary in the upload shape (ActivitySummary), from the
    phone's last reported numbers. Zeros when the phone never sent any."""
    metrics = live.latest_metrics or {}
    splits = [
        {
            key: split[key]
            for key in (
                "index",
                "duration_seconds",
                "avg_speed_mps",
                "distance_m",
                "target_speed_mps",
            )
            if key in split
        }
        for split in metrics.get("splits") or []
        if isinstance(split, dict)
    ]
    return {
        "client_activity_id": live.client_activity_id,
        "activity_type": live.activity_type,
        "started_at": live.started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "moving_seconds": float(metrics.get("moving_seconds") or 0.0),
        "distance_meters": float(metrics.get("distance_meters") or 0.0),
        "avg_speed_mps": metrics.get("avg_speed_mps"),
        "splits": splits,
        "source": {"platform": "live", "app_version": ""},
    }
