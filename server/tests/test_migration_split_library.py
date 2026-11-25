"""Migration f3b7d1c9e2a4 (issue #143): existing split configs keep their id as
their uid, keep their name uniqueness, and survive a downgrade."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

_SERVER_DIR = Path(__file__).parent.parent
_PRIOR_REVISION = "c4e8a2d6f0b1"
_MIGRATION_UNDER_TEST = "f3b7d1c9e2a4"


def _alembic_config() -> Config:
    cfg = Config(str(_SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_SERVER_DIR / "alembic"))
    return cfg


def test_existing_configs_get_uid_and_keep_unique_names(tmp_path, monkeypatch) -> None:
    from app.config import get_settings

    db_path = tmp_path / "migration_test.db"
    monkeypatch.setenv("SR_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SR_SECRET_KEY", "test-secret-key-not-a-real-one-32chars")
    get_settings.cache_clear()
    cfg = _alembic_config()
    command.upgrade(cfg, _PRIOR_REVISION)

    now = datetime.now(UTC).isoformat()
    plan = json.dumps({"split_type": "distance_km", "split_value": 1, "custom_splits": []})
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO users (id, email, password_hash, display_name, is_admin, "
            "sessions_invalidated_at, created_at) VALUES "
            "('u1', 'u1@example.com', 'x', 'U1', 0, ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO split_configs (id, user_id, name, plan, created_at, updated_at) "
            "VALUES ('c1', 'u1', 'Tempo', ?, ?, ?)",
            (plan, now, now),
        )

    command.upgrade(cfg, _MIGRATION_UNDER_TEST)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT uid, folder, source_id FROM split_configs WHERE id = 'c1'"
        ).fetchone()
        assert row == ("c1", None, None)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO split_configs (id, user_id, name, plan, created_at, updated_at, uid) "
                "VALUES ('c2', 'u1', 'Tempo', ?, ?, ?, 'x2')",
                (plan, now, now),
            )

    command.downgrade(cfg, _PRIOR_REVISION)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT name FROM split_configs").fetchall() == [("Tempo",)]
    get_settings.cache_clear()
