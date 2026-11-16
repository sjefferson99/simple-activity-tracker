import argparse
import re
import shutil
import sqlite3
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings

_SERVER_DIR = Path(__file__).resolve().parent.parent

# How long `run` waits on shutdown for the background reanalysis to finish
# the activity it's on. Inside Docker's default 10 s stop grace period.
_REANALYSIS_SHUTDOWN_GRACE_SECONDS = 5.0


def _alembic_config() -> Config:
    cfg = Config(str(_SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_SERVER_DIR / "alembic"))
    return cfg


def _database_path(database_url: str) -> Path:
    """Extracts the filesystem path from a `sqlite:///...` URL. Backup/restore
    only ever runs against this project's own SQLite deployments (the app has
    no other supported database — see docs/SERVER-PRODUCTION-PLAN.md R4)."""
    if not database_url.startswith("sqlite:///"):
        raise ValueError(f"backup only supports sqlite:/// URLs, got: {database_url}")
    return Path(database_url.removeprefix("sqlite:///"))


def _is_database_at_head() -> bool:
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    from app.db import get_engine

    script = ScriptDirectory.from_config(_alembic_config())
    head = script.get_current_head()
    with get_engine().connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    return current == head


def _unknown_database_revisions() -> list[str]:
    """The database's current migration revision(s) that this image's
    migration scripts don't contain, i.e. revisions written by a *newer*
    server version (issue #218). Empty for a fresh database, one at head, or
    one merely behind."""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    from app.db import get_engine

    # First boot: don't connect. Connecting makes SQLite create an empty
    # database file, which `run` would then mistake for an existing database
    # that needs a pre-migration backup.
    database_url = get_settings().database_url
    if database_url.startswith("sqlite:///") and not _database_path(database_url).exists():
        return []

    script = ScriptDirectory.from_config(_alembic_config())
    known = {revision.revision for revision in script.walk_revisions()}
    with get_engine().connect() as connection:
        current = MigrationContext.configure(connection).get_current_heads()
    return [revision for revision in current if revision not in known]


def _refuse_if_database_is_newer() -> None:
    """Exits before anything touches the database or the backups when it was
    migrated by a newer server version (e.g. switching from `:edge` back to
    `:latest`, or rolling back an image). Must run before the pre-migration
    backup: otherwise each restart of a crash-looping container writes
    another backup and prunes an older one, deleting the backups from before
    the switch, which are the ones a rollback needs (issue #218)."""
    unknown = _unknown_database_revisions()
    if unknown:
        sys.exit(
            f"The database is at migration {', '.join(unknown)}, which this server "
            "version doesn't know: a newer version has already upgraded it. "
            "Refusing to start; nothing was changed and no backup was written. "
            "Run that newer version (e.g. the image tag you used before, such as "
            "`edge`), or restore a backup taken before it upgraded the database "
            "(see deploy/standalone-tls/README.md 'Backups and migration safety')."
        )


def migrate() -> None:
    command.upgrade(_alembic_config(), "head")


def backup(target_dir: str) -> Path:
    """Writes a timestamped, self-contained backup: a consistent snapshot of
    the SQLite database (`VACUUM INTO`, safe to run against a live WAL-mode
    DB — unlike copying the .db file directly, this can't miss data still
    sitting in the -wal file) plus a copy of the GPX blob tree, both under
    one new subdirectory. Returns that subdirectory's path.
    """
    settings = get_settings()
    db_path = _database_path(settings.database_url)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    dest = Path(target_dir) / f"backup-{timestamp}"
    dest.mkdir(parents=True, exist_ok=False)

    db_dest = dest / db_path.name
    with sqlite3.connect(db_path) as conn:
        conn.execute("VACUUM INTO ?", (str(db_dest),))

    gpx_src = Path(settings.data_dir) / "gpx"
    if gpx_src.exists():
        shutil.copytree(gpx_src, dest / "gpx")

    print(f"Backup written to {dest}")
    return dest


# Matches only the names backup() creates (`backup-` + the fixed-width
# `%Y%m%dT%H%M%S%fZ` timestamp), so pruning never touches anything else an
# admin keeps in the backup directory. Fixed width also means sorting the
# names sorts them oldest-first.
_BACKUP_NAME_RE = re.compile(r"^backup-\d{8}T\d{12}Z$")


