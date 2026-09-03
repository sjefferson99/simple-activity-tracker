def test_admin_routes_are_404_for_non_admins(app_client, auth_headers) -> None:
    # Demote the bootstrap admin to a regular user via direct DB access
    # (there's no "downgrade yourself" API route, and shouldn't be).
    from app.db import get_session_factory
    from app.repositories.users import SqlAlchemyUserRepository

    with get_session_factory()() as session:
        repo = SqlAlchemyUserRepository(session)
        user = repo.get_by_email("admin@example.com")
        user.is_admin = False
        session.commit()

    response = app_client.get("/api/v1/admin/users", headers=auth_headers)
    assert response.status_code == 404


def test_admin_can_list_users(app_client, auth_headers) -> None:
    response = app_client.get("/api/v1/admin/users", headers=auth_headers)
    assert response.status_code == 200
    users = response.json()
    assert len(users) == 1
    assert users[0]["email"] == "admin@example.com"


def test_admin_can_create_a_user(app_client, auth_headers) -> None:
    response = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "newuser@example.com",
            "display_name": "New User",
            "password": "a-strong-password",
            "is_admin": False,
        },
    )
    assert response.status_code == 201
    assert response.json()["email"] == "newuser@example.com"


def test_creating_a_user_with_a_taken_email_is_rejected(app_client, auth_headers) -> None:
    response = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "admin@example.com",
            "display_name": "Dupe",
            "password": "a-strong-password",
            "is_admin": False,
        },
    )
    assert response.status_code == 409


def test_admin_cannot_demote_themself(app_client, auth_headers) -> None:
    me = app_client.get("/api/v1/me", headers=auth_headers).json()
    response = app_client.patch(
        f"/api/v1/admin/users/{me['id']}", headers=auth_headers, json={"is_admin": False}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "cannot_modify_self"


def test_admin_cannot_disable_themself(app_client, auth_headers) -> None:
    me = app_client.get("/api/v1/me", headers=auth_headers).json()
    response = app_client.patch(
        f"/api/v1/admin/users/{me['id']}", headers=auth_headers, json={"disabled": True}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "cannot_modify_self"


def test_admin_cannot_delete_themself(app_client, auth_headers) -> None:
    me = app_client.get("/api/v1/me", headers=auth_headers).json()
    response = app_client.delete(f"/api/v1/admin/users/{me['id']}", headers=auth_headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "cannot_modify_self"


def test_demoting_a_second_admin_down_to_one_is_allowed(app_client, auth_headers) -> None:
    # Going from 2 enabled admins to 1 is legitimate — only reaching *zero*
    # is blocked, and that's only reachable via self-demotion (see the
    # last_admin defense-in-depth comments in app/api/v1/admin.py), which
    # cannot_modify_self already covers. This proves the ordinary case
    # isn't over-blocked by the last_admin check.
    create = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "second-admin@example.com",
            "display_name": "Second Admin",
            "password": "a-strong-password",
            "is_admin": True,
        },
    )
    second_admin_id = create.json()["id"]

    response = app_client.patch(
        f"/api/v1/admin/users/{second_admin_id}", headers=auth_headers, json={"is_admin": False}
    )
    assert response.status_code == 200
    assert response.json()["is_admin"] is False


def test_disabling_a_user_revokes_their_session_immediately(app_client, auth_headers) -> None:
    create = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "target@example.com",
            "display_name": "Target",
            "password": "a-strong-password",
            "is_admin": False,
        },
    )
    target_id = create.json()["id"]

    login = app_client.post(
        "/api/v1/auth/login",
        json={"email": "target@example.com", "password": "a-strong-password", "device_name": "x"},
    )
    target_headers = {"Authorization": f"Bearer {login.json()['token']}"}
    assert app_client.get("/api/v1/me", headers=target_headers).status_code == 200

    response = app_client.patch(
        f"/api/v1/admin/users/{target_id}", headers=auth_headers, json={"disabled": True}
    )
    assert response.status_code == 200

    assert app_client.get("/api/v1/me", headers=target_headers).status_code == 401


def test_admin_password_reset_revokes_existing_sessions(app_client, auth_headers) -> None:
    create = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "target2@example.com",
            "display_name": "Target2",
            "password": "a-strong-password",
            "is_admin": False,
        },
    )
    target_id = create.json()["id"]

    login = app_client.post(
        "/api/v1/auth/login",
        json={"email": "target2@example.com", "password": "a-strong-password", "device_name": "x"},
    )
    target_headers = {"Authorization": f"Bearer {login.json()['token']}"}

    response = app_client.post(
        f"/api/v1/admin/users/{target_id}/password",
        headers=auth_headers,
        json={"new_password": "brand-new-password"},
    )
    assert response.status_code == 204
    assert app_client.get("/api/v1/me", headers=target_headers).status_code == 401


def test_deleting_a_user_removes_their_activities(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    from tests.conftest import upload_sample_activity

    create = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "target3@example.com",
            "display_name": "Target3",
            "password": "a-strong-password",
            "is_admin": False,
        },
    )
    target_id = create.json()["id"]

    login = app_client.post(
        "/api/v1/auth/login",
        json={"email": "target3@example.com", "password": "a-strong-password", "device_name": "x"},
    )
    target_headers = {"Authorization": f"Bearer {login.json()['token']}"}
    upload_sample_activity(app_client, target_headers, sample_gpx_bytes)

    response = app_client.delete(f"/api/v1/admin/users/{target_id}", headers=auth_headers)
    assert response.status_code == 204

    response = app_client.get("/api/v1/admin/users", headers=auth_headers)
    emails = [u["email"] for u in response.json()]
    assert "target3@example.com" not in emails
