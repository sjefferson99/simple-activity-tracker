"""Convert to activity (issue #130 phase D, docs/LIVE-TRACKING-PLAN.md §4):
an unsaved live session becomes a normal activity, and the phone's own
upload, if it arrives later, replaces it in place."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.analysis.gpx_parser import parse_gpx, parse_split_plan
from tests.conftest import (
    HTMX,
    OTHER_USER_PASSWORD,
    bearer_headers,
    create_user,
    make_summary,
    web_login,
)
from tests.test_live import CID, OWNER_EMAIL, OWNER_PASSWORD, _live_session_id, _points, _send

CUSTOM_PLAN = {
    "split_type": "distance_km",
    "split_value": 1,
    "custom_splits": [[400, 3.5], [200, None]],
    "targets_as": "pace",
}


def _start(client, headers, *, activity_type="running", split_plan=None) -> None:
    body: dict = {"activity_type": activity_type, "started_at": "2026-01-01T07:00:00Z"}
    if split_plan is not None:
        body["split_plan"] = split_plan
    assert client.put(f"/api/v1/live/{CID}", headers=headers, json=body).status_code == 200


def _metrics() -> dict:
    return {
        "distance_meters": 2345.0,
        "elapsed_seconds": 700.0,
        "moving_seconds": 690.0,
        "avg_speed_mps": 3.4,
        "splits": [
            {"index": 1, "duration_seconds": 300.0, "avg_speed_mps": 3.33, "distance_m": 1000}
        ],
    }


def _set_last_update(session_id: str, when: datetime) -> None:
    from app.db import get_session_factory
    from app.models.live import LiveSession

    with get_session_factory()() as session:
        live = session.get(LiveSession, session_id)
        assert live is not None
        live.last_update_at = when
        session.commit()


@pytest.fixture
def unsaved(app_client, auth_headers) -> str:
    """The owner's live run: two segments (a pause), a custom split plan and
    the phone's numbers, but no final upload. Returns the session id."""
    _start(app_client, auth_headers, split_plan=CUSTOM_PLAN)
    _send(app_client, auth_headers, 0, _points(0, 30), metrics=_metrics())
    _send(app_client, auth_headers, 30, _points(30, 30, segment=1), metrics=_metrics())
    session_id = _live_session_id()
    web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    return session_id


def _convert(client, session_id):
    return client.post(f"/live/{session_id}/convert", headers=HTMX)


def test_convert_makes_a_normal_activity(app_client, auth_headers, unsaved):
    response = _convert(app_client, unsaved)
    assert response.status_code == 200
    activity_id = response.headers["hx-redirect"].rsplit("/", 1)[1]

    activity = app_client.get(f"/api/v1/activities/{activity_id}", headers=auth_headers).json()
    assert activity["activity_type"] == "running"
    assert activity["client_summary"]["distance_meters"] == 2345.0
    assert activity["client_summary"]["splits"][0]["distance_m"] == 1000
    assert activity["analysis"]["status"] == "done"
    assert activity["split_plan"]["custom_splits"] == [[400.0, 3.5], [200.0, None]]

    gpx = app_client.get(f"/api/v1/activities/{activity_id}/gpx", headers=auth_headers).content
    track = parse_gpx(gpx)
    assert [len(s.points) for s in track.segments] == [30, 30]
    assert track.segments[0].points[0].accuracy_m == 5.0
    plan = parse_split_plan(gpx)
    assert plan is not None and plan.custom_splits == [(400.0, 3.5), (200.0, None)]

    page = app_client.get(f"/activities/{activity_id}")
    assert "Saved from live tracking" in page.text

    from app.db import get_session_factory
    from app.models.live import LivePoint, LiveSession

    with get_session_factory()() as session:
        live = session.get(LiveSession, unsaved)
        assert live is not None
        assert (live.state, live.activity_id) == ("converted", activity_id)
        assert session.query(LivePoint).count() == 0
    # Gone from the owner's "Live and unsaved" list.
    assert f"/live/{unsaved}" not in app_client.get("/").text


