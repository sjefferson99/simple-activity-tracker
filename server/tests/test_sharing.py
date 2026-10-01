"""Sharing activity history with other users (issue #130 phase A,
docs/LIVE-TRACKING-PLAN.md §2.2 and §3). The owner is always in control:
only they grant, a revoke applies to the very next request, and a viewer can
never edit, download or export anything."""

import io
import logging
import zipfile
from datetime import UTC, datetime

import pytest

from tests.conftest import upload_sample_activity

HTMX = {"X-Requested-With": "htmx"}
OWNER_EMAIL, OWNER_PASSWORD = "admin@example.com", "admin-password-123"
VIEWER_PASSWORD = "viewer-password-123"


def _create_user(email: str, display_name: str, *, disabled: bool = False) -> str:
    from app.auth.passwords import hash_password
    from app.db import get_session_factory
    from app.models.user import User
    from app.repositories.users import SqlAlchemyUserRepository

    with get_session_factory()() as session:
        now = datetime.now(UTC)
        user = User(
            email=email,
            password_hash=hash_password(VIEWER_PASSWORD),
            display_name=display_name,
            is_admin=False,
            disabled_at=now if disabled else None,
            sessions_invalidated_at=now,
            created_at=now,
        )
        SqlAlchemyUserRepository(session).add(user)
        session.commit()
        return user.id


def _web_login(client, email: str, password: str) -> None:
    client.cookies.clear()
    response = client.post("/login", headers=HTMX, data={"email": email, "password": password})
    assert response.status_code == 200


def _bearer(client, email: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password, "device_name": "t"}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _set_title(activity_id: str, title: str) -> None:
    from app.db import get_session_factory
    from app.models.activity import Activity

    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None
        activity.title = title
        session.commit()


@pytest.fixture
def shared_setup(app_client, auth_headers, sample_gpx_bytes):
    """Owner (the admin fixture user) with two activities, plus a viewer
    account. Nothing is shared yet. Leaves the client signed in as owner."""
    first = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()["id"]
    second = upload_sample_activity(
        app_client,
        auth_headers,
        sample_gpx_bytes,
        client_activity_id="22222222-2222-2222-2222-222222222222",
    ).json()["id"]
    _set_title(first, "Owner Morning Run")
    _set_title(second, "Owner Evening Run")
    viewer_id = _create_user("viewer@example.com", "Vera Viewer")
    _web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    return {"activities": [first, second], "viewer_id": viewer_id}


def _grant_history(client, viewer_id: str) -> None:
    _web_login(client, OWNER_EMAIL, OWNER_PASSWORD)
    response = client.post("/settings/shares", headers=HTMX, data={"viewer_id": viewer_id})
    assert response.status_code == 200


def _as_viewer(client) -> None:
    _web_login(client, "viewer@example.com", VIEWER_PASSWORD)


# --- settings: the owner's controls --------------------------------------


def test_settings_lists_enabled_other_users_in_the_dropdown(app_client, shared_setup):
    _create_user("gone@example.com", "Disabled Dan", disabled=True)
    page = app_client.get("/settings")
    assert page.status_code == 200
    assert "Sharing" in page.text
    assert "Vera Viewer" in page.text
    assert "Disabled Dan" not in page.text
    # Display names only, never another user's email.
    assert "viewer@example.com" not in page.text


def test_grant_then_revoke_history(app_client, shared_setup):
    viewer_id = shared_setup["viewer_id"]
    granted = app_client.post("/settings/shares", headers=HTMX, data={"viewer_id": viewer_id})
    assert granted.status_code == 200
    assert f'hx-delete="/settings/shares/{viewer_id}"' in granted.text

    revoked = app_client.delete(f"/settings/shares/{viewer_id}", headers=HTMX)
    assert revoked.status_code == 200
    assert f'hx-delete="/settings/shares/{viewer_id}"' not in revoked.text

    from app.db import get_session_factory
    from app.models.share import UserShare

    with get_session_factory()() as session:
        assert session.query(UserShare).count() == 0


