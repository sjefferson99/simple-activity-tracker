import json
import os
from collections.abc import Generator
from datetime import UTC
from pathlib import Path

import pytest

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def app_client(tmp_path, monkeypatch) -> Generator:
    """A TestClient wired to a fresh tmp SQLite DB (migrated to head) and a
    fresh tmp blob dir.

    get_settings()/get_engine() are lru_cache'd process-wide singletons, so
    the caches must be cleared after setting the env vars for this test and
    before anything reads them — otherwise a DB/engine created by an earlier
    test (or import) would leak into this one.
    """
    from app.auth.rate_limit import login_rate_limiter
    from app.config import get_settings
    from app.db import get_engine

    db_path = tmp_path / "test.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("SR_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SR_SECRET_KEY", "test-secret")
    monkeypatch.setenv("SR_DATA_DIR", str(data_dir))
    # TestClient talks plain http://testserver — a Secure cookie set over
    # that would be silently dropped by the client's cookie jar (per RFC,
    # respected by http.cookiejar), breaking every session-cookie-based web
    # test. Mirrors the real "plain-http LAN testing" setting from
    # docs/WEB-PLAN.md §5.5.
    monkeypatch.setenv("SR_SECURE_COOKIES", "false")
    get_settings.cache_clear()
    get_engine.cache_clear()
    # login_rate_limiter is a module-level singleton (see app/auth/rate_limit.py)
    # shared across the whole test process — reset it so one test's login
    # attempts don't count against the next test's budget.
    login_rate_limiter.reset()

    from alembic.config import Config
    from fastapi.testclient import TestClient

    from alembic import command
    from app.main import create_app

    server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_cfg = Config(os.path.join(server_dir, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(server_dir, "alembic"))
    command.upgrade(alembic_cfg, "head")

    with TestClient(create_app()) as client:
        yield client

    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture
def admin_token(app_client, monkeypatch) -> str:
    """Bootstraps an admin user directly in the DB (not via the API, since
    there's no self-registration route for the first user) and returns a
    fresh device token for it."""
    from datetime import datetime

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

    response = app_client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@example.com",
            "password": "admin-password-123",
            "device_name": "test",
        },
    )
    assert response.status_code == 200
    token: str = response.json()["token"]
    return token


@pytest.fixture
def auth_headers(admin_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def sample_gpx_bytes() -> bytes:
    return (_FIXTURE_DIR / "sample_run.gpx").read_bytes()


def make_summary(client_run_id: str = "11111111-1111-1111-1111-111111111111") -> dict:
    return {
        "client_run_id": client_run_id,
        "started_at": "2026-01-01T07:00:00Z",
        "ended_at": "2026-01-01T07:16:30Z",
        "moving_seconds": 900.0,
        "distance_meters": 3000.0,
        "avg_speed_mps": 3.33,
        "splits": [{"index": 1, "duration_seconds": 300.0, "avg_speed_mps": 3.33}],
        "source": {"platform": "android", "app_version": "1.0.0+1"},
    }


def upload_sample_run(
    app_client,
    headers,
    sample_gpx_bytes,
    client_run_id: str = "11111111-1111-1111-1111-111111111111",
):
    return app_client.post(
        "/api/v1/runs",
        headers=headers,
        data={"summary": json.dumps(make_summary(client_run_id))},
        files={"gpx": ("run.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
