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
from dataclasses import dataclass
from typing import Literal

from app.activity_export import ImportSummary

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
