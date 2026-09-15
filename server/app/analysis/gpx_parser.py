from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

import gpxpy
import gpxpy.gpx

from app.analysis.track import Point, Segment, Track


class GpxParseError(Exception):
    pass


class GpxNoTrackPointsError(GpxParseError):
    """Raised specifically when parsing succeeded but the file has zero
    usable (timestamped) points — distinct from a malformed/corrupt file, so
    callers that care about that distinction (e.g. the Strava importer,
    which treats a genuinely GPS-less activity as a normal skip rather than
    a failure) can catch this subclass specifically."""


_EXTENSIONS_NS = "https://simple-activity-tracker.local/gpx-extensions"
_ACCURACY_TAG = f"{{{_EXTENSIONS_NS}}}accuracy"
_HAS_ACCURACY_TAG = f"{{{_EXTENSIONS_NS}}}has_accuracy"


def _point_accuracy_m(gpx_point: gpxpy.gpx.GPXTrackPoint) -> float | None:
    """The point's sat:accuracy extension value, or None if absent/unmeasured
    (sat:has_accuracy is "false") or unparseable — same "missing is not the
    same as good" treatment mobile's own MetricsEngine gives this field."""
    accuracy_text: str | None = None
    has_accuracy = True
    for element in gpx_point.extensions:
        tag = getattr(element, "tag", None)
        if tag == _ACCURACY_TAG:
            accuracy_text = element.text
        elif tag == _HAS_ACCURACY_TAG:
            has_accuracy = (element.text or "").strip().lower() == "true"

    if not has_accuracy or accuracy_text is None:
        return None
    try:
        return float(accuracy_text)
    except ValueError:
        return None


def parse_gpx(data: bytes) -> Track:
    """Parses GPX bytes into a Track. Points with no timestamp are dropped —
    a Track without complete timing can't support any of the analysis this
    module does (splits, speed, moving time). Raises GpxParseError on
    anything gpxpy itself rejects, or if there's not a single usable point,
    so callers can map both to a 400 without inspecting gpxpy's exceptions.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GpxParseError("GPX file is not valid UTF-8") from exc

    # GPX never legitimately needs a DOCTYPE or a custom entity declaration —
    # reject both outright rather than relying solely on the stdlib expat
    # parser's own protections (billion-laughs is blocked in modern Python,
    # but external entity resolution history is worth not depending on). See
    # R8 in docs/SERVER-PRODUCTION-PLAN.md.
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise GpxParseError("GPX file must not contain a DOCTYPE or ENTITY declaration")

    try:
        gpx = gpxpy.parse(text)
    except Exception as exc:  # gpxpy raises its own GPXException plus XML errors
        raise GpxParseError(f"Could not parse GPX: {exc}") from exc

    segments: list[Segment] = []
    for gpx_track in gpx.tracks:
        for gpx_segment in gpx_track.segments:
            points = [
                Point(
                    lat=p.latitude,
                    lon=p.longitude,
                    ele=p.elevation,
                    time=_as_utc(p.time),
                    accuracy_m=_point_accuracy_m(p),
                )
                for p in gpx_segment.points
                if p.time is not None
            ]
            if points:
                segments.append(Segment(points=points))

    track = Track(segments=segments)
    if track.point_count == 0:
        raise GpxNoTrackPointsError("GPX file has no timestamped track points")
    return track


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def guess_device_name(data: bytes) -> str | None:
    """Best-effort device name for a manually-uploaded GPX, read from the
    root <gpx creator="..."> attribute (what Garmin/most standalone trackers
    set — e.g. "Foretrex 401") or the <metadata><author><name> as a fallback.
    Never raises: this is only ever used to prefill an editable form field,
    so a file gpxpy can't even parse just yields no suggestion rather than
    failing the whole upload (parse_gpx already does the real validation).
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        return None
    try:
        gpx = gpxpy.parse(text)
    except Exception:
        return None

    creator = (gpx.creator or "").strip()
    if creator:
        return creator
    author = (gpx.author_name or "").strip()
    return author or None


_SPLIT_EXTENSIONS_NS = "https://simple-activity-tracker.local/gpx-extensions"
_VALID_SPLIT_TYPES = {"distance_km", "distance_mi", "time_min"}


