import argparse
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


def migrate() -> None:
    command.upgrade(_alembic_config(), "head")


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
            assert all_activities  # enforced by main()'s mutually-exclusive group
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


def run() -> None:
    """validate config -> migrate -> bootstrap admin -> serve."""
    import uvicorn
    from pydantic import ValidationError

    from app.auth.bootstrap import bootstrap_admin_if_needed
    from app.db import get_session_factory

    try:
        get_settings()
    except ValidationError as exc:
        sys.exit(f"Invalid configuration: {exc}")

    migrate()

    with get_session_factory()() as session:
        bootstrap_admin_if_needed(session)

    settings = get_settings()
    forwarded_allow_ips = settings.trusted_proxies or None
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level=settings.log_level,
        proxy_headers=bool(forwarded_allow_ips),
        forwarded_allow_ips=forwarded_allow_ips,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="simple-runner-server")
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

    args = parser.parse_args()
    if args.command == "run":
        run()
    elif args.command == "migrate":
        migrate()
    elif args.command == "reanalyze":
        reanalyze(activity_id=args.activity, all_activities=args.all)
    else:  # pragma: no cover - argparse enforces this
        sys.exit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