def test_the_phone_is_told_to_stop_after_a_convert(app_client, auth_headers, unsaved):
    _convert(app_client, unsaved)
    late = _send(app_client, auth_headers, 60, _points(60, 2))
    assert late.status_code == 410


def test_the_phones_upload_replaces_the_converted_activity_in_place(
    app_client, auth_headers, unsaved, sample_gpx_bytes
):
    activity_id = _convert(app_client, unsaved).headers["hx-redirect"].rsplit("/", 1)[1]
    # The owner tidies it up and shares it before the phone's upload lands.
    viewer = create_user("viewer@example.com", "Vera")
    assert (
        app_client.patch(
            f"/activities/{activity_id}",
            headers=HTMX,
            data={"title": "Lake loop", "notes": "Phone died"},
        ).status_code
        == 200
    )
    app_client.post(f"/activities/{activity_id}/tags", headers=HTMX, data={"name": "race"})
    app_client.post(f"/activities/{activity_id}/shares", headers=HTMX, data={"viewer_id": viewer})

    from app.db import get_session_factory
    from app.models.activity import Activity

    with get_session_factory()() as session:
        old_blob = session.get(Activity, activity_id).gpx_blob_key  # type: ignore[union-attr]

    upload = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary(CID))},
        files={"gpx": ("a.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert upload.status_code == 200
    replaced = upload.json()
    assert replaced["id"] == activity_id
    assert replaced["title"] == "Lake loop"
    assert replaced["notes"] == "Phone died"
    assert [t["name"] for t in replaced["tags"]] == ["race"]
    assert replaced["client_summary"]["distance_meters"] == 3000.0
    assert replaced["source_platform"] == "android"
    assert replaced["analysis"]["status"] == "done"

    gpx = app_client.get(f"/api/v1/activities/{activity_id}/gpx", headers=auth_headers).content
    assert gpx == sample_gpx_bytes

    from app.config import get_settings
    from app.storage.blob_store import LocalFileBlobStore

    store = LocalFileBlobStore(Path(get_settings().data_dir))
    with pytest.raises(FileNotFoundError):
        store.get(old_blob)

    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None and activity.recovered_from_live is False

    # The share survived.
    web_login(app_client, "viewer@example.com", OTHER_USER_PASSWORD)
    assert app_client.get(f"/shared/activities/{activity_id}").status_code == 200

    # A second upload of the same activity is the usual no-op again.
    web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    again = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary(CID))},
        files={"gpx": ("a.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert again.status_code == 200
    assert "Saved from live tracking" not in app_client.get(f"/activities/{activity_id}").text


def test_a_normal_activity_is_never_replaced(app_client, auth_headers, sample_gpx_bytes):
    first = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary(CID))},
        files={"gpx": ("a.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert first.status_code == 201
    other_gpx = sample_gpx_bytes.replace(b"Z</time>", b"Z</time>", 1) + b"\n"
    again = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary(CID))},
        files={"gpx": ("a.gpx", other_gpx, "application/gpx+xml")},
    )
    assert again.status_code == 200
    gpx = app_client.get(
        f"/api/v1/activities/{first.json()['id']}/gpx", headers=auth_headers
    ).content
    assert gpx == sample_gpx_bytes


def test_an_invalid_phone_upload_leaves_the_converted_activity_alone(
    app_client, auth_headers, unsaved
):
    activity_id = _convert(app_client, unsaved).headers["hx-redirect"].rsplit("/", 1)[1]
    bad = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary(CID))},
        files={"gpx": ("a.gpx", b"<gpx>broken", "application/gpx+xml")},
    )
    assert bad.status_code == 400
    page = app_client.get(f"/activities/{activity_id}")
    assert "Saved from live tracking" in page.text
    assert (
        app_client.get(f"/api/v1/activities/{activity_id}/gpx", headers=auth_headers).status_code
        == 200
    )


