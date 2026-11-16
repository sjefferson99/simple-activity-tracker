"""R4 (docs/SERVER-PRODUCTION-PLAN.md): `simple-activity-tracker-server backup <dir>`
writes a timestamped, self-contained snapshot (database + GPX blobs) that can be
copied elsewhere and restored by stopping the app, replacing /data, and starting
it again. D6: SR_AUTO_MIGRATE=false refuses to start a server whose database
isn't already at the latest migration, and the default (true) path takes a
backup before migrating."""

import sqlite3
from pathlib import Path

import pytest

from app.cli import _is_database_at_head, backup, prune_backups
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
    from alembic import command as alembic_command
    from app.cli import _alembic_config, run
    from app.config import get_settings

    monkeypatch.setenv("SR_BACKUP_DIR", str(get_settings().data_dir) + "/backups")
    get_settings.cache_clear()
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)

    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    alembic_command.downgrade(_alembic_config(), "-1")

    run()

    backups = list(Path(get_settings().backup_dir).glob("backup-*"))
    assert len(backups) == 1
    assert _is_database_at_head() is True
    get_settings.cache_clear()


def test_run_skips_backup_when_database_is_already_at_head(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch
) -> None:
    # Issue #207: a restart with nothing to migrate must not write a backup.
    from app.cli import run
    from app.config import get_settings

    monkeypatch.setenv("SR_BACKUP_DIR", str(get_settings().data_dir) + "/backups")
    get_settings.cache_clear()
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)

    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)

    run()

    assert list(Path(get_settings().backup_dir).glob("backup-*")) == []
    get_settings.cache_clear()


def test_run_prunes_old_backups_after_a_pre_migration_backup(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch
) -> None:
    from alembic import command as alembic_command
    from app.cli import _alembic_config, run
    from app.config import get_settings

    backup_dir = Path(get_settings().data_dir) / "backups"
    old = _make_fake_backups(backup_dir, 4)
    monkeypatch.setenv("SR_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("SR_BACKUP_KEEP", "2")
    get_settings.cache_clear()
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)

    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    alembic_command.downgrade(_alembic_config(), "-1")

    run()

    remaining = sorted(p.name for p in backup_dir.glob("backup-*"))
    assert len(remaining) == 2
    assert remaining[0] == old[-1].name  # newest pre-existing one survives
    assert remaining[1] not in {p.name for p in old}  # plus the new backup
    get_settings.cache_clear()


def test_run_starts_even_if_pruning_fails(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch, capsys
) -> None:
    from alembic import command as alembic_command
    from app.cli import _alembic_config, run
    from app.config import get_settings

    backup_dir = Path(get_settings().data_dir) / "backups"
    _make_fake_backups(backup_dir, 3)
    monkeypatch.setenv("SR_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("SR_BACKUP_KEEP", "1")
    get_settings.cache_clear()
    started = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: started.append(True))

    def failing_rmtree(path, *args, **kwargs):
        raise PermissionError(f"denied: {path}")

    monkeypatch.setattr("app.cli.shutil.rmtree", failing_rmtree)

    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    alembic_command.downgrade(_alembic_config(), "-1")

    run()

    assert started == [True]
    assert "could not remove old backup" in capsys.readouterr().out
    assert len(list(backup_dir.glob("backup-*"))) == 4
    get_settings.cache_clear()


def _make_fake_backups(target: Path, count: int) -> list[Path]:
    """Creates `count` backup-<timestamp> dirs, oldest first, all older than
    anything backup() would create now."""
    made = []
    for i in range(count):
        path = target / f"backup-2020010{i + 1}T120000000000Z"
        path.mkdir(parents=True)
        (path / "simple_activity_tracker.db").write_bytes(b"x")
        made.append(path)
    return made