def prune_backups(target_dir: str, keep: int, *, protect: Path | None = None) -> list[Path]:
    """Deletes the oldest `backup-<timestamp>` directories in target_dir
    beyond the newest `keep` (issue #207). `keep=0` keeps everything.
    `protect` (the backup just written) is never deleted and counts as one
    of the kept: with a clock that has gone backwards its name could sort
    older than existing backups, and it's the one about to matter.
    Best-effort: a failure is reported and skipped, never raised, so a
    pruning problem can't stop the server starting. Returns what was deleted.
    """
    if keep <= 0:
        return []
    try:
        backups = sorted(
            entry
            for entry in Path(target_dir).iterdir()
            if _BACKUP_NAME_RE.match(entry.name) and entry.is_dir() and not entry.is_symlink()
        )
    except OSError as exc:
        print(f"Warning: could not list {target_dir} to prune old backups: {exc}")
        return []

    keep_others = keep
    if protect is not None and protect in backups:
        backups.remove(protect)
        keep_others -= 1
    removed = []
    for old in backups[: max(len(backups) - keep_others, 0)]:
        try:
            shutil.rmtree(old)
        except OSError as exc:
            print(f"Warning: could not remove old backup {old}: {exc}")
            continue
        removed.append(old)
    if removed:
        print(f"Pruned {len(removed)} old backup(s) from {target_dir}, keeping the newest {keep}")
    return removed


def reanalyze(*, activity_id: str | None, all_activities: bool) -> None:
    """Reruns AnalyzerV1 against stored activities (see app/reanalysis.py).
    Exactly one of activity_id/all_activities must be given by the caller
    (main() enforces this). --all only touches stale activities and commits
    each one as it goes (issue #212), so it can be stopped and rerun."""
    from app.reanalysis import reanalyze_activity, reanalyze_stale

    if activity_id is not None:
        if reanalyze_activity(activity_id) is None:
            sys.exit(f"No activity found with id {activity_id}")
        return
    assert all_activities  # noqa: S101 -- enforced by main()'s mutually-exclusive group
    reanalyze_stale()


def gc(*, apply: bool) -> None:
    """Finds blobs on disk with no Activity row pointing at them (orphans
    from an interrupted upload/delete, or a leftover *.tmp from a crash
    mid-write) and rows whose blob is missing from disk. Orphan blobs are
    deleted only when --apply is passed; otherwise this is a dry run that
    only reports what it found. Rows with a missing blob are always just
    reported (there's no safe automatic fix — see docs/SERVER-PRODUCTION-PLAN.md R1).
    """
    from sqlalchemy import select

    from app.db import get_session_factory
    from app.models.activity import Activity

    data_dir = Path(get_settings().data_dir)
    gpx_dir = data_dir / "gpx"

    with get_session_factory()() as session:
        rows = list(session.execute(select(Activity.gpx_blob_key)).scalars())
    referenced = {data_dir / "gpx" / key for key in rows}

    on_disk = {p for p in gpx_dir.rglob("*") if p.is_file()} if gpx_dir.exists() else set()
    orphans = sorted(p for p in on_disk if p not in referenced)
    missing = sorted(p for p in referenced if p not in on_disk)

    if missing:
        print(f"{len(missing)} activity row(s) reference a missing blob:")
        for path in missing:
            print(f"  MISSING: {path}")
    if orphans:
        verb = "Deleting" if apply else "Would delete"
        print(f"{len(orphans)} orphan blob(s) with no activity row ({verb.lower()}):")
        for path in orphans:
            print(f"  {verb}: {path}")
            if apply:
                path.unlink(missing_ok=True)
    if not missing and not orphans:
        print("No orphan blobs or missing blobs found.")
    elif orphans and not apply:
        print("Re-run with --apply to delete the orphan blob(s) listed above.")


