from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import db_session
from app.models.activity import Activity
from app.models.activity_analysis import ActivityAnalysis, AnalysisStatus
from app.repositories.activities import InvalidCursor, SqlAlchemyActivityRepository
from app.repositories.activity_analyses import SqlAlchemyActivityAnalysisRepository
from app.storage.blob_store import LocalFileBlobStore
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
    except InvalidCursor:
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
    activity.title = title.strip() or None
    activity.notes = notes.strip() or None
    activity.updated_at = datetime.now(UTC)
    return Response(status_code=200, headers={"HX-Refresh": "true"})


@router.delete("/activities/{activity_id}", dependencies=[Depends(require_htmx_header)])
def activity_delete(
    activity_id: str,
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

    LocalFileBlobStore(Path(get_settings().data_dir)).delete(activity.gpx_blob_key)
    activities.delete(activity)
    return Response(status_code=200, headers={"HX-Redirect": "/"})
