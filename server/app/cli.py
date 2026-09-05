import argparse
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from sqlalchemy import select

from alembic import command
from app.config import get_settings

_SERVER_DIR = Path(__file__).resolve().parent.parent


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


def reanalyze(*, activity_id: str | None, all_activities: bool) -> None:
    """Reruns AnalyzerV1 against stored activities, per docs/WEB-PLAN.md §5.4:
    the extensibility hook for algorithm changes (a bumped ANALYSIS_VERSION, a
    fixed bug in the analyzer) to reach activities that were already analysed
    under an older version, without needing a re-upload from the phone —
    the GPX itself never changes, only what's derived from it. Exactly one
    of activity_id/all_activities must be given by the caller (main() enforces
    this).
    """
    from app.analysis.gpx_parser import GpxParseError, parse_gpx
    from app.analysis.v1 import ANALYSIS_VERSION, AnalyzerV1
    from app.db import get_session_factory
    from app.models.activity import Activity
    from app.models.activity_analysis import ActivityAnalysis, AnalysisStatus
    from app.storage.blob_store import LocalFileBlobStore

    blob_store = LocalFileBlobStore(Path(get_settings().data_dir))
    analyzer = AnalyzerV1()

    with get_session_factory()() as session:
        if activity_id is not None:
            activity = session.get(Activity, activity_id)
            activities = [activity] if activity is not None else []
            if not activities:
                sys.exit(f"No activity found with id {activity_id}")
        else:
            assert all_activities  # noqa: S101 -- enforced by main()'s mutually-exclusive group
            stmt = (
                select(Activity)
                .outerjoin(ActivityAnalysis, ActivityAnalysis.activity_id == Activity.id)
                .where(
                    (ActivityAnalysis.activity_id.is_(None))
                    | (ActivityAnalysis.analysis_version < ANALYSIS_VERSION)
                )
            )
            activities = list(session.execute(stmt).scalars())

        print(
            f"Reanalyzing {len(activities)} activity(ies) at analysis_version={ANALYSIS_VERSION}..."
        )
        for activity in activities:
            try:
                gpx_bytes = blob_store.get(activity.gpx_blob_key)
                track = parse_gpx(gpx_bytes)
                result = analyzer.analyze(track)
                status = AnalysisStatus.done
                error = None
            except (GpxParseError, OSError, ValueError) as exc:
                result = None
                status = AnalysisStatus.failed
                error = str(exc)
                print(f"  {activity.id}: FAILED — {exc}")

            existing = session.get(ActivityAnalysis, activity.id)
            if existing is None:
                existing = ActivityAnalysis(activity_id=activity.id, computed_at=datetime.now(UTC))
                session.add(existing)
            existing.analysis_version = ANALYSIS_VERSION
            existing.status = status
            existing.result = result
            existing.error = error
            existing.computed_at = datetime.now(UTC)

            if status == AnalysisStatus.done:
                print(f"  {activity.id}: done")

        session.commit()


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
    """validate config -> migrate (or refuse to start if behind) -> bootstrap admin -> serve."""
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

    if settings.auto_migrate:
        if settings.backup_before_migrate and _database_path(settings.database_url).exists():
            try:
                backup(settings.backup_dir)
            except OSError as exc:
                sys.exit(
                    f"Pre-migration backup to {settings.backup_dir!r} failed: {exc}. "
                    "Make sure that directory is mounted and writable (see "
                    "deploy/standalone-tls/README.md 'Backups and migration safety'), "
                    "or set SR_BACKUP_BEFORE_MIGRATE=false to skip it (not recommended)."
                )
        migrate()
    elif not _is_database_at_head():
        sys.exit(
            "Database is not at the latest migration and SR_AUTO_MIGRATE=false — "
            "refusing to start. Run `simple-activity-tracker-server migrate` first."
        )

    with get_session_factory()() as session:
        bootstrap_admin_if_needed(session)

    settings = get_settings()
    forwarded_allow_ips = settings.trusted_proxies or None
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104 -- must bind all interfaces inside the container to be reachable
        port=8000,
        log_level=settings.log_level,
        proxy_headers=bool(forwarded_allow_ips),
        forwarded_allow_ips=forwarded_allow_ips,
    )


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

    args = parser.parse_args()
    if args.command == "run":
        run()
    elif args.command == "migrate":
        migrate()
    elif args.command == "reanalyze":
        reanalyze(activity_id=args.activity, all_activities=args.all)
    elif args.command == "gc":
        gc(apply=args.apply)
    elif args.command == "backup":
        backup(args.directory)
    else:  # pragma: no cover - argparse enforces this
        sys.exit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
