"""R4 (docs/SERVER-PRODUCTION-PLAN.md): `simple-activity-tracker-server backup <dir>`
writes a timestamped, self-contained snapshot (database + GPX blobs) that can be
copied elsewhere and restored by stopping the app, replacing /data, and starting
it again. D6: SR_AUTO_MIGRATE=false refuses to start a server whose database
isn't already at the latest migration, and the default (true) path takes a
backup before migrating."""

import sqlite3
from pathlib import Path

import pytest

from app.cli import _is_database_at_head, backup
from tests.conftest import upload_sample_activity


def test_backup_produces_a_restorable_database_and_blobs(
    app_client, auth_headers, sample_gpx_bytes, tmp_path
) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()

    from app.config import get_settings
    from app.db import get_session_factory
    from app.models.activity import Activity

    with get_session_factory()() as session:
        activity = session.get(Activity, created["id"])
        assert activity is not None
        blob_key = activity.gpx_blob_key

    backup_target = tmp_path / "backups"
    dest = backup(str(backup_target))

    db_path = Path(get_settings().database_url.removeprefix("sqlite:///"))
    backed_up_db = dest / db_path.name
    assert backed_up_db.exists()

    with sqlite3.connect(backed_up_db) as conn:
        rows = conn.execute("SELECT id FROM activities WHERE id = ?", (created["id"],)).fetchall()
    assert rows == [(created["id"],)]

    backed_up_blob = dest / "gpx" / blob_key
    assert backed_up_blob.read_bytes() == sample_gpx_bytes


def test_backup_captures_data_written_before_wal_checkpoint(
    app_client, auth_headers, sample_gpx_bytes, tmp_path
) -> None:
    # VACUUM INTO must see committed rows even if they're still sitting in the
    # WAL file and haven't been checkpointed into the main .db file yet — a
    # plain file copy of the .db alone could miss them (the reason R4 rejects
    # that approach).
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)

    dest = backup(str(tmp_path / "backups"))

    from app.config import get_settings

    db_path = Path(get_settings().database_url.removeprefix("sqlite:///"))
    with sqlite3.connect(dest / db_path.name) as conn:
        count = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    assert count == 1


def test_backup_creates_a_distinct_timestamped_subdirectory(
    app_client, auth_headers, sample_gpx_bytes, tmp_path
) -> None:
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)

    target = tmp_path / "backups"
    first = backup(str(target))
    second = backup(str(target))

    assert first != second
    assert first.exists()
    assert second.exists()


def test_is_database_at_head_true_after_migration(app_client) -> None:
    assert _is_database_at_head() is True


def test_is_database_at_head_false_when_behind(app_client) -> None:
    from alembic import command
    from app.cli import _alembic_config

    command.downgrade(_alembic_config(), "-1")
    try:
        assert _is_database_at_head() is False
    finally:
        command.upgrade(_alembic_config(), "head")


def test_run_refuses_to_start_when_behind_head_and_auto_migrate_disabled(
    app_client, monkeypatch
) -> None:
    from alembic import command as alembic_command
    from app.cli import _alembic_config, run
    from app.config import get_settings

    monkeypatch.setenv("SR_AUTO_MIGRATE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)

    alembic_command.downgrade(_alembic_config(), "-1")
    try:
        with pytest.raises(SystemExit, match="SR_AUTO_MIGRATE=false"):
            run()
    finally:
        alembic_command.upgrade(_alembic_config(), "head")
        get_settings.cache_clear()


def test_run_starts_when_at_head_and_auto_migrate_disabled(app_client, monkeypatch) -> None:
    from app.cli import run
    from app.config import get_settings

    monkeypatch.setenv("SR_AUTO_MIGRATE", "false")
    get_settings.cache_clear()
    started = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: started.append(True))

    run()

    assert started == [True]
    get_settings.cache_clear()


def test_run_backs_up_before_migrating_by_default(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch
) -> None:
    from app.cli import run
    from app.config import get_settings

    monkeypatch.setenv("SR_BACKUP_DIR", str(get_settings().data_dir) + "/backups")
    get_settings.cache_clear()
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)

    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)

    run()

    backups = list(Path(get_settings().backup_dir).glob("backup-*"))
    assert len(backups) == 1
    get_settings.cache_clear()


def test_run_exits_cleanly_when_backup_directory_is_not_writable(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch, tmp_path
) -> None:
    # A deployment that forgets to mount SR_BACKUP_DIR (or a permissions
    # mismatch) must fail with a clear message pointing at the fix, not a
    # raw traceback — this reproduces the real failure hit when manually
    # testing against a container with /data but no /backups mount. A file
    # standing where a directory is expected reproduces "can't create this
    # path" portably (Windows doesn't honor chmod the way Linux does).
    from app.cli import run
    from app.config import get_settings

    blocked = tmp_path / "not-a-directory"
    blocked.write_text("occupies the path backup() needs to mkdir")
    monkeypatch.setenv("SR_BACKUP_DIR", str(blocked))
    get_settings.cache_clear()
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)

    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)

    with pytest.raises(SystemExit, match="Pre-migration backup"):
        run()
    get_settings.cache_clear()
