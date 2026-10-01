"""Read-only pages for activities other users have shared with the signed-in
user (issue #130). Every route here authorizes through
app.sharing.get_history_visible_activity on every request, and none of them
changes anything. Downloads and export are deliberately absent (plan D7):
the owner routes (/activities/..., /api/v1/activities/...) stay owner-only."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v1.activities import track_out
from app.deps import db_session
from app.repositories.activity_analyses import SqlAlchemyActivityAnalysisRepository
from app.repositories.users import SqlAlchemyUserRepository
from app.sharing import get_history_visible_activity
from app.web.activities import _activity_view, splits_fragment_response, splits_reset_response
from app.web.deps import WebUser
from app.web.templating import templates

router = APIRouter(prefix="/shared/activities", tags=["web"], include_in_schema=False)


def _not_found(request: Request, user: object) -> Response:
    return templates.TemplateResponse(request, "not_found.html", {"user": user}, status_code=404)


@router.get("/{activity_id}")
def shared_activity_detail(
    activity_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    activity = get_history_visible_activity(session, user.id, activity_id)
    if activity is None:
        return _not_found(request, user)
    analysis = SqlAlchemyActivityAnalysisRepository(session).get_by_activity_id(activity.id)
    owner = SqlAlchemyUserRepository(session).get_by_id(activity.user_id)
    return templates.TemplateResponse(
        request,
        "activity_detail.html",
        {
            "user": user,
            "activity": _activity_view(activity, analysis),
            "read_only": True,
            "owner_name": owner.display_name if owner is not None else "",
        },
    )


@router.get("/{activity_id}/track")
def shared_activity_track(
    activity_id: str,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    """The map feed for the read-only page. Always the default downsampled
    track, never the full-resolution one."""
    activity = get_history_visible_activity(session, user.id, activity_id)
    if activity is None:
        return JSONResponse({"error": {"code": "not_found", "message": "Not found"}}, 404)
    return JSONResponse(track_out(session, activity).model_dump(mode="json"))


@router.get("/{activity_id}/splits")
def shared_activity_splits(
    activity_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    split_type: Annotated[str, Query(pattern="^(distance_km|distance_mi|time_min)$")] = (
        "distance_km"
    ),
    split_value: Annotated[int, Query(ge=1, le=1000)] = 1,
) -> Response:
    activity = get_history_visible_activity(session, user.id, activity_id)
    if activity is None:
        return _not_found(request, user)
    return splits_fragment_response(request, activity, split_type, split_value)


@router.get("/{activity_id}/splits/reset")
def shared_activity_splits_reset(
    activity_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    activity = get_history_visible_activity(session, user.id, activity_id)
    if activity is None:
        return _not_found(request, user)
    return splits_reset_response(request, session, activity)