@pytest.mark.parametrize("bad_viewer", ["self", "disabled", "unknown", ""])
def test_cannot_share_with_self_disabled_or_unknown_users(app_client, shared_setup, bad_viewer):
    from app.db import get_session_factory
    from app.models.share import UserShare
    from app.repositories.users import SqlAlchemyUserRepository

    with get_session_factory()() as session:
        owner = SqlAlchemyUserRepository(session).get_by_email(OWNER_EMAIL)
        assert owner is not None
        owner_id = owner.id
    viewer_id = {
        "self": owner_id,
        "disabled": _create_user("gone@example.com", "Gone", disabled=True),
        "unknown": "00000000-0000-0000-0000-000000000000",
        "": "",
    }[bad_viewer]

    response = app_client.post("/settings/shares", headers=HTMX, data={"viewer_id": viewer_id})
    assert response.status_code == 400
    activity_response = app_client.post(
        f"/activities/{shared_setup['activities'][0]}/shares",
        headers=HTMX,
        data={"viewer_id": viewer_id},
    )
    assert activity_response.status_code == 400
    with get_session_factory()() as session:
        assert session.query(UserShare).count() == 0


def test_sharing_mutations_require_the_htmx_header(app_client, shared_setup):
    viewer_id = shared_setup["viewer_id"]
    activity_id = shared_setup["activities"][0]
    assert app_client.post("/settings/shares", data={"viewer_id": viewer_id}).status_code == 403
    assert app_client.delete(f"/settings/shares/{viewer_id}").status_code == 403
    assert (
        app_client.post(
            f"/activities/{activity_id}/shares", data={"viewer_id": viewer_id}
        ).status_code
        == 403
    )
    assert app_client.delete(f"/activities/{activity_id}/shares/{viewer_id}").status_code == 403


def test_sharing_changes_are_audited(app_client, shared_setup, caplog):
    viewer_id = shared_setup["viewer_id"]
    activity_id = shared_setup["activities"][0]
    with caplog.at_level(logging.INFO, logger="app.audit"):
        app_client.post("/settings/shares", headers=HTMX, data={"viewer_id": viewer_id})
        app_client.delete(f"/settings/shares/{viewer_id}", headers=HTMX)
        app_client.post(
            f"/activities/{activity_id}/shares", headers=HTMX, data={"viewer_id": viewer_id}
        )
        app_client.delete(f"/activities/{activity_id}/shares/{viewer_id}", headers=HTMX)
    messages = " ".join(r.message for r in caplog.records if r.name == "app.audit")
    for event in (
        "share.history_granted",
        "share.history_revoked",
        "activity_share.added",
        "activity_share.removed",
    ):
        assert f"event={event}" in messages


# --- the viewer's side ------------------------------------------------------


def test_nothing_is_visible_without_a_grant(app_client, shared_setup):
    activity_id = shared_setup["activities"][0]
    _as_viewer(app_client)

    shared_tab = app_client.get("/", params={"tab": "shared"})
    assert shared_tab.status_code == 200
    assert "Nothing has been shared with you yet" in shared_tab.text
    assert "Owner Morning Run" not in shared_tab.text
    for path in ("", "/track", "/splits", "/splits/reset"):
        assert app_client.get(f"/shared/activities/{activity_id}{path}").status_code == 404


def test_history_grant_shows_every_activity_on_the_shared_tab_only(app_client, shared_setup):
    _grant_history(app_client, shared_setup["viewer_id"])
    _as_viewer(app_client)

    shared_tab = app_client.get("/", params={"tab": "shared"})
    assert "Owner Morning Run" in shared_tab.text
    assert "Owner Evening Run" in shared_tab.text
    assert "Admin" in shared_tab.text  # owner's display name on each row
    for activity_id in shared_setup["activities"]:
        assert f'href="/shared/activities/{activity_id}"' in shared_tab.text
    # Read-only list: no selection checkboxes, export or delete controls, and
    # none of the Mine tab's upload/import cards.
    assert 'class="activity-select"' not in shared_tab.text
    assert "Export" not in shared_tab.text
    assert "Delete selected" not in shared_tab.text
    assert "Upload a GPX" not in shared_tab.text

    mine_tab = app_client.get("/")
    assert "Owner Morning Run" not in mine_tab.text
    assert "No activities yet" in mine_tab.text


