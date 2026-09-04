"""R1 (docs/SERVER-PRODUCTION-PLAN.md): delete routes must remove the GPX
blob only after the row deletion commits, not before — otherwise a failed
commit leaves a row with no blob. Each delete route now calls
session.commit() explicitly before deleting the blob synchronously (a
Starlette BackgroundTask was tried first, but it runs as part of sending
the response — before db_session's own post-yield commit — so it can't be
used for this ordering)."""

from pathlib import Path

import pytest

from app.config import get_settings
from tests.conftest import upload_sample_activity


def _blob_path_for(activity_id: str, app_client, auth_headers) -> Path:
    from app.db import get_session_factory
    from app.models.activity import Activity

    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None
        return Path(get_settings().data_dir) / "gpx" / activity.gpx_blob_key


def test_delete_activity_removes_blob_only_after_commit(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    blob_path = _blob_path_for(created["id"], app_client, auth_headers)
    assert blob_path.exists()

    response = app_client.delete(f"/api/v1/activities/{created['id']}", headers=auth_headers)
    assert response.status_code == 204
    assert not blob_path.exists()


def test_delete_activity_with_a_failing_commit_leaves_the_blob_in_place(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch
) -> None:
    """Forces the route's own explicit session.commit() to fail before it
    reaches the blob delete, and asserts both the row and the blob survive
    — proving blob deletion really is ordered after a *successful* commit,
    not just after the row is deleted in-session."""
    from sqlalchemy.orm import Session

    from app.db import get_session_factory
    from app.models.activity import Activity

    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    blob_path = _blob_path_for(created["id"], app_client, auth_headers)
    assert blob_path.exists()

    real_commit = Session.commit

    def failing_commit(self):
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(Session, "commit", failing_commit)
    try:
        with pytest.raises(RuntimeError, match="simulated commit failure"):
            app_client.delete(f"/api/v1/activities/{created['id']}", headers=auth_headers)
    finally:
        monkeypatch.setattr(Session, "commit", real_commit)

    assert blob_path.exists()
    with get_session_factory()() as session:
        assert session.get(Activity, created["id"]) is not None


def test_web_delete_removes_blob_only_after_commit(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    blob_path = _blob_path_for(created["id"], app_client, auth_headers)
    assert blob_path.exists()

    login = app_client.post(
        "/login",
        headers={"X-Requested-With": "htmx"},
        data={"email": "admin@example.com", "password": "admin-password-123"},
    )
    assert login.status_code == 200

    response = app_client.delete(
        f"/activities/{created['id']}", headers={"X-Requested-With": "htmx"}
    )
    assert response.status_code == 200
    assert not blob_path.exists()
