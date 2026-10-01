"""Live tracking upload from the phone (issue #130 phase B,
docs/LIVE-TRACKING-PLAN.md §2.3). API level 2.

Protocol: PUT the session's metadata once (idempotent), then POST point
batches numbered from 0. The server keeps `next_index`, the next point it
expects: a retried batch is a no-op, a gap is a 409 carrying `next_index` so
the phone resends from there, and a session that has already become an
activity is a 410 (stop uploading this run). Every route is scoped to the
caller's own sessions by client_activity_id.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.orm import Session

from app.api.v1.errors import api_error
from app.api.v1.schemas import LivePointsIn, LiveSessionIn, LiveSessionStateOut
from app.audit import log_audit_event
from app.auth.current_user import CurrentUser
from app.auth.rate_limit import live_upload_rate_limiter
from app.deps import db_session
from app.models.live import LiveSession
from app.repositories.live import NewLivePoint, SqlAlchemyLiveSessionRepository
from app.validation import LIVE_POINTS_MAX_PER_SESSION

router = APIRouter(prefix="/api/v1/live", tags=["live"])

# Sessions not updated for this long are deleted (plan §2.4).
LIVE_RETENTION = timedelta(days=30)

ClientActivityId = Annotated[str, Path(min_length=1, max_length=36, pattern=r"^[0-9A-Fa-f-]+$")]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _state_out(live: LiveSession) -> LiveSessionStateOut:
    return LiveSessionStateOut(next_index=live.next_index, state=live.state)  # type: ignore[arg-type]


def _require_rate_limit(user_id: str) -> None:
    if not live_upload_rate_limiter.allow(f"user:{user_id}"):
        raise api_error(429, "rate_limited", "Too many live updates. Try again shortly.")


def _require_open(live: LiveSession) -> None:
    if live.activity_id is not None or live.state == "converted":
        raise api_error(410, "session_closed", "This activity is already saved; stop uploading")


@router.put("/{client_activity_id}", response_model=LiveSessionStateOut)
def put_live_session(
    client_activity_id: ClientActivityId,
    body: LiveSessionIn,
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> LiveSessionStateOut:
    _require_rate_limit(user.id)
    repo = SqlAlchemyLiveSessionRepository(session)
    live = repo.get_for_user(user.id, client_activity_id)
    split_plan = body.split_plan.model_dump(mode="json") if body.split_plan else None
    if live is None:
        # Opportunistic retention sweep: cheap (indexed on last_update_at)
        # and runs at most once per started activity.
        repo.purge_last_updated_before(datetime.now(UTC) - LIVE_RETENTION)
        live = repo.create(
            user_id=user.id,
            client_activity_id=client_activity_id,
            activity_type=body.activity_type,
            started_at=body.started_at,
            split_plan=split_plan,
        )
        log_audit_event(
            "live.started", actor_id=user.id, target_id=live.id, client_ip=_client_ip(request)
        )
        return _state_out(live)

    _require_open(live)
    live.activity_type = body.activity_type
    live.split_plan = split_plan
    return _state_out(live)


@router.post("/{client_activity_id}/points", response_model=LiveSessionStateOut)
def post_live_points(
    client_activity_id: ClientActivityId,
    body: LivePointsIn,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> LiveSessionStateOut:
    _require_rate_limit(user.id)
    repo = SqlAlchemyLiveSessionRepository(session)
    live = repo.get_for_user(user.id, client_activity_id)
    if live is None:
        raise api_error(404, "not_found", "No live session; PUT it first")
    _require_open(live)
    if body.from_index > live.next_index:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "index_gap",
                    "message": f"Expected points from index {live.next_index}",
                    "next_index": live.next_index,
                }
            },
        )
    if body.from_index + len(body.points) > LIVE_POINTS_MAX_PER_SESSION:
        raise api_error(413, "session_too_large", "This live session has too many points")

    repo.append_points(
        live,
        body.from_index,
        [
            NewLivePoint(
                t=p.t,
                lat=p.lat,
                lon=p.lon,
                ele=p.ele,
                accuracy=p.accuracy,
                speed=p.speed,
                segment=p.segment,
            )
            for p in body.points
        ],
    )
    now = datetime.now(UTC)
    if body.metrics is not None:
        live.latest_metrics = body.metrics.model_dump(mode="json")
    live.state = body.state
    if body.state == "finished":
        live.finished_at = live.finished_at or now
    live.last_update_at = now
    return _state_out(live)


@router.delete("/{client_activity_id}", status_code=204)
def delete_live_session(
    client_activity_id: ClientActivityId,
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> None:
    """The run was discarded on the phone: nothing of it stays on the server.
    A session already linked to an activity is left alone (deleting the
    activity is a separate, explicit action)."""
    repo = SqlAlchemyLiveSessionRepository(session)
    live = repo.get_for_user(user.id, client_activity_id)
    if live is None or live.activity_id is not None:
        raise api_error(404, "not_found", "No live session")
    live_id = live.id
    repo.delete(live)
    log_audit_event(
        "live.deleted", actor_id=user.id, target_id=live_id, client_ip=_client_ip(request)
    )