def test_shared_detail_page_is_read_only(app_client, shared_setup):
    activity_id = shared_setup["activities"][0]
    _grant_history(app_client, shared_setup["viewer_id"])
    _as_viewer(app_client)

    page = app_client.get(f"/shared/activities/{activity_id}")
    assert page.status_code == 200
    assert "Owner Morning Run" in page.text
    assert "shared by Admin" in page.text
    assert f"/shared/activities/{activity_id}/track" in page.text
    for owner_only in (
        "Download GPX",
        "Delete activity",
        "hx-patch",
        "hx-delete",
        'hx-post="/activities',
        "Add tag",
        f"/api/v1/activities/{activity_id}",
    ):
        assert owner_only not in page.text, owner_only

    track = app_client.get(f"/shared/activities/{activity_id}/track")
    assert track.status_code == 200
    assert track.json()["segments"]
    splits = app_client.get(
        f"/shared/activities/{activity_id}/splits",
        params={"split_type": "distance_km", "split_value": 1},
    )
    assert splits.status_code == 200
    assert app_client.get(f"/shared/activities/{activity_id}/splits/reset").status_code == 200


def test_revoking_applies_to_the_viewers_very_next_request(app_client, shared_setup):
    activity_id = shared_setup["activities"][0]
    viewer_id = shared_setup["viewer_id"]
    _grant_history(app_client, viewer_id)
    _as_viewer(app_client)
    assert app_client.get(f"/shared/activities/{activity_id}").status_code == 200

    _web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    app_client.delete(f"/settings/shares/{viewer_id}", headers=HTMX)

    _as_viewer(app_client)
    assert app_client.get(f"/shared/activities/{activity_id}").status_code == 404
    assert app_client.get(f"/shared/activities/{activity_id}/track").status_code == 404
    assert "Owner Morning Run" not in app_client.get("/", params={"tab": "shared"}).text


def test_per_activity_share_shows_only_that_activity(app_client, shared_setup):
    shared_id, private_id = shared_setup["activities"]
    viewer_id = shared_setup["viewer_id"]
    added = app_client.post(
        f"/activities/{shared_id}/shares", headers=HTMX, data={"viewer_id": viewer_id}
    )
    assert added.status_code == 200
    assert "Vera Viewer" in added.text

    _as_viewer(app_client)
    assert app_client.get(f"/shared/activities/{shared_id}").status_code == 200
    assert app_client.get(f"/shared/activities/{private_id}").status_code == 404
    shared_tab = app_client.get("/", params={"tab": "shared"}).text
    assert "Owner Morning Run" in shared_tab
    assert "Owner Evening Run" not in shared_tab

    _web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    removed = app_client.delete(f"/activities/{shared_id}/shares/{viewer_id}", headers=HTMX)
    assert removed.status_code == 200
    _as_viewer(app_client)
    assert app_client.get(f"/shared/activities/{shared_id}").status_code == 404


def test_owner_detail_page_shows_sharing_controls(app_client, shared_setup):
    activity_id = shared_setup["activities"][0]
    page = app_client.get(f"/activities/{activity_id}")
    assert page.status_code == 200
    assert "Only you can see this activity." in page.text
    assert f'hx-post="/activities/{activity_id}/shares"' in page.text

    _grant_history(app_client, shared_setup["viewer_id"])
    page = app_client.get(f"/activities/{activity_id}")
    assert "Already visible to everyone you share your history with" in page.text
    assert "Vera Viewer" in page.text


def test_viewer_cannot_change_shares_on_someone_elses_activity(app_client, shared_setup):
    activity_id = shared_setup["activities"][0]
    other_id = _create_user("other@example.com", "Otto")
    _grant_history(app_client, shared_setup["viewer_id"])
    _as_viewer(app_client)
    assert (
        app_client.post(
            f"/activities/{activity_id}/shares", headers=HTMX, data={"viewer_id": other_id}
        ).status_code
        == 404
    )
    assert (
        app_client.delete(
            f"/activities/{activity_id}/shares/{shared_setup['viewer_id']}", headers=HTMX
        ).status_code
        == 404
    )


def test_disabled_owner_activities_are_hidden(app_client, shared_setup):
    from app.db import get_session_factory
    from app.repositories.users import SqlAlchemyUserRepository

    activity_id = shared_setup["activities"][0]
    _grant_history(app_client, shared_setup["viewer_id"])
    with get_session_factory()() as session:
        owner = SqlAlchemyUserRepository(session).get_by_email(OWNER_EMAIL)
        assert owner is not None
        owner.disabled_at = datetime.now(UTC)
        session.commit()

    _as_viewer(app_client)
    assert app_client.get(f"/shared/activities/{activity_id}").status_code == 404
    assert "Owner Morning Run" not in app_client.get("/", params={"tab": "shared"}).text


