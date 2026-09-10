from datetime import UTC, datetime

from tests.conftest import upload_sample_activity


def _other_user_headers(app_client) -> dict[str, str]:
    """Creates a second account and returns its bearer auth headers — mirrors
    the pattern in test_activities_export_import.py::_other_user_headers."""
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


def test_add_tag_creates_and_attaches_it(app_client, auth_headers, sample_gpx_bytes):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]

    response = app_client.post(
        f"/api/v1/activities/{activity_id}/tags", headers=auth_headers, json={"name": "Strava"}
    )
    assert response.status_code == 201
    tags = response.json()["tags"]
    assert len(tags) == 1
    assert tags[0]["name"] == "Strava"
    assert tags[0]["id"]


def test_add_tag_is_idempotent_and_case_insensitive(app_client, auth_headers, sample_gpx_bytes):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]

    app_client.post(
        f"/api/v1/activities/{activity_id}/tags", headers=auth_headers, json={"name": "Strava"}
    )
    response = app_client.post(
        f"/api/v1/activities/{activity_id}/tags", headers=auth_headers, json={"name": "strava"}
    )
    assert response.status_code == 201
    tags = response.json()["tags"]
    # Same underlying tag reused (case-insensitive get-or-create), not a
    # second "strava" tag alongside the original "Strava".
    assert len(tags) == 1
    assert tags[0]["name"] == "Strava"


def test_add_tag_reuses_existing_tag_across_activities(app_client, auth_headers, sample_gpx_bytes):
    first = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes, "act-1")
    second = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes, "act-2")

    r1 = app_client.post(
        f"/api/v1/activities/{first.json()['id']}/tags",
        headers=auth_headers,
        json={"name": "Strava"},
    )
    r2 = app_client.post(
        f"/api/v1/activities/{second.json()['id']}/tags",
        headers=auth_headers,
        json={"name": "Strava"},
    )
    assert r1.json()["tags"][0]["id"] == r2.json()["tags"][0]["id"]


def test_remove_tag(app_client, auth_headers, sample_gpx_bytes):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    add = app_client.post(
        f"/api/v1/activities/{activity_id}/tags", headers=auth_headers, json={"name": "Strava"}
    )
    tag_id = add.json()["tags"][0]["id"]

    response = app_client.delete(
        f"/api/v1/activities/{activity_id}/tags/{tag_id}", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["tags"] == []


def test_remove_tag_not_present_is_a_no_op(app_client, auth_headers, sample_gpx_bytes):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]

    response = app_client.delete(
        f"/api/v1/activities/{activity_id}/tags/does-not-exist", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["tags"] == []


def test_add_tag_rejects_empty_name(app_client, auth_headers, sample_gpx_bytes):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]

    response = app_client.post(
        f"/api/v1/activities/{activity_id}/tags", headers=auth_headers, json={"name": "   "}
    )
    assert response.status_code == 400


def test_add_tag_rejects_overlong_name(app_client, auth_headers, sample_gpx_bytes):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]

    response = app_client.post(
        f"/api/v1/activities/{activity_id}/tags",
        headers=auth_headers,
        json={"name": "x" * 51},
    )
    assert response.status_code in (400, 422)


def test_add_tag_404s_for_missing_activity(app_client, auth_headers):
    response = app_client.post(
        "/api/v1/activities/does-not-exist/tags", headers=auth_headers, json={"name": "Strava"}
    )
    assert response.status_code == 404


def test_add_tag_404s_not_403s_for_another_users_activity(
    app_client, auth_headers, sample_gpx_bytes
):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]

    other_headers = _other_user_headers(app_client)
    response = app_client.post(
        f"/api/v1/activities/{activity_id}/tags", headers=other_headers, json={"name": "Strava"}
    )
    assert response.status_code == 404


