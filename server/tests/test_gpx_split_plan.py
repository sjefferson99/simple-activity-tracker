"""parse_split_plan (issue #100): the full split plan read from the uploaded
GPX's root <extensions> — sat:split_target/sat:split_plan/sat:split_targets_as,
written alongside the unchanged sat:split_type/sat:split_value (see mobile's
RunGpxLog and docs/SPLIT-TARGETS-PLAN.md §4.2 / SPLIT-TARGETS-SERVER-PLAN.md)."""

from app.analysis.gpx_parser import SplitPlanData, parse_split_plan

_NS = "https://simple-activity-tracker.local/gpx-extensions"

_TRK = (
    b'<trk><trkseg><trkpt lat="0" lon="0"><time>2026-01-01T00:00:00Z</time></trkpt>'
    b'<trkpt lat="0.001" lon="0"><time>2026-01-01T00:00:01Z</time></trkpt>'
    b"</trkseg></trk>"
)


def _gpx(extensions_xml: bytes) -> bytes:
    return (
        b'<?xml version="1.0"?><gpx version="1.1" '
        b'xmlns:sat="' + _NS.encode() + b'">' + extensions_xml + _TRK + b"</gpx>"
    )


def test_plain_split_type_value_yields_a_rolling_plan_with_no_target() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>distance_km</sat:split_type>"
        b"<sat:split_value>1</sat:split_value></extensions>"
    )
    assert parse_split_plan(gpx) == SplitPlanData(
        split_type="distance_km", split_value=1, rolling_target_mps=None, custom_splits=[]
    )


def test_rolling_plan_with_a_target() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>distance_km</sat:split_type>"
        b"<sat:split_value>1</sat:split_value>"
        b"<sat:split_target>2.222</sat:split_target>"
        b"<sat:split_targets_as>speed</sat:split_targets_as></extensions>"
    )
    plan = parse_split_plan(gpx)
    assert plan is not None
    assert plan.rolling_target_mps == 2.222
    assert plan.custom_splits == []
    assert plan.targets_as == "speed"
    assert not plan.is_custom


def test_custom_plan_with_mixed_targets() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>time_min</sat:split_type>"
        b"<sat:split_value>1</sat:split_value>"
        b"<sat:split_plan>90@2.222;60@1.667;120</sat:split_plan>"
        b"<sat:split_targets_as>pace</sat:split_targets_as></extensions>"
    )
    plan = parse_split_plan(gpx)
    assert plan is not None
    assert plan.is_custom
    assert plan.custom_splits == [(90.0, 2.222), (60.0, 1.667), (120.0, None)]
    assert plan.rolling_target_mps is None
    assert plan.targets_as == "pace"


def test_targets_as_defaults_to_pace_when_absent() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>distance_km</sat:split_type>"
        b"<sat:split_value>1</sat:split_value></extensions>"
    )
    plan = parse_split_plan(gpx)
    assert plan is not None
    assert plan.targets_as == "pace"


def test_split_plan_present_wins_over_split_target() -> None:
    """Shouldn't happen from the real app (mobile writes at most one of the
    two — see SplitPlan.isCustom), but a custom plan is unambiguous evidence
    of the user's intent, so it takes priority over a stray rolling target
    rather than silently merging the two."""
    gpx = _gpx(
        b"<extensions><sat:split_type>distance_km</sat:split_type>"
        b"<sat:split_value>1</sat:split_value>"
        b"<sat:split_target>3.0</sat:split_target>"
        b"<sat:split_plan>400@3;200</sat:split_plan></extensions>"
    )
    plan = parse_split_plan(gpx)
    assert plan is not None
    assert plan.is_custom
    assert plan.rolling_target_mps is None


def test_malformed_split_plan_entry_falls_back_to_no_plan_at_all() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>distance_km</sat:split_type>"
        b"<sat:split_value>1</sat:split_value>"
        b"<sat:split_plan>400@3;notanumber</sat:split_plan></extensions>"
    )
    plan = parse_split_plan(gpx)
    assert plan is not None
    assert plan.custom_splits == []
    assert not plan.is_custom


def test_non_positive_target_in_split_plan_is_malformed() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>distance_km</sat:split_type>"
        b"<sat:split_value>1</sat:split_value>"
        b"<sat:split_plan>400@0;200</sat:split_plan></extensions>"
    )
    plan = parse_split_plan(gpx)
    assert plan is not None
    assert plan.custom_splits == []


def test_non_positive_rolling_target_is_ignored() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>distance_km</sat:split_type>"
        b"<sat:split_value>1</sat:split_value>"
        b"<sat:split_target>0</sat:split_target></extensions>"
    )
    plan = parse_split_plan(gpx)
    assert plan is not None
    assert plan.rolling_target_mps is None


def test_returns_none_when_no_valid_base_split_preference() -> None:
    gpx = _gpx(b"<extensions><sat:split_plan>400@3;200</sat:split_plan></extensions>")
    assert parse_split_plan(gpx) is None


def test_returns_none_for_unparseable_gpx() -> None:
    assert parse_split_plan(b"this is not gpx") is None
