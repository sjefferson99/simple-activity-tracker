"""Reruns the current analyzer against stored activities (docs/WEB-PLAN.md
§5.4): how an algorithm change (a bumped ANALYSIS_VERSION, a fixed analyzer
bug) reaches activities analysed under an older version, without a re-upload
from the phone. The GPX never changes, only what's derived from it.

Each activity is its own short transaction in its own session (issue #212):
peak memory stays flat however many activities are stale, and a crash or
restart partway keeps everything already committed, so the next run only
picks up the rest. That also lets `run` do this in a background thread while
the app serves (issue #206/#213), so each write is guarded against a request
that changed the same analysis meanwhile (see _reanalyze_one).
"""

import logging
import threading
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import ColumnElement, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.analysis.gpx_parser import GpxParseError, parse_gpx, parse_split_plan
from app.analysis.track_sampling import DEFAULT_MAX_POINTS, sample_track
from app.analysis.v1 import (
    ANALYSIS_VERSION,
    AnalyzerV1,
    distance_and_duration_from_result,
    elapsed_and_gain_from_result,
    endpoints_from_result,
)
from app.api.v1.activities import _split_plan_to_json
from app.config import get_settings
from app.db import get_session_factory
from app.models.activity import Activity
from app.models.activity_analysis import ActivityAnalysis, AnalysisStatus
from app.records import replace_best_efforts
from app.storage.blob_store import LocalFileBlobStore
from app.terrain import terrain_correct

logger = logging.getLogger("app.reanalysis")

BACKGROUND_THREAD_NAME = "startup-reanalysis"


class Outcome(StrEnum):
    done = "done"
    failed = "failed"  # stored as a FAILED analysis, like an unparseable upload
    skipped = "skipped"  # gone, no longer stale, or changed by a request meanwhile
    error = "error"  # unexpected exception: nothing stored, retried on the next run


def _stale_condition() -> ColumnElement[bool]:
    stale = (ActivityAnalysis.activity_id.is_(None)) | (
        ActivityAnalysis.analysis_version < ANALYSIS_VERSION
    )
    if get_settings().terrain_correction:
        # Issue #5: retry a correction whose tile couldn't be fetched last
        # time, and correct what was analysed while it was off.
        terrain_status = ActivityAnalysis.result["elevation"]["terrain"]["status"]
        stale = stale | terrain_status.as_string().in_(("pending", "disabled"))
    return stale


def stale_activity_ids() -> list[str]:
    """Only the ids, so nothing heavier than a list of strings is held across
    the whole run (issue #212). Each activity is loaded in its own session."""
    with get_session_factory()() as session:
        stmt = (
            select(Activity.id)
            .outerjoin(ActivityAnalysis, ActivityAnalysis.activity_id == Activity.id)
            .where(_stale_condition())
            .order_by(Activity.id)
        )
        return list(session.execute(stmt).scalars())


def _analyze(
    activity: Activity, previous: ActivityAnalysis | None, blob_store: LocalFileBlobStore
) -> tuple[
    dict[str, Any] | None, dict[str, Any] | None, AnalysisStatus, str | None, dict[str, Any] | None
]:
    """Returns (result, cached_track, status, error, split_plan_json_to_backfill).
    A GPX that's missing, unreadable or unparseable is a FAILED analysis."""
    try:
        gpx_bytes = blob_store.get(activity.gpx_blob_key)
        track = parse_gpx(gpx_bytes)
        # Reanalyze refreshes the derived ActivityAnalysis.result. It
        # deliberately does not touch activity.split_type/split_value, which
        # were set once at upload time and stay upload-time-fixed (pre-existing
        # defaults aren't backfilled). The plan is re-parsed from the GPX itself
        # (issue #100). Unlike those two, activity.split_plan IS backfilled when
        # it's still null: an activity uploaded after the phone started writing
        # the plan extensions (#99) but before the server understood them
        # (#100) would otherwise have a plan-aware splits table but no
        # Activity.split_plan row, so the web page's "reset to my uploaded
        # plan" control and the custom-plan heading/controls would never
        # appear for it.
        split_plan = parse_split_plan(gpx_bytes)
        backfill = (
            _split_plan_to_json(split_plan)
            if split_plan is not None and activity.split_plan is None
            else None
        )
        corrected, terrain = terrain_correct(
            track, previous.result if previous is not None else None
        )
        analyzer = AnalyzerV1()
        result = (
            analyzer.analyze(
                corrected,
                split_plan.split_type,
                split_plan.split_value,
                activity_type=activity.activity_type,
                split_plan=split_plan,
                terrain=terrain,
            )
            if split_plan
            else analyzer.analyze(corrected, activity_type=activity.activity_type, terrain=terrain)
        )
        cached_track = sample_track(track, max_points=DEFAULT_MAX_POINTS)
        return result, cached_track, AnalysisStatus.done, None, backfill
    except (GpxParseError, OSError, ValueError) as exc:
        return None, None, AnalysisStatus.failed, str(exc), None


