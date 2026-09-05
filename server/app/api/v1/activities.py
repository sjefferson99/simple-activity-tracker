import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activity_export import (
    ActivityNotFoundError,
    ImportArchiveError,
    export_activities_archive,
    read_import_archive,
    run_import,
)
from app.analysis.gpx_parser import GpxParseError, parse_gpx
from app.analysis.track_sampling import DEFAULT_MAX_POINTS, sample_track
from app.analysis.v1 import ANALYSIS_VERSION, AnalyzerV1
from app.api.v1.errors import api_error
from app.api.v1.schemas import (
    ActivityListItem,
    ActivityListResponse,
    ActivityOut,
    ActivityPatchRequest,
    ActivitySummary,
    AnalysisOut,
    ExportManifestEntry,
    ExportRequest,
    ImportResult,
    TrackOut,
)
from app.audit import log_audit_event
from app.auth.current_user import CurrentUser
from app.config import get_settings
from app.deps import db_session
from app.models.activity import Activity
from app.models.activity_analysis import ActivityAnalysis, AnalysisStatus
from app.repositories.activities import InvalidCursorError, SqlAlchemyActivityRepository
from app.repositories.activity_analyses import SqlAlchemyActivityAnalysisRepository
from app.storage.blob_store import LocalFileBlobStore
from app.validation import SUMMARY_MAX_BYTES

router = APIRouter(prefix="/api/v1/activities", tags=["activities"])


def _blob_store() -> LocalFileBlobStore:
    return LocalFileBlobStore(Path(get_settings().data_dir))


def _activity_out(activity: Activity, analysis: ActivityAnalysis | None) -> ActivityOut:
    return ActivityOut(
        id=activity.id,
        client_activity_id=activity.client_activity_id,
        activity_type=activity.activity_type,  # type: ignore[arg-type]
        started_at=activity.started_at,
        ended_at=activity.ended_at,
        title=activity.title,
        notes=activity.notes,
        client_summary=activity.client_summary,
        source_platform=activity.source_platform,
        source_app_version=activity.source_app_version,
        created_at=activity.created_at,
        updated_at=activity.updated_at,
        analysis=_analysis_out(analysis),
    )


def _analysis_out(analysis: ActivityAnalysis | None) -> AnalysisOut:
    if analysis is None or analysis.status == AnalysisStatus.pending:
        return AnalysisOut(status="pending")
    if analysis.status == AnalysisStatus.failed:
        return AnalysisOut(status="failed")
    return AnalysisOut(status="done", result=analysis.result)


