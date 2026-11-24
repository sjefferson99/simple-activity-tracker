"""Migration a3c7e9f1b5d2 (issue #190): backfills elapsed_seconds and
elevation_gain_m on activity_analyses and the activity_best_efforts table
from each stored result. Runs Alembic directly against a throwaway DB, with
rows inserted before the migration (app_client always migrates straight to
head)."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config

from alembic import command

_SERVER_DIR = Path(__file__).parent.parent
_PRIOR_REVISION = "e8a4c2f7d913"
_MIGRATION_UNDER_TEST = "a3c7e9f1b5d2"


def _alembic_config() -> Config:
    cfg = Config(str(_SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_SERVER_DIR / "alembic"))
    return cfg


def test_backfill_from_stored_results(tmp_path, monkeypatch) -> None:
    from app.config import get_settings

    db_path = tmp_path / "migration_test.db"
    monkeypatch.setenv("SR_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SR_SECRET_KEY", "test-secret-key-not-a-real-one-32chars")
    get_settings.cache_clear()

    cfg = _alembic_config()
    command.upgrade(cfg, _PRIOR_REVISION)

    now = datetime.now(UTC).isoformat()
    done_result = {
        "elapsed_seconds": 930.0,
        "elevation": {"gain_m": 21.5},
        "best_efforts": [
            {"distance_meters": 1000.0, "duration_seconds": 290.0, "avg_speed_mps": 3.4},
            {"distance_meters": 5000.0, "duration_seconds": 1600.0, "avg_speed_mps": 3.1},
        ],
    }
    no_altitude_result = {
        "elapsed_seconds": 60.0,
        "elevation": {"gain_m": None},
        "best_efforts": [],
    }

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO users (id, email, password_hash, display_name, is_admin, "
            "sessions_invalidated_at, created_at) VALUES "
            "('u1', 'u1@example.com', 'x', 'U1', 0, ?, ?)",
            (now, now),
        )
        rows = [
            ("a-done", "c1", "done", json.dumps(done_result)),
            ("a-no-alt", "c2", "done", json.dumps(no_altitude_result)),
            ("a-failed", "c3", "failed", None),
        ]
        for activity_id, client_id, status, result in rows:
            conn.execute(
                "INSERT INTO activities (id, user_id, client_activity_id, started_at, "
                "ended_at, activity_type, client_summary, gpx_blob_key, gpx_sha256, "
                "gpx_bytes, source_platform, source_app_version, created_at, updated_at, "
                "recovered_from_live) "
                "VALUES (?, 'u1', ?, ?, ?, 'running', '{}', 'k', 'h', 1, 'manual', '', ?, ?, 0)",
                (activity_id, client_id, now, now, now, now),
            )
            conn.execute(
                "INSERT INTO activity_analyses (activity_id, analysis_version, status, "
                "result, distance_meters, moving_seconds, computed_at) "
                "VALUES (?, 13, ?, ?, 0, 0, ?)",
                (activity_id, status, result, now),
            )
        conn.commit()

    command.upgrade(cfg, _MIGRATION_UNDER_TEST)

    with sqlite3.connect(db_path) as conn:
        columns = dict(
            (row[0], (row[1], row[2]))
            for row in conn.execute(
                "SELECT activity_id, elapsed_seconds, elevation_gain_m FROM activity_analyses"
            )
        )
        assert columns == {
            "a-done": (930.0, 21.5),
            "a-no-alt": (60.0, None),
            "a-failed": (None, None),
        }
        efforts = sorted(
            conn.execute("SELECT activity_id, distance_m, duration_s FROM activity_best_efforts")
        )
        assert efforts == [("a-done", 1000.0, 290.0), ("a-done", 5000.0, 1600.0)]

    command.downgrade(cfg, _PRIOR_REVISION)
    with sqlite3.connect(db_path) as conn:
        columns_after = {row[1] for row in conn.execute("PRAGMA table_info(activity_analyses)")}
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert not columns_after & {"elapsed_seconds", "elevation_gain_m"}
    assert "activity_best_efforts" not in tables

    get_settings.cache_clear()