def _reanalyze_one(
    session_factory: sessionmaker[Session],
    blob_store: LocalFileBlobStore,
    activity_id: str,
    *,
    only_if_stale: bool,
) -> Outcome:
    with session_factory() as session:
        stmt = (
            select(Activity, ActivityAnalysis)
            .outerjoin(ActivityAnalysis, ActivityAnalysis.activity_id == Activity.id)
            .where(Activity.id == activity_id)
        )
        if only_if_stale:
            # Re-checked per activity: since `run` serves while this works
            # through the list, an upload replacement could have brought it
            # up to date (or a delete removed it) since the ids were listed.
            stmt = stmt.where(_stale_condition())
        row = session.execute(stmt).first()
        if row is None:
            return Outcome.skipped
        activity, previous = row
        loaded_computed_at = previous.computed_at if previous is not None else None

        result, cached_track, status, error, backfill = _analyze(activity, previous, blob_store)
        if status == AnalysisStatus.failed:
            logger.warning("  %s: FAILED — %s", activity_id, error)

        distance_meters, moving_seconds = distance_and_duration_from_result(result)
        start_lat, start_lon, end_lat, end_lon = endpoints_from_result(result)
        elapsed_seconds, elevation_gain_m = elapsed_and_gain_from_result(result)
        values: dict[str, Any] = {
            "analysis_version": ANALYSIS_VERSION,
            "status": status,
            "result": result,
            "distance_meters": distance_meters,
            "moving_seconds": moving_seconds,
            "start_lat": start_lat,
            "start_lon": start_lon,
            "end_lat": end_lat,
            "end_lon": end_lon,
            "elapsed_seconds": elapsed_seconds,
            "elevation_gain_m": elevation_gain_m,
            "track": cached_track,
            "error": error,
            "computed_at": datetime.now(UTC),
        }

        try:
            # Write the analysis first, conditionally: it only lands if the
            # row is still the one loaded above. That statement also takes
            # the database's write lock, so nothing can change the row
            # between this check and the commit. A request that replaced or
            # deleted the analysis while this one was computing wins: rowcount
            # 0 (changed or deleted) or an IntegrityError (an analysis row or
            # activity delete appeared where there was none) means skip.
            if previous is None:
                session.add(ActivityAnalysis(activity_id=activity_id, **values))
                session.flush()
            else:
                updated = session.execute(
                    update(ActivityAnalysis)
                    .where(
                        ActivityAnalysis.activity_id == activity_id,
                        ActivityAnalysis.computed_at == loaded_computed_at,
                    )
                    .values(**values)
                    .execution_options(synchronize_session=False)
                )
                if updated.rowcount != 1:  # type: ignore[attr-defined]
                    session.rollback()
                    return Outcome.skipped
            if backfill is not None:
                activity.split_plan = backfill
            replace_best_efforts(session, activity_id, result)
            session.commit()
        except IntegrityError:
            session.rollback()
            return Outcome.skipped

    if status == AnalysisStatus.done:
        logger.info("  %s: done", activity_id)
    return Outcome.done if status == AnalysisStatus.done else Outcome.failed


def reanalyze_activity(activity_id: str) -> Outcome | None:
    """Reanalyzes one activity whatever its version. None if there's no such
    activity."""
    with get_session_factory()() as session:
        if session.get(Activity, activity_id) is None:
            return None
    blob_store = LocalFileBlobStore(Path(get_settings().data_dir))
    logger.info("Reanalyzing 1 activity at analysis_version=%s...", ANALYSIS_VERSION)
    return _reanalyze_one(get_session_factory(), blob_store, activity_id, only_if_stale=False)


def reanalyze_stale(stop: threading.Event | None = None) -> dict[Outcome, int]:
    """Reanalyzes every stale activity, one transaction each. `stop` ends the
    run after the activity in progress (used on shutdown); the rest are
    picked up next time. An unexpected exception on one activity is logged
    and that activity left as it was (retried next run), so one bad activity
    can't stop the others or, in the background, kill the thread silently."""
    ids = stale_activity_ids()
    counts = dict.fromkeys(Outcome, 0)
    if not ids:
        logger.info("No activities need reanalysis (analysis_version=%s).", ANALYSIS_VERSION)
        return counts
    logger.info(
        "Reanalyzing %d activity(ies) at analysis_version=%s...", len(ids), ANALYSIS_VERSION
    )
    session_factory = get_session_factory()
    blob_store = LocalFileBlobStore(Path(get_settings().data_dir))
    for index, activity_id in enumerate(ids, start=1):
        if stop is not None and stop.is_set():
            logger.info(
                "Reanalysis stopped with %d of %d remaining.", len(ids) - index + 1, len(ids)
            )
            return counts
        try:
            outcome = _reanalyze_one(session_factory, blob_store, activity_id, only_if_stale=True)
        except Exception:
            logger.exception(
                "  %s: ERROR — left as it was, will retry on the next run", activity_id
            )
            outcome = Outcome.error
        counts[outcome] += 1
    logger.info(
        "Reanalysis finished: %d done, %d failed, %d skipped, %d errors.",
        counts[Outcome.done],
        counts[Outcome.failed],
        counts[Outcome.skipped],
        counts[Outcome.error],
    )
    return counts


def start_background_reanalysis(stop: threading.Event) -> threading.Thread:
    """Runs reanalyze_stale() in a daemon thread, so `run` can start serving
    (and answer /healthz) straight away instead of after a reanalysis that can
    take minutes on a large account (issues #206, #213). Pages show the old
    analysis for an activity until its turn comes."""

    def _work() -> None:
        try:
            reanalyze_stale(stop)
        except Exception:
            logger.exception("Background reanalysis failed; stale activities retry on next start")

    thread = threading.Thread(target=_work, name=BACKGROUND_THREAD_NAME, daemon=True)
    thread.start()
    return thread
