"""Migration 5a6b3dd72c96 (issue #76): backfills start_lat/start_lon/end_lat/
end_lon on activity_analyses from the R8 track cache's first/last points.
Runs Alembic directly against a throwaway tmp DB rather than using the
app_client fixture, since the point is to check the migration's own SQL
against rows inserted *before* it runs — app_client always migrates straight
to head."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config

from alembic import command

_SERVER_DIR = Path(__file__).parent.parent
_PRIOR_REVISION = "0aff3bc612d3"  # immediately before the migration under test
_MIGRATION_UNDER_TEST = "5a6b3dd72c96"


def _alembic_config() -> Config:
    cfg = Config(str(_SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_SERVER_DIR / "alembic"))
    return cfg


def test_backfill_populates_coordinates_from_the_cached_track(tmp_path, monkeypatch) -> None:
    from app.config import get_settings

    db_path = tmp_path / "migration_test.db"
    monkeypatch.setenv("SR_DATABASE_URL", f"sqlite:///{db_path}")
    # alembic/env.py reads app.config.get_settings().database_url, which
    # requires SR_SECRET_KEY even though this migration never touches it —
    # get_settings is a process-wide lru_cache, so it must be cleared after
    # setting the env var (see tests/conftest.py's app_client fixture for
    # the same pattern) or an earlier test's cached Settings would win.
    monkeypatch.setenv("SR_SECRET_KEY", "test-secret-key-not-a-real-one-32chars")
    get_settings.cache_clear()

    cfg = _alembic_config()
    command.upgrade(cfg, _PRIOR_REVISION)

    now = datetime.now(UTC).isoformat()
    track = {
        "segments": [
            [{"lat": 51.10, "lon": -2.10, "ele": 10.0, "t": 0.0}],
            [
                {"lat": 51.30, "lon": -2.30, "ele": 12.0, "t": 30.0},
                {"lat": 51.40, "lon": -2.40, "ele": 15.0, "t": 60.0},
            ],
        ]
    }

    with sqlite3.connect(db_path) as conn:
        # Minimal users/activities rows to satisfy the FK columns — content
        # of these doesn't matter for this migration, only that
        # activity_analyses rows exist with the shapes the backfill targets.
        conn.execute(
            "INSERT INTO users (id, email, password_hash, display_name, is_admin, "
            "sessions_invalidated_at, created_at) VALUES "
            "('u1', 'u1@example.com', 'x', 'U1', 0, ?, ?)",
            (now, now),
        )
        for activity_id, client_id in [("a-with-track", "c1"), ("a-without-track", "c2")]:
            conn.execute(
                "INSERT INTO activities (id, user_id, client_activity_id, started_at, "
                "ended_at, activity_type, client_summary, gpx_blob_key, gpx_sha256, "
                "gpx_bytes, source_platform, source_app_version, created_at, updated_at) "
                "VALUES (?, 'u1', ?, ?, ?, 'running', '{}', 'k', 'h', 1, 'manual', '', ?, ?)",
                (activity_id, client_id, now, now, now, now),
            )
        conn.execute(
            "INSERT INTO activity_analyses (activity_id, analysis_version, status, "
            "result, distance_meters, moving_seconds, track, computed_at) "
            "VALUES ('a-with-track', 4, 'done', '{}', 0, 0, ?, ?)",
            (json.dumps(track), now),
        )
        conn.execute(
            "INSERT INTO activity_analyses (activity_id, analysis_version, status, "
            "result, distance_meters, moving_seconds, track, computed_at) "
            "VALUES ('a-without-track', 4, 'done', '{}', 0, 0, NULL, ?)",
            (now,),
        )
        conn.commit()

    command.upgrade(cfg, _MIGRATION_UNDER_TEST)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT start_lat, start_lon, end_lat, end_lon FROM activity_analyses "
            "WHERE activity_id = 'a-with-track'"
        ).fetchone()
        assert row == (51.10, -2.10, 51.40, -2.40)

        null_row = conn.execute(
            "SELECT start_lat, start_lon, end_lat, end_lon FROM activity_analyses "
            "WHERE activity_id = 'a-without-track'"
        ).fetchone()
        assert null_row == (None, None, None, None)

    # Downgrade must cleanly drop the four columns again.
    command.downgrade(cfg, _PRIOR_REVISION)
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(activity_analyses)")}
    assert not columns & {"start_lat", "start_lon", "end_lat", "end_lon"}

    get_settings.cache_clear()
