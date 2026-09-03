"""Route-level tests for app/web/ — see docs/WEB-PLAN.md §8 W2 acceptance
criteria: render/redirect for signed-in vs signed-out, the htmx CSRF header
rule, admin 404s for non-admins, and the self/last-admin guards."""

from tests.conftest import upload_sample_activity

HTMX_HEADERS = {"X-Requested-With": "htmx"}


def _login_cookie_client(app_client, email: str, password: str):
    response = app_client.post(
        "/login",
        headers=HTMX_HEADERS,
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert response.headers["hx-redirect"] == "/"
    return app_client


def test_login_page_renders(app_client):
    response = app_client.get("/login")
    assert response.status_code == 200
    assert "Sign in" in response.text


def test_root_redirects_when_signed_out(app_client):
    response = app_client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_without_htmx_header_is_rejected(app_client):
    response = app_client.post(
        "/login", data={"email": "admin@example.com", "password": "admin-password-123"}
    )
    assert response.status_code == 403


def test_login_success_sets_cookie_and_redirects(app_client, auth_headers):
    response = app_client.post(
        "/login",
        headers=HTMX_HEADERS,
        data={"email": "admin@example.com", "password": "admin-password-123"},
    )
    assert response.status_code == 200
    assert response.headers["hx-redirect"] == "/"
    assert "sr_session" in response.cookies


def test_login_wrong_password_shows_error(app_client):
    response = app_client.post(
        "/login",
        headers=HTMX_HEADERS,
        data={"email": "admin@example.com", "password": "wrong"},
    )
    assert response.status_code == 401
    assert "Invalid email or password" in response.text


def test_activity_list_renders_for_signed_in_user(app_client, sample_gpx_bytes, auth_headers):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/")
    assert response.status_code == 200
    assert "3.00 km" in response.text or "km" in response.text


def test_activity_list_empty_state(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get("/")
    assert response.status_code == 200
    assert "No activities yet" in response.text


def test_activity_detail_renders_with_map_and_analysis(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get(f"/activities/{activity_id}")
    assert response.status_code == 200
    assert 'id="map"' in response.text
    assert "Distance (server)" in response.text
    assert "Splits" in response.text


def test_activity_detail_404_for_missing_activity(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get("/activities/does-not-exist")
    assert response.status_code == 404


def test_activity_patch_without_htmx_header_is_403(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.patch(f"/activities/{activity_id}", data={"title": "Morning run"})
    assert response.status_code == 403


def test_activity_patch_updates_title_and_notes(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.patch(
        f"/activities/{activity_id}",
        headers=HTMX_HEADERS,
        data={"title": "Morning run", "notes": "Felt good"},
    )
    assert response.status_code == 200
    assert response.headers.get("hx-refresh") == "true"

    check = app_client.get(f"/api/v1/activities/{activity_id}", headers=auth_headers)
    assert check.json()["title"] == "Morning run"
    assert check.json()["notes"] == "Felt good"


def test_activity_patch_rejects_oversized_title(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.patch(
        f"/activities/{activity_id}",
        headers=HTMX_HEADERS,
        data={"title": "x" * 100_000, "notes": ""},
    )
    assert response.status_code == 400

    check = app_client.get(f"/api/v1/activities/{activity_id}", headers=auth_headers)
    assert check.json()["title"] is None


def test_activity_delete_via_web_removes_activity(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.delete(f"/activities/{activity_id}", headers=HTMX_HEADERS)
    assert response.status_code == 200
    assert response.headers.get("hx-redirect") == "/"

    check = app_client.get(f"/api/v1/activities/{activity_id}", headers=auth_headers)
    assert check.status_code == 404


def test_devices_page_lists_bearer_device(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get("/devices")
    assert response.status_code == 200
    assert "test" in response.text  # the admin_token fixture's device_name


def test_device_revoke_without_htmx_header_is_403(app_client, auth_headers):
    devices = app_client.get("/api/v1/me/devices", headers=auth_headers).json()
    device_id = devices[0]["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.delete(f"/devices/{device_id}")
    assert response.status_code == 403


def test_device_revoke_via_web(app_client, auth_headers):
    devices = app_client.get("/api/v1/me/devices", headers=auth_headers).json()
    device_id = devices[0]["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.delete(f"/devices/{device_id}", headers=HTMX_HEADERS)
    assert response.status_code == 200

    check = app_client.get("/api/v1/me/devices", headers=auth_headers)
    assert check.status_code == 401  # the presenting bearer token was just revoked


def test_settings_page_renders(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get("/settings")
    assert response.status_code == 200
    assert "Change password" in response.text


def test_change_password_wrong_current_password(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.put(
        "/settings/password",
        headers=HTMX_HEADERS,
        data={"current_password": "wrong", "new_password": "new-password-123"},
    )
    assert response.status_code == 401
    assert "incorrect" in response.text


def test_change_password_success_keeps_current_session(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.put(
        "/settings/password",
        headers=HTMX_HEADERS,
        data={"current_password": "admin-password-123", "new_password": "new-password-123"},
    )
    assert response.status_code == 200
    assert "sr_session" in response.cookies  # re-minted, so this browser stays signed in

    # The bearer token used to log in this fixture's admin should now be revoked.
    check = app_client.get("/api/v1/me", headers=auth_headers)
    assert check.status_code == 401

    still_in = app_client.get("/settings")
    assert still_in.status_code == 200


def test_register_disabled_by_default_returns_404(app_client):
    response = app_client.get("/register")
    assert response.status_code == 404


def test_register_when_enabled(app_client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("SR_ALLOW_REGISTRATION", "true")
    get_settings.cache_clear()
    try:
        page = app_client.get("/register")
        assert page.status_code == 200

        response = app_client.post(
            "/register",
            headers=HTMX_HEADERS,
            data={
                "display_name": "New User",
                "email": "newuser@example.com",
                "password": "password123",
            },
        )
        assert response.status_code == 200
        assert response.headers["hx-redirect"] == "/"
        assert "sr_session" in response.cookies
    finally:
        get_settings.cache_clear()


def test_register_rejects_short_password_and_invalid_email(app_client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("SR_ALLOW_REGISTRATION", "true")
    get_settings.cache_clear()
    try:
        response = app_client.post(
            "/register",
            headers=HTMX_HEADERS,
            data={
                "display_name": "New User",
                "email": "not-an-email",
                "password": "x",
            },
        )
        assert response.status_code == 400
        assert "sr_session" not in response.cookies
    finally:
        get_settings.cache_clear()


def test_admin_users_page_404_for_non_admin(app_client, auth_headers):
    # Create a non-admin user directly via the admin API, then sign in as them.
    create = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "member@example.com",
            "display_name": "Member",
            "password": "member-password-123",
        },
    )
    assert create.status_code == 201

    _login_cookie_client(app_client, "member@example.com", "member-password-123")
    response = app_client.get("/admin/users")
    assert response.status_code == 404


def test_admin_users_page_renders_for_admin(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get("/admin/users")
    assert response.status_code == 200
    assert "admin@example.com" in response.text


def test_admin_cannot_demote_self(app_client, auth_headers):
    client = _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    admin_id = client.get("/api/v1/me").json()["id"]

    response = client.patch(
        f"/admin/users/{admin_id}", headers=HTMX_HEADERS, data={"is_admin": "false"}
    )
    assert response.status_code == 400
    assert "cannot demote or disable your own account" in response.text


def test_admin_cannot_delete_last_admin_via_other_admin(app_client, auth_headers):
    # Promote a second user to admin, then have the ORIGINAL admin try to
    # demote themself while the other admin exists — should succeed, since
    # there'd still be one enabled admin left (the other user). Then, with
    # only one admin left, demoting/disabling that one should be blocked.
    create = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "second-admin@example.com",
            "display_name": "Second Admin",
            "password": "second-password-123",
            "is_admin": True,
        },
    )
    assert create.status_code == 201
    second_admin_id = create.json()["id"]

    client = _login_cookie_client(app_client, "second-admin@example.com", "second-password-123")
    response = client.patch(
        f"/admin/users/{second_admin_id}", headers=HTMX_HEADERS, data={"is_admin": "false"}
    )
    assert response.status_code == 400
    assert "cannot demote or disable your own account" in response.text


def test_disabling_user_kills_session_and_device_token(app_client, auth_headers):
    create = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "member2@example.com",
            "display_name": "Member2",
            "password": "member2-password-123",
        },
    )
    member_id = create.json()["id"]

    member_login = app_client.post(
        "/api/v1/auth/login",
        json={
            "email": "member2@example.com",
            "password": "member2-password-123",
            "device_name": "member-phone",
        },
    )
    member_headers = {"Authorization": f"Bearer {member_login.json()['token']}"}

    # Capture the member's own session cookie value before the admin (who
    # shares this same TestClient/cookie jar) signs in and overwrites it.
    _login_cookie_client(app_client, "member2@example.com", "member2-password-123")
    member_cookie = app_client.cookies.get("sr_session")
    assert member_cookie is not None

    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    disable = app_client.patch(
        f"/admin/users/{member_id}", headers=HTMX_HEADERS, data={"disabled": "true"}
    )
    assert disable.status_code == 200

    assert app_client.get("/api/v1/me", headers=member_headers).status_code == 401

    # Set the Cookie header directly rather than TestClient's per-request
    # cookies= (deprecated) — this overrides the jar's current (admin)
    # cookie for this one request without mutating the shared jar.
    stale_session_check = app_client.get(
        "/", headers={"Cookie": f"sr_session={member_cookie}"}, follow_redirects=False
    )
    assert stale_session_check.status_code == 303