def run() -> None:
    """validate config -> migrate (or refuse to start if behind) -> bootstrap
    admin -> serve, reanalysing stale activities in the background."""
    import uvicorn
    from pydantic import ValidationError

    from app.audit import configure_logging
    from app.auth.bootstrap import bootstrap_admin_if_needed
    from app.db import get_session_factory

    try:
        settings = get_settings()
    except ValidationError as exc:
        sys.exit(f"Invalid configuration: {exc}")

    configure_logging(settings.log_level)

    _refuse_if_database_is_newer()
    if settings.auto_migrate:
        # Only back up when there's a migration to protect against (issue
        # #207): an up-to-date database starts without writing a full copy.
        if (
            settings.backup_before_migrate
            and _database_path(settings.database_url).exists()
            and not _is_database_at_head()
        ):
            try:
                written = backup(settings.backup_dir)
            except OSError as exc:
                sys.exit(
                    f"Pre-migration backup to {settings.backup_dir!r} failed: {exc}. "
                    "Make sure that directory is mounted and writable (see "
                    "deploy/standalone-tls/README.md 'Backups and migration safety'), "
                    "or set SR_BACKUP_BEFORE_MIGRATE=false to skip it (not recommended)."
                )
            prune_backups(settings.backup_dir, settings.backup_keep, protect=written)
        migrate()
    elif not _is_database_at_head():
        sys.exit(
            "Database is not at the latest migration and SR_AUTO_MIGRATE=false — "
            "refusing to start. Run `simple-activity-tracker-server migrate` first."
        )

    with get_session_factory()() as session:
        bootstrap_admin_if_needed(session)

    reanalysis_stop = threading.Event()
    reanalysis_thread = None
    if settings.auto_reanalyze:
        # Picks up any activity whose stored ActivityAnalysis predates the
        # current ANALYSIS_VERSION (a bumped analyzer version ships in the
        # same release as the code that reads it), so an analyzer bugfix or
        # algorithm change (e.g. issue #83) reaches every existing user's
        # already-uploaded activities on upgrade, with no manual CLI step
        # and no re-upload from the phone. A fast no-op when nothing is
        # stale. Runs in the background while the app serves (issues #206,
        # #213): on a large account it takes minutes, and blocking until it
        # finished left /healthz silent long enough for the container to be
        # marked unhealthy and compose to never start the proxy. Pages show
        # an activity's previous analysis until its turn comes.
        from app.reanalysis import start_background_reanalysis

        reanalysis_thread = start_background_reanalysis(reanalysis_stop)

    forwarded_allow_ips = settings.trusted_proxies or None
    try:
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",  # noqa: S104 -- must bind all interfaces inside the container to be reachable
            port=8000,
            log_level=settings.log_level,
            proxy_headers=bool(forwarded_allow_ips),
            forwarded_allow_ips=forwarded_allow_ips,
        )
    finally:
        # Let the activity in progress commit rather than dying mid-way;
        # anything left is picked up on the next start (issue #212).
        reanalysis_stop.set()
        if reanalysis_thread is not None:
            reanalysis_thread.join(timeout=_REANALYSIS_SHUTDOWN_GRACE_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(prog="simple-activity-tracker-server")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="Run migrations, then serve the app.")
    subparsers.add_parser("migrate", help="Run pending migrations and exit.")

    reanalyze_parser = subparsers.add_parser(
        "reanalyze", help="Rerun the current analyzer against stored activities."
    )
    reanalyze_group = reanalyze_parser.add_mutually_exclusive_group(required=True)
    reanalyze_group.add_argument(
        "--activity", metavar="ID", help="Reanalyze a single activity by id."
    )
    reanalyze_group.add_argument(
        "--all",
        action="store_true",
        help=(
            "Reanalyze every activity whose stored analysis_version is older than the current one."
        ),
    )

    gc_parser = subparsers.add_parser(
        "gc", help="Find (and optionally delete) GPX blobs with no activity row."
    )
    gc_parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete orphan blobs (default is a dry run that only reports them).",
    )

    backup_parser = subparsers.add_parser(
        "backup",
        help="Write a timestamped backup (database + GPX blobs) to the given directory.",
    )
    backup_parser.add_argument(
        "directory", help="Directory the timestamped backup subdirectory is created under."
    )
    backup_parser.add_argument(
        "--keep",
        type=int,
        metavar="N",
        default=None,
        help=(
            "After backing up, keep only the newest N backup-<timestamp> directories "
            "there (0 keeps all). Defaults to SR_BACKUP_KEEP (5)."
        ),
    )

    args = parser.parse_args()
    if args.command == "run":
        run()
    elif args.command == "migrate":
        _refuse_if_database_is_newer()
        migrate()
    elif args.command == "reanalyze":
        from app.audit import configure_logging

        configure_logging(get_settings().log_level)  # progress is logged under app.reanalysis
        reanalyze(activity_id=args.activity, all_activities=args.all)
    elif args.command == "gc":
        gc(apply=args.apply)
    elif args.command == "backup":
        if args.keep is not None and args.keep < 0:
            parser.error("--keep must be 0 or more")
        written = backup(args.directory)
        keep = args.keep if args.keep is not None else get_settings().backup_keep
        prune_backups(args.directory, keep, protect=written)
    else:  # pragma: no cover - argparse enforces this
        sys.exit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
