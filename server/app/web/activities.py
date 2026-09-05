from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from sqlalchemy.orm import Session

from app.activity_export import (
    ImportArchiveError,
    export_activities_archive,
    read_import_archive,
    run_import,
)
from app.api.v1.activities import _insert_from_manifest_entry
from app.audit import log_audit_event
from app.config import get_settings
from app.deps import db_session
from app.models.activity import Activity
from app.models.activity_analysis import ActivityAnalysis, AnalysisStatus
from app.repositories.activities import InvalidCursorError, SqlAlchemyActivityRepository
from app.repositories.activity_analyses import SqlAlchemyActivityAnalysisRepository
from app.storage.blob_store import LocalFileBlobStore
from app.validation import NOTES_MAX_LENGTH, TITLE_MAX_LENGTH
from app.web.deps import WebUser, require_htmx_header
from app.web.templating import templates

router = APIRouter(tags=["web"], include_in_schema=False)


def _activity_view(activity: Activity, analysis: ActivityAnalysis | None) -> dict[str, Any]:
    """Shapes an Activity + ActivityAnalysis pair the way activity_detail.html
    expects — mirrors app.api.v1.activities._activity_out()/_analysis_out()
    but as a plain dict for template access rather than a Pydantic model."""
    if analysis is None or analysis.status == AnalysisStatus.pending:
        analysis_view: dict[str, Any] = {"status": "pending", "result": None}
    elif analysis.status == AnalysisStatus.failed:
        analysis_view = {"status": "failed", "result": None}
    else:
        analysis_view = {"status": "done", "result": analysis.result}
    return {
        "id": activity.id,
        "title": activity.title,
        "notes": activity.notes,
        "activity_type": activity.activity_type,
        "started_at": activity.started_at,
        "ended_at": activity.ended_at,
        "client_summary": activity.client_summary,
        "analysis": analysis_view,
    }


@router.get("/")
def activity_list(
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    cursor: str | None = None,
) -> Response:
    activities = SqlAlchemyActivityRepository(session)
    try:
        page = activities.list_for_user(user.id, limit=20, cursor=cursor)
    except InvalidCursorError:
        # A tampered or stale cursor in the URL shouldn't break the page for
        # a human browsing — fall back to the first page rather than a 400.
        page = activities.list_for_user(user.id, limit=20, cursor=None)
    context = {
        "user": user,
        "activities": page.activities,
        "next_cursor": page.next_cursor,
    }
    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse(request, "partials/activity_list_items.html", context)
    return templates.TemplateResponse(request, "activities_list.html", context)


