import json
from datetime import UTC

import pytest

from tests.conftest import make_summary, upload_sample_activity


def test_upload_creates_an_activity_with_analysis(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    response = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    assert response.status_code == 201
    body = response.json()
    assert body["analysis"]["status"] == "done"
    assert body["analysis"]["result"]["distance_meters"] > 0
    assert body["client_summary"]["distance_meters"] == 3000.0
    assert body["activity_type"] == "running"


def test_upload_with_cycling_type_is_stored_and_returned(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    response = upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, activity_type="cycling"
    )
    assert response.status_code == 201
    assert response.json()["activity_type"] == "cycling"


def test_upload_with_invalid_activity_type_is_rejected(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    response = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary(activity_type="swimming"))},
        files={"gpx": ("activity.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_summary"


def test_reupload_with_same_client_activity_id_is_idempotent(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    first = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    assert first.status_code == 201
    activity_id = first.json()["id"]

    second = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    assert second.status_code == 200
    assert second.json()["id"] == activity_id


def test_different_client_activity_ids_create_separate_activities(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    first = upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )
    second = upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


def test_upload_requires_authentication(app_client, sample_gpx_bytes) -> None:
    response = app_client.post(
        "/api/v1/activities",
        data={"summary": json.dumps(make_summary())},
        files={"gpx": ("activity.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert response.status_code == 401


def test_upload_oversize_gpx_is_rejected(app_client, auth_headers, monkeypatch) -> None:
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SR_MAX_GPX_BYTES", "10")
    get_settings.cache_clear()
    try:
        response = app_client.post(
            "/api/v1/activities",
            headers=auth_headers,
            data={"summary": json.dumps(make_summary())},
            files={"gpx": ("activity.gpx", b"x" * 100, "application/gpx+xml")},
        )
        assert response.status_code == 413
    finally:
        get_settings.cache_clear()


def test_upload_junk_gpx_is_rejected(app_client, auth_headers) -> None:
    response = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary())},
        files={"gpx": ("activity.gpx", b"this is not gpx", "application/gpx+xml")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_gpx"


def test_upload_gpx_with_no_timestamped_points_is_rejected(app_client, auth_headers) -> None:
    empty_gpx = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg></trkseg></trk>
</gpx>"""
    response = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary())},
        files={"gpx": ("activity.gpx", empty_gpx, "application/gpx+xml")},
    )
    assert response.status_code == 400


def test_upload_with_malformed_summary_is_rejected(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    response = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": "{not valid json"},
        files={"gpx": ("activity.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_summary"


def test_upload_with_too_many_splits_is_rejected(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    summary = make_summary()
    summary["splits"] = [
        {"index": i, "duration_seconds": 60.0, "avg_speed_mps": 3.0} for i in range(1, 2002)
    ]
    response = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(summary)},
        files={"gpx": ("activity.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_summary"


def test_upload_with_oversized_summary_is_rejected(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    response = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": "x" * (256 * 1024 + 1)},
        files={"gpx": ("activity.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_summary"


def test_get_activity_by_id(app_client, auth_headers, sample_gpx_bytes) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    response = app_client.get(f"/api/v1/activities/{created['id']}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_nonexistent_activity_404s(app_client, auth_headers) -> None:
    response = app_client.get("/api/v1/activities/does-not-exist", headers=auth_headers)
    assert response.status_code == 404


def test_activity_belonging_to_another_user_404s_not_403s(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()

    from datetime import datetime

    from app.auth.passwords import hash_password
    from app.db import get_session_factory
    from app.models.user import User
    from app.repositories.users import SqlAlchemyUserRepository

    with get_session_factory()() as session:
        now = datetime.now(UTC)
        other = User(
            email="other@example.com",
            password_hash=hash_password("other-password-123"),
            display_name="Other",
            is_admin=False,
            sessions_invalidated_at=now,
            created_at=now,
        )
        SqlAlchemyUserRepository(session).add(other)
        session.commit()

    login = app_client.post(
        "/api/v1/auth/login",
        json={"email": "other@example.com", "password": "other-password-123", "device_name": "x"},
    )
    other_headers = {"Authorization": f"Bearer {login.json()['token']}"}

    response = app_client.get(f"/api/v1/activities/{created['id']}", headers=other_headers)
    assert response.status_code == 404


def test_patch_updates_title_and_notes(app_client, auth_headers, sample_gpx_bytes) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    response = app_client.patch(
        f"/api/v1/activities/{created['id']}",
        headers=auth_headers,
        json={"title": "Morning run", "notes": "Felt great"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Morning run"
    assert response.json()["notes"] == "Felt great"


def test_patch_rejects_unknown_fields(app_client, auth_headers, sample_gpx_bytes) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    response = app_client.patch(
        f"/api/v1/activities/{created['id']}",
        headers=auth_headers,
        json={"distance_meters": 999.0},
    )
    assert response.status_code == 422


def test_delete_removes_the_activity(app_client, auth_headers, sample_gpx_bytes) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    response = app_client.delete(f"/api/v1/activities/{created['id']}", headers=auth_headers)
    assert response.status_code == 204

    response = app_client.get(f"/api/v1/activities/{created['id']}", headers=auth_headers)
    assert response.status_code == 404


def test_gpx_download_returns_the_original_bytes(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    response = app_client.get(f"/api/v1/activities/{created['id']}/gpx", headers=auth_headers)
    assert response.status_code == 200
    assert response.content == sample_gpx_bytes
    assert response.headers["content-type"].startswith("application/gpx+xml")


def test_analysis_endpoint_returns_the_computed_result(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    response = app_client.get(f"/api/v1/activities/{created['id']}/analysis", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "done"


def test_track_endpoint_returns_downsampled_points(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    response = app_client.get(
        f"/api/v1/activities/{created['id']}/track", headers=auth_headers, params={"max_points": 50}
    )
    assert response.status_code == 200
    segments = response.json()["segments"]
    assert len(segments) == 2
    for segment in segments:
        assert len(segment) <= 52  # max_points + a small stride-rounding allowance


def test_track_endpoint_at_default_max_points_serves_the_cached_track(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch
) -> None:
    """R8 in docs/SERVER-PRODUCTION-PLAN.md: a request at the default
    max_points must be served from the cached track computed at upload
    time, without re-reading/re-parsing the GPX blob."""
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()

    from app.storage.blob_store import LocalFileBlobStore

    def _fail_if_called(self, blob_key: str) -> bytes:
        raise AssertionError("blob should not be read when the cached track is available")

    monkeypatch.setattr(LocalFileBlobStore, "get", _fail_if_called)

    response = app_client.get(f"/api/v1/activities/{created['id']}/track", headers=auth_headers)
    assert response.status_code == 200
    segments = response.json()["segments"]
    assert len(segments) == 2
    assert all(len(segment) > 0 for segment in segments)


def test_track_endpoint_at_non_default_max_points_reparses(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    default_response = app_client.get(
        f"/api/v1/activities/{created['id']}/track", headers=auth_headers
    )
    custom_response = app_client.get(
        f"/api/v1/activities/{created['id']}/track",
        headers=auth_headers,
        params={"max_points": 10},
    )
    assert default_response.status_code == custom_response.status_code == 200
    default_lengths = [len(s) for s in default_response.json()["segments"]]
    custom_lengths = [len(s) for s in custom_response.json()["segments"]]
    assert custom_lengths != default_lengths


def test_upload_rejects_gpx_with_doctype(app_client, auth_headers) -> None:
    malicious_gpx = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE gpx [<!ENTITY xxe "test">]>'
        b'<gpx version="1.1"><trk><trkseg>'
        b'<trkpt lat="0" lon="0"><time>2026-01-01T00:00:00Z</time></trkpt>'
        b"</trkseg></trk></gpx>"
    )
    response = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary())},
        files={"gpx": ("activity.gpx", malicious_gpx, "application/gpx+xml")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_gpx"


def test_pagination_cursor_pages_through_results(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    ids = [f"cccccccc-cccc-cccc-cccc-{i:012d}" for i in range(5)]
    for activity_id in ids:
        upload_sample_activity(app_client, auth_headers, sample_gpx_bytes, activity_id)

    response = app_client.get("/api/v1/activities", headers=auth_headers, params={"limit": 2})
    assert response.status_code == 200
    page1 = response.json()
    assert len(page1["activities"]) == 2
    assert page1["next_cursor"] is not None

    seen_ids = {a["id"] for a in page1["activities"]}
    cursor = page1["next_cursor"]
    while cursor is not None:
        response = app_client.get(
            "/api/v1/activities", headers=auth_headers, params={"limit": 2, "cursor": cursor}
        )
        page = response.json()
        seen_ids.update(a["id"] for a in page["activities"])
        cursor = page["next_cursor"]

    assert len(seen_ids) == 5


@pytest.mark.parametrize(
    "cursor",
    [
        "garbage",  # invalid base64 padding
        "Zm9v",  # valid base64, not JSON
        "WyJub3QtYS1kYXRlIiwieCJd",  # valid JSON list, non-ISO date
        "WzFd",  # valid JSON list, wrong length
    ],
)
def test_malformed_cursor_returns_400(app_client, auth_headers, cursor) -> None:
    response = app_client.get("/api/v1/activities", headers=auth_headers, params={"cursor": cursor})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cursor"