# --- every owner route stays owner-only ------------------------------------


def test_viewer_gets_404_on_every_owner_web_route(app_client, shared_setup):
    activity_id = shared_setup["activities"][0]
    _grant_history(app_client, shared_setup["viewer_id"])
    _as_viewer(app_client)

    assert app_client.get(f"/activities/{activity_id}").status_code == 404
    assert app_client.get(f"/activities/{activity_id}/splits").status_code == 404
    assert app_client.get(f"/activities/{activity_id}/splits/reset").status_code == 404
    assert (
        app_client.patch(
            f"/activities/{activity_id}", headers=HTMX, data={"title": "hijacked"}
        ).status_code
        == 404
    )
    assert (
        app_client.post(
            f"/activities/{activity_id}/tags", headers=HTMX, data={"name": "x"}
        ).status_code
        == 404
    )
    assert app_client.delete(f"/activities/{activity_id}/tags/any", headers=HTMX).status_code == 404
    assert app_client.delete(f"/activities/{activity_id}", headers=HTMX).status_code == 404
    bulk = app_client.post(
        "/activities/bulk-delete", headers=HTMX, data={"activity_ids": [activity_id]}
    )
    assert bulk.status_code == 400

    # Export with a shared activity's id silently drops it: the archive holds
    # nothing of the owner's.
    export = app_client.get("/export", params={"selection": "1", "activity_ids": activity_id})
    assert export.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(export.content)).namelist()
    assert not any(name.endswith(".gpx") for name in names)
    filtered = app_client.get("/export/filtered", params={"tab": "shared"})
    assert filtered.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(filtered.content)).namelist()
    assert not any(name.endswith(".gpx") for name in names)

    _web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    page = app_client.get(f"/activities/{activity_id}")
    assert page.status_code == 200
    assert "hijacked" not in page.text


def test_viewer_gets_404_on_every_owner_api_route(app_client, shared_setup):
    activity_id = shared_setup["activities"][0]
    _grant_history(app_client, shared_setup["viewer_id"])
    headers = _bearer(app_client, "viewer@example.com", VIEWER_PASSWORD)
    base = f"/api/v1/activities/{activity_id}"

    for path in ("", "/gpx", "/analysis", "/track"):
        assert app_client.get(base + path, headers=headers).status_code == 404, path
    assert app_client.patch(base, headers=headers, json={"title": "x"}).status_code == 404
    assert app_client.post(base + "/tags", headers=headers, json={"name": "x"}).status_code == 404
    assert app_client.delete(base, headers=headers).status_code == 404
    export = app_client.post(
        "/api/v1/activities/export", headers=headers, json={"activity_ids": [activity_id]}
    )
    assert export.status_code == 404
    listing = app_client.get("/api/v1/activities", headers=headers)
    assert listing.json()["activities"] == []


# --- the Shared tab's filters ------------------------------------------------


def test_shared_tab_filters_and_preserves_the_tab_in_links(app_client, shared_setup):
    _grant_history(app_client, shared_setup["viewer_id"])
    _as_viewer(app_client)

    found = app_client.get("/", params={"tab": "shared", "q": "evening"})
    assert "Owner Evening Run" in found.text
    assert "Owner Morning Run" not in found.text
    # Sort links carry the tab, or clicking one would jump back to Mine.
    assert "tab=shared" in found.text
    assert 'name="tab" value="shared"' in found.text


def test_shared_tab_owner_filter(app_client, shared_setup, auth_headers, sample_gpx_bytes):
    viewer_id = shared_setup["viewer_id"]
    _grant_history(app_client, viewer_id)

    # A second owner shares one activity with the same viewer.
    second_owner = _create_user("second@example.com", "Sam Second")
    second_headers = _bearer(app_client, "second@example.com", VIEWER_PASSWORD)
    second_activity = upload_sample_activity(app_client, second_headers, sample_gpx_bytes).json()[
        "id"
    ]
    _set_title(second_activity, "Sam's Ride")
    _web_login(app_client, "second@example.com", VIEWER_PASSWORD)
    app_client.post(
        f"/activities/{second_activity}/shares", headers=HTMX, data={"viewer_id": viewer_id}
    )

    _as_viewer(app_client)
    everyone = app_client.get("/", params={"tab": "shared"}).text
    assert "Sam&#39;s Ride" in everyone
    assert "Owner Morning Run" in everyone
    assert f'<option value="{second_owner}"' in everyone

    only_sam = app_client.get("/", params={"tab": "shared", "owner": second_owner}).text
    assert "Sam&#39;s Ride" in only_sam
    assert "Owner Morning Run" not in only_sam

    # An owner id the viewer can't see is ignored, not an error.
    ignored = app_client.get("/", params={"tab": "shared", "owner": "nope"})
    assert ignored.status_code == 200
    assert "Owner Morning Run" in ignored.text


