"""In-memory background-job tracking for the Strava import (issue #61 follow-up):
POST /import/strava used to run run_strava_import() synchronously inside the
request handler, which for a real export (hundreds of activities) takes
minutes and blows past nginx's proxy_read_timeout — see
deploy/standalone-tls/nginx.conf. This module lets the web route hand the
import off to a FastAPI BackgroundTask and return immediately, while the
browser polls GET /import/strava/{job_id}/status for progress.

A module-level dict is enough here — this is a single-process homelab
deployment (see CLAUDE.md), not a distributed system, so there's no need for
Redis/Celery/a jobs table. Jobs are never persisted or cleaned up on a timer;
they just live for the process's lifetime and are capped in count (see
_MAX_JOBS) so a script hammering the endpoint can't leak memory forever."""

import threading
import uuid
import zipfile
from dataclasses import dataclass
from typing import Literal

from app.activity_export import ImportSummary
from app.activity_import_strava import StravaCsvRow, run_strava_import
from app.audit import log_audit_event
from app.config import get_settings
from app.db import get_session_factory

JobStatus = Literal["pending", "running", "done", "error"]

# Keeps the registry from growing unboundedly if something polls-and-abandons
# jobs repeatedly — oldest jobs are evicted first once this is exceeded.
_MAX_JOBS = 200


@dataclass
class StravaImportJob:
    id: str
    user_id: str
    status: JobStatus = "pending"
    processed: int = 0
    total: int = 0
    summary: ImportSummary | None = None
    error: str | None = None


_jobs: dict[str, StravaImportJob] = {}
_lock = threading.Lock()


def create_job(user_id: str, total: int) -> StravaImportJob:
    job = StravaImportJob(id=str(uuid.uuid4()), user_id=user_id, total=total)
    with _lock:
        _jobs[job.id] = job
        if len(_jobs) > _MAX_JOBS:
            oldest_id = next(iter(_jobs))
            del _jobs[oldest_id]
    return job


def get_job(job_id: str) -> StravaImportJob | None:
    with _lock:
        return _jobs.get(job_id)


def mark_running(job_id: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.status = "running"


def update_progress(job_id: str, processed: int, total: int) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.processed = processed
            job.total = total


def mark_done(job_id: str, summary: ImportSummary) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.status = "done"
            job.summary = summary
            job.processed = job.total


def mark_error(job_id: str, error: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.status = "error"
            job.error = error


def run_strava_import_job(
    job_id: str,
    user_id: str,
    client_ip: str,
    csv_rows: list[StravaCsvRow],
    zip_archive: zipfile.ZipFile,
) -> None:
    """The actual import loop, run outside the request/response cycle via
    BackgroundTasks. Shared by both the web and API /import/strava routes
    (app/web/activities.py, app/api/v1/activities.py) — must NOT use either
    request's db_session (app/deps.py), since that session is closed by
    FastAPI as soon as the response finishes sending, which happens before
    this function even starts running. Opens and owns its own session
    instead, mirroring db_session's own commit-on-success/rollback-on-
    exception/always-close pattern (see app/deps.py) since nothing else will
    do that for a background task.

    Also owns closing zip_archive — the request handler deliberately leaves
    it open (rather than a `with zip_archive:` in the handler itself) since
    the archive has to stay readable for the whole import, which now
    outlives the request."""
    # Imported here, not at module level, to avoid a straight-line circular
    # import: app.api.v1.activities doesn't import this module today, but
    # keeping the dependency local (rather than adding a top-level import
    # from a jobs-tracking module into a router module) keeps this module
    # focused on job bookkeeping, not the insert implementation's home.
    from app.api.v1.activities import _insert_from_strava_row

    job = get_job(job_id)
    if job is None:
        zip_archive.close()
        return  # evicted from the registry before the task got to run

    mark_running(job_id)
    session = get_session_factory()()
    try:
        with zip_archive:
            summary = run_strava_import(
                session,
                user_id,
                csv_rows,
                zip_archive,
                get_settings().max_gpx_bytes,
                _insert_from_strava_row,
                on_progress=lambda processed, total: update_progress(job_id, processed, total),
            )
        session.commit()
    except Exception as exc:  # a background task has no request/response to surface this to
        session.rollback()
        mark_error(job_id, str(exc))
        return
    finally:
        session.close()

    if summary.imported:
        log_audit_event(
            "activity.imported",
            actor_id=user_id,
            client_ip=client_ip,
            count=str(summary.imported),
            source="strava",
        )
    mark_done(job_id, summary)
