"""The live page: watching an activity while it's recorded (issue #130 phase B,
docs/LIVE-TRACKING-PLAN.md §2.4).

The owner always sees their own sessions. Anyone else goes through
app.sharing.live_access on every request, page load and poll alike, so a
revoke, a "Don't live share", or the activity finishing reaches an open page
on its next poll. Nothing here offers a download (plan D7).
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v1.activities import _insert_activity_with_gpx, _NewActivity
from app.audit import log_audit_event
from app.deps import db_session
from app.live_convert import live_session_gpx, live_session_summary
from app.models.live import LiveSession
from app.models.user import User
from app.repositories.live import SqlAlchemyLiveSessionRepository
from app.repositories.users import SqlAlchemyUserRepository
from app.sharing import get_history_visible_activity, live_access, live_viewers_of
from app.validation import LIVE_POINTS_MAX_PER_SESSION
from app.web.deps import WebUser, require_htmx_header
from app.web.templating import templates

router = APIRouter(prefix="/live", tags=["web"], include_in_schema=False)

# How often the page polls, and the most points one poll returns (the rest
# arrive on the next poll, which the page makes straight away).
POLL_SECONDS = 15
POLL_MAX_POINTS = 5000

# Convert to activity warns first when the session updated more recently than
# this: the phone may only be out of signal and about to carry on (plan §4).
CONVERT_RECENT_WARNING = timedelta(minutes=10)


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
        context["can_convert"] = live.activity_id is None and live.next_index > 0
        age = datetime.now(UTC) - live.last_update_at
        context["recent_update_minutes"] = (
            max(1, int(age.total_seconds() // 60)) if age < CONVERT_RECENT_WARNING else None
        )
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


@router.post("/{session_id}/convert", dependencies=[Depends(require_htmx_header)])
def live_convert(
    session_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    """Saves an unsaved live session as an activity (issue #130 D6), for when
    the phone's own upload never arrived. The session becomes "converted":
    the phone is told to stop (410) if it comes back, and its own upload, if
    it ever arrives, replaces this activity in place (upload_activity)."""
    repo = SqlAlchemyLiveSessionRepository(session)
    live = repo.get(session_id)
    if live is None or live.user_id != user.id:
        return Response(status_code=404)
    if live.activity_id is not None:
        return Response(status_code=200, headers={"HX-Redirect": f"/activities/{live.activity_id}"})
    points = repo.points_since(live.id, 0, LIVE_POINTS_MAX_PER_SESSION)
    if not points:
        return Response(status_code=400)

    ended_at = points[-1].t
    activity, _analysis, created = _insert_activity_with_gpx(
        session,
        user.id,
        _NewActivity(
            client_activity_id=live.client_activity_id,
            activity_type=live.activity_type,
            started_at=live.started_at,
            ended_at=ended_at,
            client_summary=live_session_summary(live, ended_at),
            source_platform="live",
            source_app_version="",
        ),
        live_session_gpx(live, points),
    )
    # Not created: the phone's own upload landed in the meantime, and that
    # real activity is what this session now points at.
    if created:
        activity.recovered_from_live = True
    live.state = "converted" if created else "finished"
    live.activity_id = activity.id
    live.finished_at = live.finished_at or datetime.now(UTC)
    repo.drop_points(live.id)
    log_audit_event(
        "live.converted",
        actor_id=user.id,
        target_id=live.id,
        client_ip=request.client.host if request.client else "unknown",
        activity_id=activity.id,
    )
    return Response(status_code=200, headers={"HX-Redirect": f"/activities/{activity.id}"})


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
