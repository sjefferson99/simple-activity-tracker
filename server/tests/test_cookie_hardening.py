"""S8 in docs/SERVER-PRODUCTION-PLAN.md: the session cookie should use the
__Host- prefix whenever it's Secure (Secure + no Domain + Path=/ are exactly
what __Host- requires, and this cookie already satisfies all three), and
logout's delete_cookie must match set_session_cookie's name and flags."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from tests.conftest import run_migrations


def _build_secure_client(tmp_path, monkeypatch) -> TestClient:
    db_path = tmp_path / "secure.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("SR_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SR_SECRET_KEY", "test-secret-key-not-a-real-one-32chars")
    monkeypatch.setenv("SR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("SR_SECURE_COOKIES", "true")

    from app.config import get_settings
    from app.db import get_engine
    from app.main import create_app

    get_settings.cache_clear()
    get_engine.cache_clear()

    run_migrations()

    from app.auth.passwords import hash_password
    from app.db import get_session_factory
    from app.models.user import User
    from app.repositories.users import SqlAlchemyUserRepository

    with get_session_factory()() as session:
        now = datetime.now(UTC)
        user = User(
            email="admin@example.com",
            password_hash=hash_password("admin-password-123"),
            display_name="Admin",
            is_admin=True,
            sessions_invalidated_at=now,
            created_at=now,
        )
        SqlAlchemyUserRepository(session).add(user)
        session.commit()

    return TestClient(create_app())


def test_secure_cookie_uses_host_prefix(tmp_path, monkeypatch):
    from app.config import get_settings
    from app.db import get_engine

    client = _build_secure_client(tmp_path, monkeypatch)
    try:
        with client:
            login = client.post(
                "/login",
                headers={"X-Requested-With": "htmx"},
                data={"email": "admin@example.com", "password": "admin-password-123"},
            )
            assert login.status_code == 200
            set_cookie = login.headers["set-cookie"]
            assert "__Host-sr_session=" in set_cookie
            assert "sr_session=" not in set_cookie.replace("__Host-sr_session=", "")
            assert "Secure" in set_cookie
            assert "Path=/" in set_cookie
            assert "Domain=" not in set_cookie
    finally:
        get_settings.cache_clear()
        get_engine.cache_clear()


def test_logout_deletes_the_host_prefixed_cookie_with_matching_flags(tmp_path, monkeypatch):
    from app.config import get_settings
    from app.db import get_engine

    client = _build_secure_client(tmp_path, monkeypatch)
    try:
        with client:
            login = client.post(
                "/login",
                headers={"X-Requested-With": "htmx"},
                data={"email": "admin@example.com", "password": "admin-password-123"},
            )
            cookie_value = login.headers["set-cookie"].split("__Host-sr_session=")[1].split(";")[0]

            logout = client.post(
                "/logout",
                headers={"X-Requested-With": "htmx", "Cookie": f"__Host-sr_session={cookie_value}"},
            )
            assert logout.status_code == 200
            delete_cookie = logout.headers["set-cookie"]
            assert delete_cookie.startswith("__Host-sr_session=")
            assert "Secure" in delete_cookie
            assert "HttpOnly" in delete_cookie
            assert "samesite=lax" in delete_cookie.lower()

            replay = client.get(
                "/", headers={"Cookie": f"__Host-sr_session={cookie_value}"}, follow_redirects=False
            )
            assert replay.status_code == 303
    finally:
        get_settings.cache_clear()
        get_engine.cache_clear()


def test_insecure_deployment_keeps_the_bare_cookie_name(app_client, auth_headers):
    login = app_client.post(
        "/login",
        headers={"X-Requested-With": "htmx"},
        data={"email": "admin@example.com", "password": "admin-password-123"},
    )
    assert login.status_code == 200
    assert "__Host-sr_session" not in login.headers["set-cookie"]
    assert "sr_session=" in login.headers["set-cookie"]
