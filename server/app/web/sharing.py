"""Owner-side sharing controls (issue #130, docs/LIVE-TRACKING-PLAN.md):
who can watch me live and see my history, the "Don't live share" switch
(Settings), and extra viewers for one finished activity (its detail page).
Only the signed-in owner ever changes their own grants; viewer pages live in
app/web/shared_activities.py and app/web/live.py."""

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

# An HTML checkbox submits "on" when ticked and nothing at all when not.
Checkbox = Annotated[str, Form()]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _ticked(value: str) -> bool:
    return value == "on"


def settings_share_context(session: Session, owner: User) -> dict[str, Any]:
    shares = SqlAlchemyShareRepository(session).list_shares(owner.id)
    return {
        "shares": shares,
        "share_candidates": shareable_users(
            session, owner.id, exclude_ids={viewer.id for viewer, _ in shares}
        ),
        "live_sharing_paused": owner.live_sharing_paused,
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


def _share_list(
    request: Request, session: Session, user: User, *, error: str | None = None
) -> Response:
    context = settings_share_context(session, user)
    if error is not None:
        context["share_error"] = error
    return templates.TemplateResponse(
        request, "partials/share_list.html", context, status_code=400 if error else 200
    )


@router.post("/settings/shares", dependencies=[Depends(require_htmx_header)])
def add_share(
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    viewer_id: Annotated[str, Form()] = "",
    live: Checkbox = "",
    history: Checkbox = "",
) -> Response:
    if not _is_shareable(session, user, viewer_id):
        return _share_list(request, session, user, error="Pick a user to share with.")
    if not _ticked(live) and not _ticked(history):
        return _share_list(request, session, user, error="Choose Live, History or both.")
    SqlAlchemyShareRepository(session).set_flags(
        user.id, viewer_id, live=_ticked(live), history=_ticked(history)
    )
    log_audit_event(
        "share.granted",
        actor_id=user.id,
        target_id=viewer_id,
        client_ip=_client_ip(request),
        live=str(_ticked(live)).lower(),
        history=str(_ticked(history)).lower(),
    )
    return _share_list(request, session, user)


@router.patch("/settings/shares/{viewer_id}", dependencies=[Depends(require_htmx_header)])
def update_share(
    viewer_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    live: Checkbox = "",
    history: Checkbox = "",
) -> Response:
    """A Live/History checkbox in an existing row changed. Unticking both
    removes the grant entirely."""
    shares = SqlAlchemyShareRepository(session)
    if shares.get(user.id, viewer_id) is None:
        return Response(status_code=404)
    shares.set_flags(user.id, viewer_id, live=_ticked(live), history=_ticked(history))
    log_audit_event(
        "share.updated",
        actor_id=user.id,
        target_id=viewer_id,
        client_ip=_client_ip(request),
        live=str(_ticked(live)).lower(),
        history=str(_ticked(history)).lower(),
    )
    return _share_list(request, session, user)


@router.delete("/settings/shares/{viewer_id}", dependencies=[Depends(require_htmx_header)])
def remove_share(
    viewer_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    if SqlAlchemyShareRepository(session).delete_share(user.id, viewer_id):
        log_audit_event(
            "share.revoked",
            actor_id=user.id,
            target_id=viewer_id,
            client_ip=_client_ip(request),
        )
    return _share_list(request, session, user)


@router.put("/settings/live-sharing", dependencies=[Depends(require_htmx_header)])
def set_live_sharing_paused(
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    paused: Checkbox = "",
) -> Response:
    """The "Don't live share" switch: hides every live session from every
    viewer at once, without forgetting who has a Live grant."""
    user.live_sharing_paused = _ticked(paused)
    log_audit_event(
        "share.live_updated",
        actor_id=user.id,
        target_id=user.id,
        client_ip=_client_ip(request),
        paused=str(user.live_sharing_paused).lower(),
    )
    return _share_list(request, session, user)


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