# --- cascades ------------------------------------------------------------


def test_deleting_a_shared_activity_removes_its_shares(app_client, shared_setup, auth_headers):
    web_id, api_id = shared_setup["activities"]
    viewer_id = shared_setup["viewer_id"]
    for activity_id in (web_id, api_id):
        app_client.post(
            f"/activities/{activity_id}/shares", headers=HTMX, data={"viewer_id": viewer_id}
        )

    assert app_client.delete(f"/activities/{web_id}", headers=HTMX).status_code == 200
    assert (
        app_client.delete(f"/api/v1/activities/{api_id}", headers=auth_headers).status_code == 204
    )

    from app.db import get_session_factory
    from app.models.share import ActivityShare

    with get_session_factory()() as session:
        assert session.query(ActivityShare).count() == 0


def test_bulk_delete_of_shared_activities(app_client, shared_setup):
    viewer_id = shared_setup["viewer_id"]
    for activity_id in shared_setup["activities"]:
        app_client.post(
            f"/activities/{activity_id}/shares", headers=HTMX, data={"viewer_id": viewer_id}
        )
    response = app_client.post(
        "/activities/bulk-delete",
        headers=HTMX,
        data={"activity_ids": shared_setup["activities"]},
    )
    assert response.status_code == 200


@pytest.mark.parametrize("via", ["api", "web"])
def test_admin_can_delete_users_with_shares_both_ways(app_client, shared_setup, auth_headers, via):
    viewer_id = shared_setup["viewer_id"]
    _grant_history(app_client, viewer_id)
    app_client.post(
        f"/activities/{shared_setup['activities'][0]}/shares",
        headers=HTMX,
        data={"viewer_id": viewer_id},
    )

    from app.db import get_session_factory
    from app.models.share import ActivityShare, UserShare
    from app.repositories.shares import SqlAlchemyShareRepository
    from app.repositories.users import SqlAlchemyUserRepository

    # The viewer also shares their own history back with the admin, so the
    # deleted user has grants in both directions.
    with get_session_factory()() as session:
        admin = SqlAlchemyUserRepository(session).get_by_email(OWNER_EMAIL)
        assert admin is not None
        SqlAlchemyShareRepository(session).grant_history(viewer_id, admin.id)
        session.commit()

    if via == "api":
        response = app_client.delete(f"/api/v1/admin/users/{viewer_id}", headers=auth_headers)
        assert response.status_code == 204
    else:
        _web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
        response = app_client.delete(f"/admin/users/{viewer_id}", headers=HTMX)
        assert response.status_code == 200

    with get_session_factory()() as session:
        assert session.query(UserShare).count() == 0
        assert session.query(ActivityShare).count() == 0


def test_revoking_history_keeps_a_live_grant(app_client, shared_setup):
    """A row with only Live left is kept; one with neither flag is deleted."""
    from app.db import get_session_factory
    from app.repositories.shares import SqlAlchemyShareRepository
    from app.repositories.users import SqlAlchemyUserRepository

    viewer_id = shared_setup["viewer_id"]
    with get_session_factory()() as session:
        owner = SqlAlchemyUserRepository(session).get_by_email(OWNER_EMAIL)
        assert owner is not None
        shares = SqlAlchemyShareRepository(session)
        shares.grant_history(owner.id, viewer_id)
        share = shares.get(owner.id, viewer_id)
        assert share is not None
        share.can_view_live = True
        session.flush()

        assert shares.revoke_history(owner.id, viewer_id) is True
        kept = shares.get(owner.id, viewer_id)
        assert kept is not None
        assert kept.can_view_live is True
        assert kept.can_view_history is False
        assert shares.revoke_history(owner.id, viewer_id) is False
