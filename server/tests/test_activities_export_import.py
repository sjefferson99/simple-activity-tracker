import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from tests.conftest import upload_sample_activity


def _other_user_headers(app_client) -> dict[str, str]:
    """Creates a second account and returns its bearer auth headers — used to
    verify export/import are scoped per-user, mirroring the pattern in
    test_activities_api.py::test_activity_belonging_to_another_user_404s_not_403s."""
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
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_export_all_produces_a_zip_with_manifest_and_gpx(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)

    response = app_client.post("/api/v1/activities/export", headers=auth_headers, json={})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    archive = zipfile.ZipFile(io.BytesIO(response.content))
    manifest = json.loads(archive.read("manifest.json"))
    assert len(manifest["activities"]) == 1
    entry = manifest["activities"][0]
    assert entry["client_activity_id"] == "11111111-1111-1111-1111-111111111111"
    assert entry["gpx_filename"] in archive.namelist()
    assert archive.read(entry["gpx_filename"]) == sample_gpx_bytes


def test_export_selected_ids_only_includes_those_activities(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    first = upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    ).json()
    upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )

    response = app_client.post(
        "/api/v1/activities/export",
        headers=auth_headers,
        json={"activity_ids": [first["id"]]},
    )
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    manifest = json.loads(archive.read("manifest.json"))
    assert len(manifest["activities"]) == 1
    assert manifest["activities"][0]["client_activity_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_export_with_unknown_id_404s(app_client, auth_headers) -> None:
    response = app_client.post(
        "/api/v1/activities/export", headers=auth_headers, json={"activity_ids": ["nope"]}
    )
    assert response.status_code == 404


def test_export_cannot_include_another_users_activity(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    other_headers = _other_user_headers(app_client)

    response = app_client.post(
        "/api/v1/activities/export",
        headers=other_headers,
        json={"activity_ids": [created["id"]]},
    )
    assert response.status_code == 404


def test_import_round_trip_recreates_the_activity(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    original = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    app_client.delete(f"/api/v1/activities/{original['id']}", headers=auth_headers)
    archive_bytes = _export_archive_from_manifest(sample_gpx_bytes, original)

    response = app_client.post(
        "/api/v1/activities/import",
        headers=auth_headers,
        files={"archive": ("export.zip", archive_bytes, "application/zip")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 1
    assert body["skipped"] == 0
    assert body["failed"] == 0

    listing = app_client.get("/api/v1/activities", headers=auth_headers).json()
    assert len(listing["activities"]) == 1
    assert listing["activities"][0]["title"] == original["title"]


def _export_archive_from_manifest(gpx_bytes: bytes, activity: dict) -> bytes:
    manifest = {
        "activities": [
            {
                "client_activity_id": activity["client_activity_id"],
                "activity_type": activity["activity_type"],
                "started_at": activity["started_at"],
                "ended_at": activity["ended_at"],
                "title": activity["title"],
                "notes": activity["notes"],
                "client_summary": activity["client_summary"],
                "source_platform": activity["source_platform"],
                "source_app_version": activity["source_app_version"],
                "gpx_filename": f"{activity['client_activity_id']}.gpx",
            }
        ]
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr(f"{activity['client_activity_id']}.gpx", gpx_bytes)
    return buffer.getvalue()


def test_import_skips_an_activity_that_already_exists(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    original = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    archive_bytes = _export_archive_from_manifest(sample_gpx_bytes, original)

    response = app_client.post(
        "/api/v1/activities/import",
        headers=auth_headers,
        files={"archive": ("export.zip", archive_bytes, "application/zip")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 0
    assert body["skipped"] == 1
    assert body["items"][0]["status"] == "skipped"


def test_import_into_a_different_account_does_not_collide(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    original = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    archive_bytes = _export_archive_from_manifest(sample_gpx_bytes, original)
    other_headers = _other_user_headers(app_client)

    response = app_client.post(
        "/api/v1/activities/import",
        headers=other_headers,
        files={"archive": ("export.zip", archive_bytes, "application/zip")},
    )
    assert response.status_code == 200
    assert response.json()["imported"] == 1

    other_listing = app_client.get("/api/v1/activities", headers=other_headers).json()
    assert len(other_listing["activities"]) == 1
    owner_listing = app_client.get("/api/v1/activities", headers=auth_headers).json()
    assert len(owner_listing["activities"]) == 1


def test_import_rejects_a_non_zip_file(app_client, auth_headers) -> None:
    response = app_client.post(
        "/api/v1/activities/import",
        headers=auth_headers,
        files={"archive": ("export.zip", b"not a zip", "application/zip")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_archive"


def test_import_rejects_a_manifest_that_exceeds_max_import_bytes_when_decompressed(
    app_client, auth_headers, monkeypatch
) -> None:
    """Regression test: manifest.json's declared uncompressed size must be
    checked before it's decompressed — a highly compressible manifest.json
    can reach a >1000:1 compression ratio (confirmed: ~48KB compressed
    inflates to ~48MB), so without this check a small upload well under
    SR_MAX_IMPORT_BYTES could still force a much larger decompression."""
    from app.config import get_settings

    monkeypatch.setenv("SR_MAX_IMPORT_BYTES", "1000")
    get_settings.cache_clear()
    try:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", "x" * 10_000)

        response = app_client.post(
            "/api/v1/activities/import",
            headers=auth_headers,
            files={"archive": ("export.zip", buffer.getvalue(), "application/zip")},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_archive"
    finally:
        get_settings.cache_clear()


def test_import_rejects_a_zip_missing_the_manifest(app_client, auth_headers) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "not a manifest")

    response = app_client.post(
        "/api/v1/activities/import",
        headers=auth_headers,
        files={"archive": ("export.zip", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_archive"


def test_import_reports_a_failed_item_when_gpx_entry_is_missing(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    original = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    manifest = {
        "activities": [
            {
                "client_activity_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "activity_type": original["activity_type"],
                "started_at": original["started_at"],
                "ended_at": original["ended_at"],
                "title": None,
                "notes": None,
                "client_summary": original["client_summary"],
                "source_platform": original["source_platform"],
                "source_app_version": original["source_app_version"],
                "gpx_filename": "missing.gpx",
            }
        ]
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))

    response = app_client.post(
        "/api/v1/activities/import",
        headers=auth_headers,
        files={"archive": ("export.zip", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["failed"] == 1
    assert "missing.gpx" in body["items"][0]["reason"]


def test_import_reports_a_failed_item_for_invalid_gpx_but_continues(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    good = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    app_client.delete(f"/api/v1/activities/{good['id']}", headers=auth_headers)

    manifest = {
        "activities": [
            {
                "client_activity_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "activity_type": "running",
                "started_at": good["started_at"],
                "ended_at": good["ended_at"],
                "title": None,
                "notes": None,
                "client_summary": good["client_summary"],
                "source_platform": good["source_platform"],
                "source_app_version": good["source_app_version"],
                "gpx_filename": "bad.gpx",
            },
            {
                "client_activity_id": good["client_activity_id"],
                "activity_type": good["activity_type"],
                "started_at": good["started_at"],
                "ended_at": good["ended_at"],
                "title": good["title"],
                "notes": good["notes"],
                "client_summary": good["client_summary"],
                "source_platform": good["source_platform"],
                "source_app_version": good["source_app_version"],
                "gpx_filename": "good.gpx",
            },
        ]
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("bad.gpx", b"not valid gpx")
        archive.writestr("good.gpx", sample_gpx_bytes)

    response = app_client.post(
        "/api/v1/activities/import",
        headers=auth_headers,
        files={"archive": ("export.zip", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["failed"] == 1
    assert body["imported"] == 1
    failed_item = next(item for item in body["items"] if item["status"] == "failed")
    assert failed_item["reason"] is not None
    assert not failed_item["reason"].startswith("400:")
    assert "{'error'" not in failed_item["reason"]


def test_import_persists_earlier_successes_even_when_a_later_entry_fails(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    """Regression test: a failure partway through a batch must not roll back
    activities that were already successfully inserted earlier in the same
    request — db_session only commits once, at the very end, so a bare
    session.rollback() in the per-entry except block would previously wipe
    every prior success in the same import too."""
    good = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    app_client.delete(f"/api/v1/activities/{good['id']}", headers=auth_headers)

    manifest = {
        "activities": [
            {
                "client_activity_id": good["client_activity_id"],
                "activity_type": good["activity_type"],
                "started_at": good["started_at"],
                "ended_at": good["ended_at"],
                "title": good["title"],
                "notes": good["notes"],
                "client_summary": good["client_summary"],
                "source_platform": good["source_platform"],
                "source_app_version": good["source_app_version"],
                "gpx_filename": "good.gpx",
            },
            {
                "client_activity_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                "activity_type": "running",
                "started_at": good["started_at"],
                "ended_at": good["ended_at"],
                "title": None,
                "notes": None,
                "client_summary": good["client_summary"],
                "source_platform": good["source_platform"],
                "source_app_version": good["source_app_version"],
                "gpx_filename": "bad.gpx",
            },
        ]
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("good.gpx", sample_gpx_bytes)
        archive.writestr("bad.gpx", b"not valid gpx")

    response = app_client.post(
        "/api/v1/activities/import",
        headers=auth_headers,
        files={"archive": ("export.zip", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 1
    assert body["failed"] == 1

    listing = app_client.get("/api/v1/activities", headers=auth_headers).json()
    client_activity_ids = {a["id"] for a in listing["activities"]}
    assert len(client_activity_ids) == 1


def test_import_oversize_archive_is_rejected(app_client, auth_headers, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("SR_MAX_IMPORT_BYTES", "10")
    get_settings.cache_clear()
    try:
        response = app_client.post(
            "/api/v1/activities/import",
            headers=auth_headers,
            files={"archive": ("export.zip", b"x" * 100, "application/zip")},
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "archive_too_large"
    finally:
        get_settings.cache_clear()


def test_import_requires_authentication(app_client) -> None:
    response = app_client.post(
        "/api/v1/activities/import", files={"archive": ("export.zip", b"x", "application/zip")}
    )
    assert response.status_code == 401


def test_export_requires_authentication(app_client) -> None:
    response = app_client.post("/api/v1/activities/export", json={})
    assert response.status_code == 401


def _manifest_entry(activity: dict, **overrides) -> dict:
    entry = {
        "client_activity_id": activity["client_activity_id"],
        "activity_type": activity["activity_type"],
        "started_at": activity["started_at"],
        "ended_at": activity["ended_at"],
        "title": activity["title"],
        "notes": activity["notes"],
        "client_summary": activity["client_summary"],
        "source_platform": activity["source_platform"],
        "source_app_version": activity["source_app_version"],
        "gpx_filename": f"{activity['client_activity_id']}.gpx",
    }
    entry.update(overrides)
    return entry


def test_import_rejects_an_oversized_client_summary(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    good = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    app_client.delete(f"/api/v1/activities/{good['id']}", headers=auth_headers)

    oversized_summary = dict(good["client_summary"], padding="x" * (256 * 1024 + 1))
    manifest = {"activities": [_manifest_entry(good, client_summary=oversized_summary)]}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr(f"{good['client_activity_id']}.gpx", sample_gpx_bytes)

    response = app_client.post(
        "/api/v1/activities/import",
        headers=auth_headers,
        files={"archive": ("export.zip", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["failed"] == 1
    assert body["imported"] == 0
    assert "client_summary" in body["items"][0]["reason"]

    listing = app_client.get("/api/v1/activities", headers=auth_headers).json()
    assert listing["activities"] == []


def test_import_rejects_an_oversized_title(app_client, auth_headers, sample_gpx_bytes) -> None:
    good = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    app_client.delete(f"/api/v1/activities/{good['id']}", headers=auth_headers)

    manifest = {"activities": [_manifest_entry(good, title="x" * 201)]}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr(f"{good['client_activity_id']}.gpx", sample_gpx_bytes)

    response = app_client.post(
        "/api/v1/activities/import",
        headers=auth_headers,
        files={"archive": ("export.zip", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["failed"] == 1
    assert body["imported"] == 0


def test_export_skips_an_activity_with_a_missing_blob_instead_of_crashing(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    from app.config import get_settings
    from app.db import get_session_factory
    from app.models.activity import Activity

    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()

    with get_session_factory()() as session:
        activity = session.get(Activity, created["id"])
        assert activity is not None
        blob_path = Path(get_settings().data_dir) / "gpx" / activity.gpx_blob_key
        blob_path.unlink()

    response = app_client.post("/api/v1/activities/export", headers=auth_headers, json={})
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["activities"] == []


def test_import_batch_with_duplicate_client_activity_id_within_itself(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    """Regression test for a reviewer-flagged concern: two manifest entries
    sharing the same client_activity_id within one import (or one colliding
    with a genuinely concurrent insert) exercises _insert_activity_with_gpx's
    own inner begin_nested()/IntegrityError/rollback() path *while already
    inside run_import's outer per-entry savepoint*. Verifies this doesn't
    corrupt the session or lose an unrelated earlier successful entry in the
    same batch."""
    other = upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "11111111-1111-1111-1111-111111111112"
    ).json()
    app_client.delete(f"/api/v1/activities/{other['id']}", headers=auth_headers)

    dup_id = "99999999-9999-9999-9999-999999999999"
    manifest = {
        "activities": [
            _manifest_entry(other),
            {**_manifest_entry(other), "client_activity_id": dup_id, "gpx_filename": "dup1.gpx"},
            {**_manifest_entry(other), "client_activity_id": dup_id, "gpx_filename": "dup2.gpx"},
        ]
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr(f"{other['client_activity_id']}.gpx", sample_gpx_bytes)
        archive.writestr("dup1.gpx", sample_gpx_bytes)
        archive.writestr("dup2.gpx", sample_gpx_bytes)

    response = app_client.post(
        "/api/v1/activities/import",
        headers=auth_headers,
        files={"archive": ("export.zip", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 2
    assert body["skipped"] == 1

    listing = app_client.get("/api/v1/activities", headers=auth_headers).json()
    assert len(listing["activities"]) == 2