def test_tags_are_scoped_per_user(app_client, auth_headers, sample_gpx_bytes):
    """Two users tagging their own activities the same name get distinct Tag
    rows, not a shared global tag."""
    mine = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes, "mine")
    mine_tag = app_client.post(
        f"/api/v1/activities/{mine.json()['id']}/tags",
        headers=auth_headers,
        json={"name": "Strava"},
    ).json()["tags"][0]

    other_headers = _other_user_headers(app_client)
    theirs = upload_sample_activity(app_client, other_headers, sample_gpx_bytes, "theirs")
    their_tag = app_client.post(
        f"/api/v1/activities/{theirs.json()['id']}/tags",
        headers=other_headers,
        json={"name": "Strava"},
    ).json()["tags"][0]

    assert mine_tag["id"] != their_tag["id"]


def test_activity_list_includes_tags(app_client, auth_headers, sample_gpx_bytes):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    app_client.post(
        f"/api/v1/activities/{activity_id}/tags", headers=auth_headers, json={"name": "Strava"}
    )

    response = app_client.get("/api/v1/activities", headers=auth_headers)
    assert response.status_code == 200
    items = response.json()["activities"]
    assert items[0]["tags"][0]["name"] == "Strava"


def test_deleting_activity_cleans_up_tag_association(app_client, auth_headers, sample_gpx_bytes):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    app_client.post(
        f"/api/v1/activities/{activity_id}/tags", headers=auth_headers, json={"name": "Strava"}
    )

    response = app_client.delete(f"/api/v1/activities/{activity_id}", headers=auth_headers)
    assert response.status_code == 204

    # Re-adding a same-named tag to a fresh activity must not fail with a
    # dangling activity_tags row / stale FK from the deleted activity.
    second = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes, "after-delete")
    response = app_client.post(
        f"/api/v1/activities/{second.json()['id']}/tags",
        headers=auth_headers,
        json={"name": "Strava"},
    )
    assert response.status_code == 201


def test_web_add_and_remove_tag(app_client):
    """Exercises the web (htmx) tag routes, distinct from the JSON API ones —
    covers the CSRF (require_htmx_header) gate and HX-Refresh response."""
    from app.auth.passwords import hash_password
    from app.db import get_session_factory
    from app.models.user import User
    from app.repositories.users import SqlAlchemyUserRepository

    with get_session_factory()() as session:
        now = datetime.now(UTC)
        user = User(
            email="web@example.com",
            password_hash=hash_password("web-password-123"),
            display_name="Web",
            is_admin=False,
            sessions_invalidated_at=now,
            created_at=now,
        )
        SqlAlchemyUserRepository(session).add(user)
        session.commit()

    login = app_client.post(
        "/login",
        data={"email": "web@example.com", "password": "web-password-123"},
        headers={"X-Requested-With": "htmx"},
    )
    assert login.status_code in (200, 303)

    from pathlib import Path

    gpx_bytes = (Path(__file__).parent / "fixtures" / "sample_run.gpx").read_bytes()
    upload = app_client.post(
        "/upload",
        data={"activity_type": "running"},
        files={"gpx": ("activity.gpx", gpx_bytes, "application/gpx+xml")},
        headers={"X-Requested-With": "htmx"},
    )
    assert upload.status_code == 200
    activity_id = upload.headers["hx-redirect"].rsplit("/", 1)[-1]

    # Missing the CSRF header entirely -> rejected.
    no_csrf = app_client.post(f"/activities/{activity_id}/tags", data={"name": "Strava"})
    assert no_csrf.status_code == 403

    add = app_client.post(
        f"/activities/{activity_id}/tags",
        data={"name": "Strava"},
        headers={"X-Requested-With": "htmx"},
    )
    assert add.status_code == 200

    detail = app_client.get(f"/activities/{activity_id}")
    assert "Strava" in detail.text

    from app.models.activity import Activity

    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        tag_id = activity.tags[0].id

    remove = app_client.delete(
        f"/activities/{activity_id}/tags/{tag_id}", headers={"X-Requested-With": "htmx"}
    )
    assert remove.status_code == 200

    detail_after = app_client.get(f"/activities/{activity_id}")
    assert "No tags yet." in detail_after.text