@router.get("/activities/{activity_id}")
def activity_detail(
    activity_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    activity = SqlAlchemyActivityRepository(session).get_by_id_for_user(user.id, activity_id)
    if activity is None:
        return templates.TemplateResponse(
            request, "not_found.html", {"user": user}, status_code=404
        )
    analysis = SqlAlchemyActivityAnalysisRepository(session).get_by_activity_id(activity.id)
    return templates.TemplateResponse(
        request,
        "activity_detail.html",
        {"user": user, "activity": _activity_view(activity, analysis)},
    )


@router.patch("/activities/{activity_id}", dependencies=[Depends(require_htmx_header)])
def activity_patch(
    activity_id: str,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    title: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
) -> Response:
    activities = SqlAlchemyActivityRepository(session)
    activity = activities.get_by_id_for_user(user.id, activity_id)
    if activity is None:
        return Response(status_code=404)
    title = title.strip()
    notes = notes.strip()
    if len(title) > TITLE_MAX_LENGTH or len(notes) > NOTES_MAX_LENGTH:
        return Response(status_code=400)
    activity.title = title or None
    activity.notes = notes or None
    activity.updated_at = datetime.now(UTC)
    return Response(status_code=200, headers={"HX-Refresh": "true"})


@router.delete("/activities/{activity_id}", dependencies=[Depends(require_htmx_header)])
def activity_delete(
    activity_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    activities = SqlAlchemyActivityRepository(session)
    activity = activities.get_by_id_for_user(user.id, activity_id)
    if activity is None:
        return Response(status_code=404)

    analyses = SqlAlchemyActivityAnalysisRepository(session)
    analysis = analyses.get_by_activity_id(activity.id)
    if analysis is not None:
        analyses.delete(analysis)
        # See app/api/v1/activities.py:delete_activity — no relationship()
        # means the analysis delete must be flushed before the activity delete.
        session.flush()

    blob_key = activity.gpx_blob_key
    activity_id_for_audit = activity.id
    activities.delete(activity)
    # See app/api/v1/activities.py:delete_activity — committed explicitly
    # (rather than relying on db_session's post-return commit) before the
    # synchronous blob delete, since a BackgroundTask runs as part of
    # sending the response, which happens before db_session's dependency
    # cleanup/commit — not after.
    session.commit()
    log_audit_event(
        "activity.deleted",
        actor_id=user.id,
        target_id=activity_id_for_audit,
        client_ip=request.client.host if request.client else "unknown",
    )
    LocalFileBlobStore(Path(get_settings().data_dir)).delete(blob_key)
    return Response(status_code=200, headers={"HX-Redirect": "/"})


@router.get("/export")
def export_activities(
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    activity_ids: Annotated[list[str] | None, Query()] = None,
    selection: Annotated[str | None, Query()] = None,
) -> Response:
    """A plain GET (not htmx, no CSRF header) so a native <a>/<form method="get">
    submission triggers a real browser file download — matches the existing
    GPX-download link, and GET is exempt from require_htmx_header the same
    way every other read-only route already is.

    `selection=1` is a hidden field on #export-form (activities_list.html) —
    its only purpose is telling "the Export-selected form submitted with
    every checkbox unchecked" (no activity_ids at all) apart from "the plain
    Export-all link" (also no activity_ids). Without it, both cases look
    identical to this route and an empty selection would silently export
    every activity instead of the empty set the user actually asked for.

    Unlike the API's export_activities, an unknown/foreign id here is
    silently dropped rather than 404ing the whole request — the ids in this
    query string only ever come from checkboxes rendered on the page itself
    (see partials/activity_list_items.html), so one going stale (e.g. the
    activity was deleted in another tab between page load and submit) should
    just shrink the export, not error the button out entirely."""
    if selection is not None and not activity_ids:
        raise HTTPException(status_code=400, detail="Select at least one activity to export")

    if activity_ids is not None:
        activities_repo = SqlAlchemyActivityRepository(session)
        activity_ids = [
            activity_id
            for activity_id in activity_ids
            if activities_repo.get_by_id_for_user(user.id, activity_id) is not None
        ]
    blob_store = LocalFileBlobStore(Path(get_settings().data_dir))
    archive_bytes = export_activities_archive(session, blob_store, user.id, activity_ids)

    filename = f"simple-activity-tracker-export-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.zip"
    return Response(
        content=archive_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", dependencies=[Depends(require_htmx_header)])
def import_activities(
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    archive: Annotated[UploadFile, File()],
) -> Response:
    settings = get_settings()
    data = archive.file.read(settings.max_import_bytes + 1)
    if len(data) > settings.max_import_bytes:
        return templates.TemplateResponse(
            request,
            "partials/import_result.html",
            {"user": user, "error": f"Archive exceeds the {settings.max_import_bytes}-byte limit"},
            status_code=413,
        )

    try:
        manifest, zip_archive = read_import_archive(data, settings.max_import_bytes)
    except ImportArchiveError as exc:
        return templates.TemplateResponse(
            request,
            "partials/import_result.html",
            {"user": user, "error": str(exc)},
            status_code=400,
        )

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

    return templates.TemplateResponse(
        request,
        "partials/import_result.html",
        {
            "user": user,
            "imported": summary.imported,
            "skipped": summary.skipped,
            "failed": summary.failed,
            "items": summary.items,
        },
    )