@router.get("", response_model=ActivityListResponse)
def list_activities(
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> ActivityListResponse:
    try:
        page = SqlAlchemyActivityRepository(session).list_for_user(
            user.id, limit=limit, cursor=cursor
        )
    except InvalidCursorError as exc:
        raise api_error(400, "invalid_cursor", str(exc)) from exc
    items = [
        ActivityListItem(
            id=activity.id,
            activity_type=activity.activity_type,  # type: ignore[arg-type]
            started_at=activity.started_at,
            ended_at=activity.ended_at,
            title=activity.title,
            distance_meters=activity.client_summary.get("distance_meters", 0.0),
            moving_seconds=activity.client_summary.get("moving_seconds", 0.0),
        )
        for activity in page.activities
    ]
    return ActivityListResponse(activities=items, next_cursor=page.next_cursor)


@dataclass
class _NewActivity:
    client_activity_id: str
    activity_type: str
    started_at: datetime
    ended_at: datetime
    client_summary: dict[str, object]
    source_platform: str
    source_app_version: str
    title: str | None = None
    notes: str | None = None


def _insert_activity_with_gpx(
    session: Session,
    user_id: str,
    new_activity: _NewActivity,
    gpx_bytes: bytes,
) -> tuple[Activity, ActivityAnalysis, bool]:
    """Race-safe insert shared by upload and import: returns the existing row
    unchanged (created=False) if client_activity_id already exists for this
    user, otherwise parses+analyzes the GPX and inserts a new row+analysis
    (created=True). See upload_activity's original inline comments for why
    the begin_nested()/IntegrityError dance is needed — a concurrent retry of
    the same client_activity_id can race the initial existence check."""
    activities = SqlAlchemyActivityRepository(session)
    analyses = SqlAlchemyActivityAnalysisRepository(session)

    existing = activities.get_by_client_activity_id(user_id, new_activity.client_activity_id)
    if existing is not None:
        return existing, analyses.get_by_activity_id(existing.id), False  # type: ignore[return-value]

    try:
        track = parse_gpx(gpx_bytes)
    except GpxParseError as exc:
        raise api_error(400, "invalid_gpx", str(exc)) from exc

    blob_store = _blob_store()
    blob_key = blob_store.put(user_id, gpx_bytes)

    now = datetime.now(UTC)
    activity = Activity(
        user_id=user_id,
        client_activity_id=new_activity.client_activity_id,
        activity_type=new_activity.activity_type,
        started_at=new_activity.started_at,
        ended_at=new_activity.ended_at,
        title=new_activity.title,
        notes=new_activity.notes,
        client_summary=new_activity.client_summary,
        gpx_blob_key=blob_key,
        gpx_sha256=hashlib.sha256(gpx_bytes).hexdigest(),
        gpx_bytes=len(gpx_bytes),
        source_platform=new_activity.source_platform,
        source_app_version=new_activity.source_app_version,
        created_at=now,
        updated_at=now,
    )
    activities.add(activity)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        # begin_nested() only rolls back to the SAVEPOINT; the Session itself
        # is left in a "rollback required" state until this runs, or the
        # very next statement (the lookup below) raises PendingRollbackError
        # instead of the IntegrityError we actually want to handle.
        session.rollback()
        blob_store.delete(blob_key)
        winner = activities.get_by_client_activity_id(user_id, new_activity.client_activity_id)
        if winner is None:  # pragma: no cover - defensive, should be unreachable
            raise
        return winner, analyses.get_by_activity_id(winner.id), False  # type: ignore[return-value]

    try:
        result = AnalyzerV1().analyze(track)
        analysis = ActivityAnalysis(
            activity_id=activity.id,
            analysis_version=ANALYSIS_VERSION,
            status=AnalysisStatus.done,
            result=result,
            track=sample_track(track, max_points=DEFAULT_MAX_POINTS),
            computed_at=datetime.now(UTC),
        )
    except Exception as exc:  # analysis failure must never fail the upload/import
        analysis = ActivityAnalysis(
            activity_id=activity.id,
            analysis_version=ANALYSIS_VERSION,
            status=AnalysisStatus.failed,
            error=str(exc),
            computed_at=datetime.now(UTC),
        )
    analyses.add(analysis)
    try:
        session.flush()
    except Exception:
        # A failure here (e.g. the analysis flush) leaves the blob written
        # but the activity row rolled back by db_session's outer except —
        # clean it up rather than orphaning it. This path re-raises (no
        # response is ever returned), so a BackgroundTask would never run;
        # delete synchronously instead.
        blob_store.delete(blob_key)
        raise

    return activity, analysis, True


def _insert_from_manifest_entry(
    session: Session, user_id: str, entry: ExportManifestEntry, gpx_bytes: bytes
) -> bool:
    """Adapts _insert_activity_with_gpx to the ActivityInserter shape
    run_import() expects — see app/activity_export.py."""
    _activity, _analysis, created = _insert_activity_with_gpx(
        session,
        user_id,
        _NewActivity(
            client_activity_id=entry.client_activity_id,
            activity_type=entry.activity_type,
            started_at=entry.started_at,
            ended_at=entry.ended_at,
            client_summary=entry.client_summary,
            source_platform=entry.source_platform,
            source_app_version=entry.source_app_version,
            title=entry.title,
            notes=entry.notes,
        ),
        gpx_bytes,
    )
    return created


@router.post("", response_model=ActivityOut, status_code=201)
def upload_activity(
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
    response: Response,
    summary: Annotated[str, Form()],
    gpx: Annotated[UploadFile, File()],
) -> ActivityOut:
    if len(summary.encode()) > SUMMARY_MAX_BYTES:
        raise api_error(
            400, "invalid_summary", f"summary exceeds the {SUMMARY_MAX_BYTES}-byte limit"
        )
    try:
        summary_model = ActivitySummary.model_validate_json(summary)
    except ValidationError as exc:
        raise api_error(400, "invalid_summary", str(exc)) from exc

    settings = get_settings()
    gpx_bytes = gpx.file.read(settings.max_gpx_bytes + 1)
    if len(gpx_bytes) > settings.max_gpx_bytes:
        raise api_error(
            413, "gpx_too_large", f"GPX file exceeds the {settings.max_gpx_bytes}-byte limit"
        )

    activity, analysis, created = _insert_activity_with_gpx(
        session,
        user.id,
        _NewActivity(
            client_activity_id=summary_model.client_activity_id,
            activity_type=summary_model.activity_type,
            started_at=summary_model.started_at,
            ended_at=summary_model.ended_at,
            client_summary=json.loads(summary),
            source_platform=summary_model.source.platform,
            source_app_version=summary_model.source.app_version,
        ),
        gpx_bytes,
    )
    if not created:
        response.status_code = 200
    return _activity_out(activity, analysis)


@router.get("/{activity_id}", response_model=ActivityOut)
def get_activity(
    activity_id: str, user: CurrentUser, session: Annotated[Session, Depends(db_session)]
) -> ActivityOut:
    activity = SqlAlchemyActivityRepository(session).get_by_id_for_user(user.id, activity_id)
    if activity is None:
        raise api_error(404, "not_found", "Activity not found")
    analysis = SqlAlchemyActivityAnalysisRepository(session).get_by_activity_id(activity.id)
    return _activity_out(activity, analysis)


@router.patch("/{activity_id}", response_model=ActivityOut)
def patch_activity(
    activity_id: str,
    body: ActivityPatchRequest,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> ActivityOut:
    activity = SqlAlchemyActivityRepository(session).get_by_id_for_user(user.id, activity_id)
    if activity is None:
        raise api_error(404, "not_found", "Activity not found")
    if body.title is not None:
        activity.title = body.title
    if body.notes is not None:
        activity.notes = body.notes
    activity.updated_at = datetime.now(UTC)
    analysis = SqlAlchemyActivityAnalysisRepository(session).get_by_activity_id(activity.id)
    return _activity_out(activity, analysis)


@router.delete("/{activity_id}", status_code=204)
def delete_activity(
    activity_id: str,
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> None:
    activities = SqlAlchemyActivityRepository(session)
    activity = activities.get_by_id_for_user(user.id, activity_id)
    if activity is None:
        raise api_error(404, "not_found", "Activity not found")

    analysis = SqlAlchemyActivityAnalysisRepository(session).get_by_activity_id(activity.id)
    if analysis is not None:
        SqlAlchemyActivityAnalysisRepository(session).delete(analysis)
        # Without a configured relationship(), SQLAlchemy's unit-of-work has
        # no FK dependency graph between Activity and ActivityAnalysis, so it
        # can't be trusted to order two session.delete() calls correctly on
        # flush — flushing the analysis delete now guarantees it happens first.
        session.flush()

    blob_key = activity.gpx_blob_key
    activity_id_for_audit = activity.id
    activities.delete(activity)
    # Commit explicitly here rather than relying on db_session's post-return
    # commit — a Starlette BackgroundTask runs as part of sending the
    # response, which happens *before* db_session's dependency cleanup
    # (and therefore before its commit), so a background-task delete would
    # race an uncommitted transaction. Committing now, then deleting the
    # blob synchronously, guarantees the row is durable first: if the commit
    # fails, the exception propagates and the blob is correctly left in
    # place (orphan-with-no-row is safe; row-with-no-blob is not).
    session.commit()
    log_audit_event(
        "activity.deleted",
        actor_id=user.id,
        target_id=activity_id_for_audit,
        client_ip=request.client.host if request.client else "unknown",
    )
    _blob_store().delete(blob_key)


@router.get("/{activity_id}/gpx")
def download_gpx(
    activity_id: str, user: CurrentUser, session: Annotated[Session, Depends(db_session)]
) -> Response:
    activity = SqlAlchemyActivityRepository(session).get_by_id_for_user(user.id, activity_id)
    if activity is None:
        raise api_error(404, "not_found", "Activity not found")
    data = _blob_store().get(activity.gpx_blob_key)
    filename = f"{activity.started_at.date().isoformat()}.gpx"
    return Response(
        content=data,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{activity_id}/analysis", response_model=AnalysisOut)
def get_analysis(
    activity_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
    response: Response,
) -> AnalysisOut:
    activity = SqlAlchemyActivityRepository(session).get_by_id_for_user(user.id, activity_id)
    if activity is None:
        raise api_error(404, "not_found", "Activity not found")
    analysis = SqlAlchemyActivityAnalysisRepository(session).get_by_activity_id(activity.id)
    out = _analysis_out(analysis)
    if out.status != "done":
        response.status_code = 202
    return out


@router.get("/{activity_id}/track", response_model=TrackOut)
def get_track(
    activity_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
    max_points: Annotated[int, Query(ge=1, le=20000)] = DEFAULT_MAX_POINTS,
) -> TrackOut:
    activity = SqlAlchemyActivityRepository(session).get_by_id_for_user(user.id, activity_id)
    if activity is None:
        raise api_error(404, "not_found", "Activity not found")

    if max_points == DEFAULT_MAX_POINTS:
        analysis = SqlAlchemyActivityAnalysisRepository(session).get_by_activity_id(activity.id)
        if analysis is not None and analysis.track is not None:
            return TrackOut.model_validate(analysis.track)

    data = _blob_store().get(activity.gpx_blob_key)
    try:
        track = parse_gpx(data)
    except GpxParseError:
        return TrackOut(segments=[])

    return TrackOut.model_validate(sample_track(track, max_points=max_points))


@router.post("/export")
def export_activities(
    body: ExportRequest,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    try:
        archive_bytes = export_activities_archive(
            session, _blob_store(), user.id, body.activity_ids
        )
    except ActivityNotFoundError as exc:
        raise api_error(404, "not_found", str(exc)) from exc

    filename = f"simple-activity-tracker-export-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.zip"
    return Response(
        content=archive_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=ImportResult)
def import_activities(
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
    archive: Annotated[UploadFile, File()],
) -> ImportResult:
    settings = get_settings()
    data = archive.file.read(settings.max_import_bytes + 1)
    if len(data) > settings.max_import_bytes:
        raise api_error(
            413, "archive_too_large", f"Archive exceeds the {settings.max_import_bytes}-byte limit"
        )

    try:
        manifest, zip_archive = read_import_archive(data, settings.max_import_bytes)
    except ImportArchiveError as exc:
        raise api_error(400, "invalid_archive", str(exc)) from exc

    with zip_archive:
        summary = run_import(
            session,
            user.id,
            manifest,
            zip_archive,
            settings.max_gpx_bytes,
            _insert_from_manifest_entry,
        )

    if summary.imported:
        log_audit_event(
            "activity.imported",
            actor_id=user.id,
            client_ip=request.client.host if request.client else "unknown",
            count=str(summary.imported),
        )

    return ImportResult(
        imported=summary.imported,
        skipped=summary.skipped,
        failed=summary.failed,
        items=summary.items,
    )
