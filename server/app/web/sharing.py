"""Owner-side sharing controls (issue #130, docs/LIVE-TRACKING-PLAN.md):
who can see my activity history (Settings), and extra viewers for one
finished activity (its detail page). Only the signed-in owner ever changes
their own grants; viewer pages live in app/web/shared_activities.py."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, Response
from sqlalchemy.orm import Session

from app.audit import log_audit_event
from app.deps import db_session
from app.models.user import User
from app.repositories.activities import SqlAlchemyActivityRepository
from app.repositories.shares import SqlAlchemyShareRepository, shareable_users
from app.web.deps import WebUser, require_htmx_header
from app.web.templating import templates

router = APIRouter(tags=["web"], include_in_schema=False)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def settings_share_context(session: Session, owner: User) -> dict[str, Any]:
    viewers = SqlAlchemyShareRepository(session).list_history_viewers(owner.id)
    return {
        "history_viewers": viewers,
        "history_candidates": shareable_users(
            session, owner.id, exclude_ids={v.id for v in viewers}
        ),
    }


def activity_share_context(session: Session, owner: User, activity_id: str) -> dict[str, Any]:
    shares = SqlAlchemyShareRepository(session)
    account_viewers = shares.list_history_viewers(owner.id)
    extra_viewers = shares.list_activity_viewers(activity_id)
    exclude = {v.id for v in account_viewers} | {v.id for v in extra_viewers}
    return {
        "share_activity_id": activity_id,
        "account_viewers": account_viewers,
        "extra_viewers": extra_viewers,
        "extra_candidates": shareable_users(session, owner.id, exclude_ids=exclude),
    }


def _is_shareable(session: Session, owner: User, viewer_id: str) -> bool:
    return any(u.id == viewer_id for u in shareable_users(session, owner.id, exclude_ids=set()))


@router.post("/settings/shares", dependencies=[Depends(require_htmx_header)])
def grant_history_share(
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    viewer_id: Annotated[str, Form()] = "",
) -> Response:
    if not _is_shareable(session, user, viewer_id):
        context = {
            **settings_share_context(session, user),
            "share_error": "Pick a user to share with.",
        }
        return templates.TemplateResponse(
            request, "partials/share_list.html", context, status_code=400
        )
    SqlAlchemyShareRepository(session).grant_history(user.id, viewer_id)
    log_audit_event(
        "share.history_granted",
        actor_id=user.id,
        target_id=viewer_id,
        client_ip=_client_ip(request),
    )
    return templates.TemplateResponse(
        request, "partials/share_list.html", settings_share_context(session, user)
    )


@router.delete("/settings/shares/{viewer_id}", dependencies=[Depends(require_htmx_header)])
def revoke_history_share(
    viewer_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    if SqlAlchemyShareRepository(session).revoke_history(user.id, viewer_id):
        log_audit_event(
            "share.history_revoked",
            actor_id=user.id,
            target_id=viewer_id,
            client_ip=_client_ip(request),
        )
    return templates.TemplateResponse(
        request, "partials/share_list.html", settings_share_context(session, user)
    )


@router.post("/activities/{activity_id}/shares", dependencies=[Depends(require_htmx_header)])
def add_activity_share(
    activity_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    viewer_id: Annotated[str, Form()] = "",
) -> Response:
    activity = SqlAlchemyActivityRepository(session).get_by_id_for_user(user.id, activity_id)
    if activity is None:
        return Response(status_code=404)
    if not _is_shareable(session, user, viewer_id):
        context = {
            **activity_share_context(session, user, activity.id),
            "share_error": "Pick a user to share with.",
        }
        return templates.TemplateResponse(
            request, "partials/activity_share_list.html", context, status_code=400
        )
    SqlAlchemyShareRepository(session).add_activity_viewer(activity.id, viewer_id)
    log_audit_event(
        "activity_share.added",
        actor_id=user.id,
        target_id=activity.id,
        client_ip=_client_ip(request),
        viewer_id=viewer_id,
    )
    return templates.TemplateResponse(
        request,
        "partials/activity_share_list.html",
        activity_share_context(session, user, activity.id),
    )


@router.delete(
    "/activities/{activity_id}/shares/{viewer_id}", dependencies=[Depends(require_htmx_header)]
)
def remove_activity_share(
    activity_id: str,
    viewer_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    activity = SqlAlchemyActivityRepository(session).get_by_id_for_user(user.id, activity_id)
    if activity is None:
        return Response(status_code=404)
    if SqlAlchemyShareRepository(session).remove_activity_viewer(activity.id, viewer_id):
        log_audit_event(
            "activity_share.removed",
            actor_id=user.id,
            target_id=activity.id,
            client_ip=_client_ip(request),
            viewer_id=viewer_id,
        )
    return templates.TemplateResponse(
        request,
        "partials/activity_share_list.html",
        activity_share_context(session, user, activity.id),
    )
