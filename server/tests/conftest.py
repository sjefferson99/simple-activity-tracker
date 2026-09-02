import os
from collections.abc import Generator

import pytest


@pytest.fixture
def app_client(tmp_path, monkeypatch) -> Generator:
    """A TestClient wired to a fresh tmp SQLite DB, migrated to head.

    get_settings()/get_engine() are lru_cache'd process-wide singletons, so
    the caches must be cleared after setting the env vars for this test and
    before anything reads them — otherwise a DB/engine created by an earlier
    test (or import) would leak into this one.
    """
    from app.config import get_settings
    from app.db import get_engine

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SR_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SR_SECRET_KEY", "test-secret")
    get_settings.cache_clear()
    get_engine.cache_clear()

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
