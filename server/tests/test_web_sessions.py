"""Web session (S4) coverage: logout/idle-timeout actually end a session
server-side, not just delete the browser's cookie — see
docs/SERVER-PRODUCTION-PLAN.md S4."""

from datetime import UTC, datetime, timedelta

from app.auth.web_sessions import ABSOLUTE_LIFETIME, IDLE_TIMEOUT

HTMX_HEADERS = {"X-Requested-With": "htmx"}


def _login(app_client, email="admin@example.com", password="admin-password-123"):
    response = app_client.post(
        "/login", headers=HTMX_HEADERS, data={"email": email, "password": password}
    )
    assert response.status_code == 200
    return response.cookies["sr_session"]


def test_logout_revokes_the_session_row(app_client, auth_headers):
    cookie = _login(app_client)

    logout = app_client.post("/logout", headers=HTMX_HEADERS)
    assert logout.status_code == 200

    # A copy of the pre-logout cookie value, presented on a fresh request
    # (simulating a stolen/replayed cookie) must now be rejected — before S4
    # this succeeded for the cookie's full 30-day itsdangerous max_age.
    response = app_client.get("/", cookies={"sr_session": cookie}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_session_survives_across_requests_until_logout(app_client, auth_headers):
    _login(app_client)
    first = app_client.get("/")
    assert first.status_code == 200
    second = app_client.get("/")
    assert second.status_code == 200


def test_idle_timeout_rejects_a_stale_session(app_client, auth_headers):
    cookie = _login(app_client)

    from app.db import get_session_factory
    from app.models.web_session import WebSession

    with get_session_factory()() as session:
        row = session.query(WebSession).filter_by(revoked_at=None).one()
        row.last_seen_at = datetime.now(UTC) - IDLE_TIMEOUT - timedelta(minutes=1)
        session.commit()

    response = app_client.get("/", cookies={"sr_session": cookie}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_absolute_lifetime_rejects_an_old_session(app_client, auth_headers):
    cookie = _login(app_client)

    from app.db import get_session_factory
    from app.models.web_session import WebSession

    with get_session_factory()() as session:
        row = session.query(WebSession).filter_by(revoked_at=None).one()
        old = datetime.now(UTC) - ABSOLUTE_LIFETIME - timedelta(minutes=1)
        row.created_at = old
        row.last_seen_at = old
        session.commit()

    response = app_client.get("/", cookies={"sr_session": cookie}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_settings_page_lists_active_session(app_client, auth_headers):
    _login(app_client)
    response = app_client.get("/settings")
    assert response.status_code == 200
    assert "this device" in response.text


def test_revoking_another_session_signs_it_out(app_client, auth_headers):
    first_cookie = _login(app_client)
    # A second sign-in (e.g. a different browser) creates a second row and
    # becomes this TestClient's current cookie (its jar holds one cookie
    # per name — the second login's Set-Cookie replaces the first).
    second_cookie = _login(app_client)
    assert first_cookie != second_cookie

    from app.auth.sessions import read_session_cookie
    from app.config import get_settings

    first_session_id = read_session_cookie(get_settings().secret_key, first_cookie).session_id

    revoke = app_client.delete(f"/settings/sessions/{first_session_id}", headers=HTMX_HEADERS)
    assert revoke.status_code == 200

    replay = app_client.get("/", cookies={"sr_session": first_cookie}, follow_redirects=False)
    assert replay.status_code == 303


def test_cannot_revoke_own_current_session_via_the_sessions_route(app_client, auth_headers):
    _login(app_client)

    from app.db import get_session_factory
    from app.models.web_session import WebSession

    with get_session_factory()() as session:
        row = session.query(WebSession).filter_by(revoked_at=None).one()
        session_id = row.id

    response = app_client.delete(f"/settings/sessions/{session_id}", headers=HTMX_HEADERS)
    assert response.status_code == 400

    # The session must still work — it wasn't actually revoked.
    still_signed_in = app_client.get("/")
    assert still_signed_in.status_code == 200


def test_password_change_revokes_other_sessions_but_not_this_one(app_client, auth_headers):
    _login(app_client)
    response = app_client.put(
        "/settings/password",
        headers=HTMX_HEADERS,
        data={"current_password": "admin-password-123", "new_password": "new-password-456"},
    )
    assert response.status_code == 200
    assert "sr_session" in response.cookies  # re-minted, so this browser stays signed in

    still_signed_in = app_client.get("/")
    assert still_signed_in.status_code == 200


def test_admin_disable_revokes_the_targets_web_session(app_client, auth_headers):
    create = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "target-web-session@example.com",
            "display_name": "Target",
            "password": "a-strong-password",
            "is_admin": False,
        },
    )
    target_id = create.json()["id"]

    target_cookie = _login(app_client, "target-web-session@example.com", "a-strong-password")

    disable = app_client.patch(
        f"/api/v1/admin/users/{target_id}", headers=auth_headers, json={"disabled": True}
    )
    assert disable.status_code == 200

    response = app_client.get("/", cookies={"sr_session": target_cookie}, follow_redirects=False)
    assert response.status_code == 303