def parse_split_preference(data: bytes) -> tuple[str, int] | None:
    """Best-effort split preference from the uploaded GPX's root
    <extensions> (written by mobile — see
    mobile/lib/core/files/run_gpx_log.dart's sat:split_type/sat:split_value).
    Returns None (never raises) for any GPX with no/invalid/partial split
    extensions — an old activity, a manually-uploaded file, or a malformed
    value — so callers fall back to AnalyzerV1's own default rather than
    failing the upload.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        return None
    try:
        gpx = gpxpy.parse(text)
    except Exception:
        return None

    split_type: str | None = None
    split_value_raw: str | None = None
    for element in gpx.extensions:
        tag = getattr(element, "tag", None)
        if tag == f"{{{_SPLIT_EXTENSIONS_NS}}}split_type":
            split_type = (element.text or "").strip()
        elif tag == f"{{{_SPLIT_EXTENSIONS_NS}}}split_value":
            split_value_raw = (element.text or "").strip()

    if split_type not in _VALID_SPLIT_TYPES or split_value_raw is None:
        return None
    try:
        split_value = int(split_value_raw)
    except ValueError:
        return None
    if split_value <= 0:
        return None

    return split_type, split_value


@dataclass(frozen=True)
class SplitPlanData:
    """The phone's split plan (issue #99/#100), parsed from the GPX's
    sat:split_target/sat:split_plan/sat:split_targets_as extensions —
    written alongside the unchanged sat:split_type/sat:split_value (see
    mobile's RunGpxLog and docs/SPLIT-TARGETS-PLAN.md §4.2). Mirrors
    mobile's SplitPlan: split_type/split_value are the same rolling
    base every activity already has; rolling_target_mps and custom_splits
    are mutually exclusive (a custom plan's own per-split targets, or one
    target applied to every rolling split — never both, matching mobile's
    SplitPlan.isCustom split between rollingTargetSpeedMps and
    customSplits)."""

    split_type: str
    split_value: int
    rolling_target_mps: float | None
    # (size, target) pairs, in order, splits 1..N of a custom plan. Size is
    # metres for a distance split_type, seconds for time_min. Empty for a
    # rolling plan (mirrors mobile's SplitPlan.customSplits).
    custom_splits: list[tuple[float, float | None]] = field(default_factory=list)
    targets_as: Literal["pace", "speed"] = "pace"

    @property
    def is_custom(self) -> bool:
        return bool(self.custom_splits)


def _parse_custom_splits(raw: str) -> list[tuple[float, float | None]] | None:
    """Parses a sat:split_plan value ("size@target;size@target;size") into
    (size, target) pairs, or None if any entry is malformed — a partially
    unparseable plan is treated as entirely absent rather than silently
    dropping just the bad entry (see docs/SPLIT-TARGETS-SERVER-PLAN.md §2)."""
    entries = raw.split(";")
    if not entries or any(not e for e in entries):
        return None
    result: list[tuple[float, float | None]] = []
    for entry in entries:
        if "@" in entry:
            size_text, target_text = entry.split("@", 1)
            try:
                size = float(size_text)
                target: float | None = float(target_text)
            except ValueError:
                return None
        else:
            try:
                size = float(entry)
            except ValueError:
                return None
            target = None
        if size <= 0 or (target is not None and target <= 0):
            return None
        result.append((size, target))
    return result


def parse_split_plan(data: bytes) -> SplitPlanData | None:
    """Best-effort split plan from the uploaded GPX's root <extensions>
    (issue #100 — see mobile's RunGpxLog and docs/SPLIT-TARGETS-PLAN.md
    §4.2). Returns None (never raises) whenever parse_split_preference
    itself would — no/invalid split_type/split_value — since a plan without
    a valid base preference makes no sense. sat:split_target/sat:split_plan/
    sat:split_targets_as are all optional on top of that: a GPX with none of
    them still yields a SplitPlanData (rolling, no target, targets_as
    defaulting to "pace") so callers have one code path rather than having
    to special-case "old GPX with no plan extensions at all"."""
    base = parse_split_preference(data)
    if base is None:
        return None
    split_type, split_value = base

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        return None
    try:
        gpx = gpxpy.parse(text)
    except Exception:
        return None

    target_raw: str | None = None
    plan_raw: str | None = None
    targets_as_raw: str | None = None
    for element in gpx.extensions:
        tag = getattr(element, "tag", None)
        if tag == f"{{{_SPLIT_EXTENSIONS_NS}}}split_target":
            target_raw = (element.text or "").strip()
        elif tag == f"{{{_SPLIT_EXTENSIONS_NS}}}split_plan":
            plan_raw = (element.text or "").strip()
        elif tag == f"{{{_SPLIT_EXTENSIONS_NS}}}split_targets_as":
            targets_as_raw = (element.text or "").strip()

    custom_splits: list[tuple[float, float | None]] = []
    rolling_target_mps: float | None = None
    if plan_raw:
        parsed = _parse_custom_splits(plan_raw)
        if parsed is not None:
            custom_splits = parsed
    if not custom_splits and target_raw:
        try:
            value = float(target_raw)
        except ValueError:
            value = 0.0
        if value > 0:
            rolling_target_mps = value

    targets_as: Literal["pace", "speed"] = "speed" if targets_as_raw == "speed" else "pace"

    return SplitPlanData(
        split_type=split_type,
        split_value=split_value,
        rolling_target_mps=rolling_target_mps,
        custom_splits=custom_splits,
        targets_as=targets_as,
    )
