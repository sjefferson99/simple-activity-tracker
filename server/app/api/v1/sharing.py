"""Sharing settings the phone needs (issue #130 phase B, API level 2): the
user directory for the "live share with" dropdown, the caller's current
grants, and the phone's live-sharing setting. History grants are web-only."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.v1.errors import api_error
from app.api.v1.schemas import (
    LiveSharingRequest,
    MySharesResponse,
    ShareOut,
    UserDirectoryEntry,
    UserDirectoryResponse,
)
from app.audit import log_audit_event
from app.auth.current_user import CurrentUser
from app.deps import db_session
from app.models.user import User
from app.repositories.shares import SqlAlchemyShareRepository, shareable_users

users_router = APIRouter(prefix="/api/v1/users", tags=["sharing"])
me_router = APIRouter(prefix="/api/v1/me", tags=["sharing"])


def _my_shares(session: Session, user: User) -> MySharesResponse:
    return MySharesResponse(
        live_sharing_paused=user.live_sharing_paused,
        shares=[
            ShareOut(
                viewer_id=viewer.id,
                display_name=viewer.display_name,
                can_view_live=share.can_view_live,
                can_view_history=share.can_view_history,
            )
            for viewer, share in SqlAlchemyShareRepository(session).list_shares(user.id)
        ],
    )


@users_router.get("", response_model=UserDirectoryResponse)
def list_users(
    user: CurrentUser, session: Annotated[Session, Depends(db_session)]
) -> UserDirectoryResponse:
    """Every other enabled user, by display name only (plan D5)."""
    return UserDirectoryResponse(
        users=[
            UserDirectoryEntry(id=u.id, display_name=u.display_name)
            for u in shareable_users(session, user.id, exclude_ids=set())
        ]
    )


@me_router.get("/shares", response_model=MySharesResponse)
def get_my_shares(
    user: CurrentUser, session: Annotated[Session, Depends(db_session)]
) -> MySharesResponse:
    return _my_shares(session, user)


@me_router.put("/live-sharing", response_model=MySharesResponse)
def put_live_sharing(
    body: LiveSharingRequest,
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> MySharesResponse:
    viewer_ids = set(body.live_viewer_ids)
    allowed = {u.id for u in shareable_users(session, user.id, exclude_ids=set())}
    if not viewer_ids <= allowed:
        raise api_error(400, "invalid_viewer", "Unknown or unavailable user in live_viewer_ids")
    SqlAlchemyShareRepository(session).set_live_viewers(user.id, viewer_ids)
    user.live_sharing_paused = body.live_sharing_paused
    log_audit_event(
        "share.live_updated",
        actor_id=user.id,
        target_id=user.id,
        client_ip=request.client.host if request.client else "unknown",
        paused=str(body.live_sharing_paused).lower(),
        viewers=str(len(viewer_ids)),
    )
    return _my_shares(session, user)
