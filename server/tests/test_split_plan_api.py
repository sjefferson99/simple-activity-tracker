"""Issue #100: uploading a GPX with a split plan/targets stores it on
Activity.split_plan, the stored analysis honours it, and both are exposed via
the JSON API — end-to-end through the real upload route, not just the
gpx_parser/AnalyzerV1 unit tests."""

import json

from tests.conftest import make_summary

_NS = "https://simple-activity-tracker.local/gpx-extensions"


def _gpx_with_plan(extensions_xml: str, n_points: int = 90) -> bytes:
    """A real (timestamped, moving) track at a constant 5 m/s (below the
    analyzer's running implied-speed cap), with the given <extensions> inner
    XML alongside the always-present split_type/split_value. n_points=90 ->
    ~445m; pass more to cross a full 1km rolling boundary."""
    points = []
    start_lat = 0.0
    lon_per_meter = 1 / 111195
    for i in range(n_points):
        lon = i * 5.0 * lon_per_meter  # 5 m/s steps, 1s apart
        minutes, seconds = divmod(i, 60)
        points.append(
            f'<trkpt lat="{start_lat}" lon="{lon}">'
            f"<time>2026-01-01T00:{minutes:02d}:{seconds:02d}Z</time></trkpt>"
        )
    return (
        f'<?xml version="1.0"?><gpx version="1.1" xmlns:sat="{_NS}">'
        f"<extensions>{extensions_xml}</extensions>"
        f"<trk><trkseg>{''.join(points)}</trkseg></trk></gpx>"
    ).encode()


def test_upload_with_custom_split_plan_stores_and_returns_it(app_client, auth_headers) -> None:
    # Track moves at a constant 5 m/s; a 4 m/s target on the first split
    # means the actual pace beat it (too_fast), a 10 m/s target on the
    # second means the actual pace fell short of it (too_slow).
    gpx = _gpx_with_plan(
        "<sat:split_type>distance_km</sat:split_type>"
        "<sat:split_value>1</sat:split_value>"
        "<sat:split_plan>100@4;200@10</sat:split_plan>"
        "<sat:split_targets_as>speed</sat:split_targets_as>"
    )
    response = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary())},
        files={"gpx": ("activity.gpx", gpx, "application/gpx+xml")},
    )
    assert response.status_code == 201
    body = response.json()

    assert body["split_plan"] == {
        "rolling_target_mps": None,
        "custom_splits": [[100.0, 4.0], [200.0, 10.0]],
        "targets_as": "speed",
    }

    splits = body["analysis"]["result"]["splits"]
    assert len(splits) == 2
    assert splits[0]["distance_m"] == 100.0
    assert splits[0]["target_speed_mps"] == 4.0
    assert splits[0]["verdict"] == "too_fast"
    assert splits[1]["distance_m"] == 200.0
    assert splits[1]["target_speed_mps"] == 10.0
    assert splits[1]["verdict"] == "too_slow"
    assert body["analysis"]["result"]["split_targets_as"] == "speed"


def test_upload_with_rolling_target_stores_and_returns_it(app_client, auth_headers) -> None:
    gpx = _gpx_with_plan(
        "<sat:split_type>distance_km</sat:split_type>"
        "<sat:split_value>1</sat:split_value>"
        "<sat:split_target>4</sat:split_target>",
        n_points=220,  # 220 * 5 m/s ~= 1095m, enough to complete a 1km split
    )
    response = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary())},
        files={"gpx": ("activity.gpx", gpx, "application/gpx+xml")},
    )
    assert response.status_code == 201
    body = response.json()

    assert body["split_plan"] == {
        "rolling_target_mps": 4.0,
        "custom_splits": [],
        "targets_as": "pace",
    }
    splits = body["analysis"]["result"]["splits"]
    assert splits
    for split in splits:
        assert split["target_speed_mps"] == 4.0


def test_upload_with_no_plan_extensions_leaves_split_plan_null(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    response = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary())},
        files={"gpx": ("activity.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["split_plan"] is None
    for split in body["analysis"]["result"]["splits"]:
        assert split["target_speed_mps"] is None
        assert split["verdict"] is None


def test_reslicing_with_explicit_params_drops_the_plan(app_client, auth_headers) -> None:
    """Re-slicing at an explicit size is a deliberate one-off recompute, not
    a request to keep the plan's targets — they only apply to the plan's own
    sizes (issue #100 scope)."""
    gpx = _gpx_with_plan(
        "<sat:split_type>distance_km</sat:split_type>"
        "<sat:split_value>1</sat:split_value>"
        "<sat:split_target>4</sat:split_target>",
        n_points=220,
    )
    upload = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary())},
        files={"gpx": ("activity.gpx", gpx, "application/gpx+xml")},
    )
    activity_id = upload.json()["id"]

    resliced = app_client.get(
        f"/api/v1/activities/{activity_id}/analysis",
        headers=auth_headers,
        params={"split_type": "distance_km", "split_value": 1},
    )
    assert resliced.status_code == 200
    result = resliced.json()["result"]
    assert result["split_targets_as"] is None
    for split in result["splits"]:
        assert split["target_speed_mps"] is None