def test_prune_keeps_exactly_the_newest_n_and_ignores_other_entries(tmp_path) -> None:
    backups = _make_fake_backups(tmp_path, 5)
    legacy = tmp_path / "20260903_181135"
    legacy.mkdir()
    notes = tmp_path / "backup-notes.txt"
    notes.write_text("keep me")
    lookalike_file = tmp_path / "backup-20200101T000000000000Z.tar"
    lookalike_file.write_text("not a backup dir")

    removed = prune_backups(str(tmp_path), keep=2)

    assert sorted(removed) == backups[:3]
    assert sorted(p for p in tmp_path.glob("backup-2*") if p.is_dir()) == backups[3:]
    assert legacy.exists()
    assert notes.exists()
    assert lookalike_file.exists()


def test_prune_never_deletes_the_protected_backup_even_if_it_sorts_oldest(tmp_path) -> None:
    # A backup written while the clock is behind can have the oldest name;
    # it's still the one just taken (e.g. right before a migration).
    newer = _make_fake_backups(tmp_path, 3)
    just_written = tmp_path / "backup-20190101T000000000000Z"
    just_written.mkdir()

    removed = prune_backups(str(tmp_path), keep=2, protect=just_written)

    assert just_written.exists()
    assert sorted(removed) == newer[:2]
    assert newer[2].exists()


def test_prune_with_protect_and_keep_one_keeps_only_the_protected(tmp_path) -> None:
    older = _make_fake_backups(tmp_path, 2)
    just_written = tmp_path / "backup-20300101T000000000000Z"
    just_written.mkdir()

    removed = prune_backups(str(tmp_path), keep=1, protect=just_written)

    assert sorted(removed) == older
    assert just_written.exists()


def test_prune_with_keep_zero_keeps_everything(tmp_path) -> None:
    backups = _make_fake_backups(tmp_path, 4)

    assert prune_backups(str(tmp_path), keep=0) == []
    assert all(p.exists() for p in backups)


def test_prune_does_nothing_when_at_or_under_the_limit(tmp_path) -> None:
    backups = _make_fake_backups(tmp_path, 3)

    assert prune_backups(str(tmp_path), keep=3) == []
    assert all(p.exists() for p in backups)


def test_prune_missing_directory_warns_instead_of_raising(tmp_path, capsys) -> None:
    assert prune_backups(str(tmp_path / "missing"), keep=2) == []
    assert "could not list" in capsys.readouterr().out


def test_backup_command_prunes_using_keep_flag(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch, tmp_path
) -> None:
    from app.cli import main

    old = _make_fake_backups(tmp_path, 3)
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    monkeypatch.setattr("sys.argv", ["prog", "backup", str(tmp_path), "--keep", "2"])

    main()

    remaining = sorted(tmp_path.glob("backup-*"))
    assert len(remaining) == 2
    assert remaining[0] == old[-1]


def test_backup_command_defaults_to_sr_backup_keep(
    app_client, auth_headers, sample_gpx_bytes, monkeypatch, tmp_path
) -> None:
    from app.cli import main
    from app.config import get_settings

    _make_fake_backups(tmp_path, 3)
    monkeypatch.setenv("SR_BACKUP_KEEP", "1")
    get_settings.cache_clear()
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    monkeypatch.setattr("sys.argv", ["prog", "backup", str(tmp_path)])

    main()

    assert len(list(tmp_path.glob("backup-*"))) == 1
    get_settings.cache_clear()


def test_backup_keep_rejects_negative_values(monkeypatch) -> None:
    from pydantic import ValidationError

    from app.config import get_settings

    monkeypatch.setenv("SR_BACKUP_KEEP", "-1")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()
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
    from alembic import command as alembic_command
    from app.cli import _alembic_config, run
    from app.config import get_settings

    blocked = tmp_path / "not-a-directory"
    blocked.write_text("occupies the path backup() needs to mkdir")
    monkeypatch.setenv("SR_BACKUP_DIR", str(blocked))
    get_settings.cache_clear()
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)

    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    alembic_command.downgrade(_alembic_config(), "-1")

    try:
        with pytest.raises(SystemExit, match="Pre-migration backup"):
            run()
    finally:
        alembic_command.upgrade(_alembic_config(), "head")
        get_settings.cache_clear()


