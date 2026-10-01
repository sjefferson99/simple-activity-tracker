"""The live page: watching an activity while it's recorded (issue #130 phase B,
docs/LIVE-TRACKING-PLAN.md §2.4).

The owner always sees their own sessions. Anyone else goes through
app.sharing.live_access on every request, page load and poll alike, so a
revoke, a "Don't live share", or the activity finishing reaches an open page
on its next poll. Nothing here offers a download (plan D7).
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.audit import log_audit_event
from app.deps import db_session
from app.models.live import LiveSession
from app.models.user import User
from app.repositories.live import SqlAlchemyLiveSessionRepository
from app.repositories.users import SqlAlchemyUserRepository
from app.sharing import get_history_visible_activity, live_access, live_viewers_of
from app.web.deps import WebUser, require_htmx_header
from app.web.templating import templates

router = APIRouter(prefix="/live", tags=["web"], include_in_schema=False)

# How often the page polls, and the most points one poll returns (the rest
# arrive on the next poll, which the page makes straight away).
POLL_SECONDS = 15
POLL_MAX_POINTS = 5000


def _finished_activity_url(session: Session, user: User, live: LiveSession) -> str | None:
    """Where the finished activity can be seen, if this user may see it: the
    owner's own page, or the shared page only with a History grant (D8)."""
    if live.activity_id is None:
        return None
    if live.user_id == user.id:
        return f"/activities/{live.activity_id}"
    if get_history_visible_activity(session, user.id, live.activity_id) is not None:
        return f"/shared/activities/{live.activity_id}"
    return None


def _status(live: LiveSession) -> str:
    closed = live.activity_id is not None or live.state in ("finished", "converted")
    return "finished" if closed else "live"


def _not_found(request: Request, user: User) -> Response:
    return templates.TemplateResponse(request, "not_found.html", {"user": user}, status_code=404)


@router.get("/{session_id}")
def live_page(
    session_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    live = SqlAlchemyLiveSessionRepository(session).get(session_id)
    if live is None:
        return _not_found(request, user)
    is_owner = live.user_id == user.id
    access = "live" if is_owner else live_access(session, user.id, live)
    if access == "none":
        return _not_found(request, user)
    owner = SqlAlchemyUserRepository(session).get_by_id(live.user_id)
    context: dict[str, Any] = {
        "user": user,
        "live": live,
        "is_owner": is_owner,
        "owner_name": owner.display_name if owner is not None else "",
        # A viewer arriving after the finish gets the notice and nothing else.
        "status": _status(live) if access == "live" else "finished",
        "activity_url": _finished_activity_url(session, user, live),
        "poll_seconds": POLL_SECONDS,
    }
    if is_owner and owner is not None:
        context["live_viewers"] = live_viewers_of(session, owner)
        context["live_sharing_paused"] = owner.live_sharing_paused
    return templates.TemplateResponse(request, "live.html", context)


@router.get("/{session_id}/poll")
def live_poll(
    session_id: str,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    from_index: Annotated[int, Query(alias="from", ge=0)] = 0,
) -> Response:
    live = SqlAlchemyLiveSessionRepository(session).get(session_id)
    is_owner = live is not None and live.user_id == user.id
    if live is None:
        return JSONResponse({"status": "gone"}, status_code=404)
    access = "live" if is_owner else live_access(session, user.id, live)
    if access == "none":
        return JSONResponse({"status": "gone"}, status_code=404)
    if access == "finished":
        return JSONResponse(
            {"status": "finished", "activity_url": _finished_activity_url(session, user, live)}
        )

    points = SqlAlchemyLiveSessionRepository(session).points_since(
        live.id, from_index, POLL_MAX_POINTS
    )
    return JSONResponse(
        {
            "status": _status(live),
            "state": live.state,
            "activity_type": live.activity_type,
            "started_at": live.started_at.isoformat(),
            "last_update_at": live.last_update_at.isoformat(),
            "server_now": datetime.now(UTC).isoformat(),
            "metrics": live.latest_metrics,
            "next_index": (points[-1].idx + 1) if points else from_index,
            "more": len(points) == POLL_MAX_POINTS,
            "points": [
                {"lat": p.lat, "lon": p.lon, "segment": p.segment, "t": p.t.isoformat()}
                for p in points
            ],
            "activity_url": _finished_activity_url(session, user, live),
        }
    )


@router.delete("/{session_id}", dependencies=[Depends(require_htmx_header)])
def live_delete(
    session_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    """The owner discards a live session that never became an activity."""
    repo = SqlAlchemyLiveSessionRepository(session)
    live = repo.get(session_id)
    if live is None or live.user_id != user.id or live.activity_id is not None:
        return Response(status_code=404)
    repo.delete(live)
    log_audit_event(
        "live.deleted",
        actor_id=user.id,
        target_id=session_id,
        client_ip=request.client.host if request.client else "unknown",
    )
    return Response(status_code=200, headers={"HX-Redirect": "/"})