def test_converting_after_the_upload_already_landed_just_links(
    app_client, auth_headers, unsaved, sample_gpx_bytes
):
    from app.db import get_session_factory
    from app.models.live import LiveSession

    # The upload arrives, but the session link is lost (an old server, say).
    upload = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary(CID))},
        files={"gpx": ("a.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    with get_session_factory()() as session:
        live = session.get(LiveSession, unsaved)
        assert live is not None
        live.activity_id = None
        live.state = "finished"
        session.commit()
    _send(app_client, auth_headers, 60, _points(60, 1))  # points again so it can convert

    response = _convert(app_client, unsaved)
    assert response.headers["hx-redirect"] == f"/activities/{upload.json()['id']}"
    page = app_client.get(f"/activities/{upload.json()['id']}")
    assert "Saved from live tracking" not in page.text


def test_only_the_owner_can_convert(app_client, auth_headers, unsaved):
    create_user("viewer@example.com", "Vera")
    web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    app_client.post(
        "/settings/shares",
        headers=HTMX,
        data={"viewer_id": _user_id("viewer@example.com"), "live": "on", "history": "on"},
    )
    web_login(app_client, "viewer@example.com", OTHER_USER_PASSWORD)
    assert _convert(app_client, unsaved).status_code == 404
    assert "Convert to activity" not in app_client.get(f"/live/{unsaved}").text
    viewer_headers = bearer_headers(app_client, "viewer@example.com", OTHER_USER_PASSWORD)
    assert app_client.get("/api/v1/activities", headers=viewer_headers).json()["activities"] == []


def _user_id(email: str) -> str:
    from app.db import get_session_factory
    from app.models.user import User

    with get_session_factory()() as session:
        return session.query(User).filter_by(email=email).one().id


def test_convert_needs_the_htmx_header(app_client, unsaved):
    assert app_client.post(f"/live/{unsaved}/convert").status_code == 403


def test_a_session_with_no_points_cannot_be_converted(app_client, auth_headers):
    _start(app_client, auth_headers)
    session_id = _live_session_id()
    web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    assert _convert(app_client, session_id).status_code == 400
    assert "Convert to activity" not in app_client.get(f"/live/{session_id}").text


def test_the_live_page_warns_when_the_session_updated_recently(app_client, unsaved):
    page = app_client.get(f"/live/{unsaved}").text
    assert "Convert to activity" in page
    assert "phone may just be out of signal" in page

    _set_last_update(unsaved, datetime.now(UTC) - timedelta(minutes=30))
    quiet = app_client.get(f"/live/{unsaved}").text
    assert "Convert to activity" in quiet
    assert "phone may just be out of signal" not in quiet


def test_a_viewer_watching_live_sees_it_finish_on_convert(app_client, auth_headers, unsaved):
    viewer_id = create_user("viewer@example.com", "Vera")
    web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    app_client.post("/settings/shares", headers=HTMX, data={"viewer_id": viewer_id, "live": "on"})
    _convert(app_client, unsaved)
    web_login(app_client, "viewer@example.com", OTHER_USER_PASSWORD)
    assert app_client.get(f"/live/{unsaved}/poll").json() == {
        "status": "finished",
        "activity_url": None,
    }


def test_a_cycling_conversion_has_no_split_plan(app_client, auth_headers):
    _start(app_client, auth_headers, activity_type="cycling", split_plan=CUSTOM_PLAN)
    _send(app_client, auth_headers, 0, _points(0, 20))
    session_id = _live_session_id()
    web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    activity_id = _convert(app_client, session_id).headers["hx-redirect"].rsplit("/", 1)[1]
    gpx = app_client.get(f"/api/v1/activities/{activity_id}/gpx", headers=auth_headers).content
    assert parse_split_plan(gpx) is None
    assert b"split_" not in gpx