# Issue #218: an older image started against a database a newer image already
# migrated (switching from :edge back to :latest, or rolling an image back).

_NEWER_REVISION = "f00dfeedcafe"  # not one of this image's migrations


@pytest.fixture
def database_from_newer_version(app_client):
    """Stamps the database with a revision this code doesn't know, as a newer
    server's migration would leave it, and puts the real head back after."""
    from sqlalchemy import text

    from app.db import get_engine

    with get_engine().begin() as connection:
        head = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        connection.execute(
            text("UPDATE alembic_version SET version_num = :rev"), {"rev": _NEWER_REVISION}
        )
    yield
    with get_engine().begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = :rev"), {"rev": head})


def test_unknown_database_revisions_empty_at_head_and_when_behind(app_client) -> None:
    from alembic import command
    from app.cli import _alembic_config, _unknown_database_revisions

    assert _unknown_database_revisions() == []
    command.downgrade(_alembic_config(), "-1")
    try:
        assert _unknown_database_revisions() == []
    finally:
        command.upgrade(_alembic_config(), "head")


def test_unknown_database_revisions_reports_a_newer_revision(database_from_newer_version) -> None:
    from app.cli import _unknown_database_revisions

    assert _unknown_database_revisions() == [_NEWER_REVISION]


def test_run_refuses_a_newer_database_without_writing_or_pruning_backups(
    database_from_newer_version, monkeypatch
) -> None:
    # The crash loop this replaces wrote a backup and pruned an older one on
    # every restart, deleting the pre-switch backups a rollback needs.
    from app.cli import run
    from app.config import get_settings

    backup_dir = Path(get_settings().data_dir) / "backups"
    existing = _make_fake_backups(backup_dir, 4)
    monkeypatch.setenv("SR_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("SR_BACKUP_KEEP", "2")
    get_settings.cache_clear()
    started = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: started.append(True))

    try:
        for _ in range(3):  # several restarts of a crash-looping container
            with pytest.raises(SystemExit, match="newer version has already upgraded it"):
                run()
    finally:
        get_settings.cache_clear()

    assert started == []
    assert sorted(backup_dir.glob("backup-*")) == sorted(existing)


def test_run_refuses_a_newer_database_with_auto_migrate_disabled(
    database_from_newer_version, monkeypatch
) -> None:
    from app.cli import run
    from app.config import get_settings

    monkeypatch.setenv("SR_AUTO_MIGRATE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)

    try:
        # Not the "run `migrate` first" message: migrating can't help here.
        with pytest.raises(SystemExit, match="newer version has already upgraded it"):
            run()
    finally:
        get_settings.cache_clear()


def test_migrate_command_refuses_a_newer_database(database_from_newer_version, monkeypatch) -> None:
    from app.cli import main

    monkeypatch.setattr("sys.argv", ["simple-activity-tracker-server", "migrate"])

    with pytest.raises(SystemExit, match="newer version has already upgraded it"):
        main()


def test_first_boot_starts_without_a_backup_or_a_backup_directory(
    app_client, monkeypatch, tmp_path
) -> None:
    # The newer-database check must not create the database file: `run` would
    # then see an existing un-migrated database and try a pre-migration
    # backup, which fails outright where /backups isn't mounted (the CI
    # smoke test) and is pointless anywhere else.
    from app.cli import _unknown_database_revisions, run
    from app.config import get_settings
    from app.db import get_engine

    fresh_db = tmp_path / "first-boot.db"
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("occupies the path backup() would need to mkdir")
    monkeypatch.setenv("SR_DATABASE_URL", f"sqlite:///{fresh_db}")
    monkeypatch.setenv("SR_BACKUP_DIR", str(blocked))
    get_settings.cache_clear()
    get_engine.cache_clear()
    started = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: started.append(True))

    assert _unknown_database_revisions() == []
    assert not fresh_db.exists()

    run()

    assert started == [True]
    assert _is_database_at_head() is True
