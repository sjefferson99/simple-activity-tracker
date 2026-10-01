"""Who may see whose activities (issue #130, docs/LIVE-TRACKING-PLAN.md §2.2).

This is the only place viewer access is decided. Every owner route keeps
scoping by `get_by_id_for_user(user.id, ...)`; viewer routes go through
`get_history_visible_activity` or `live_access`, and the "Shared with me"
lists through `history_visible_clause` and `live_sessions_visible_to`. Rules
are evaluated on every request, never cached, so a revocation applies to the
viewer's very next request.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.live import LiveSession
from app.models.share import ActivityShare, UserShare
from app.models.user import User


def history_visible_clause(viewer_id: str) -> Any:
    """SQL condition on `Activity`: someone else's activity that `viewer_id`
    may see in their history, either through the owner's account-level
    History grant or a per-activity share. A disabled owner's activities are
    hidden from everyone."""
    account_grant = exists(
        select(1).where(
            UserShare.owner_id == Activity.user_id,
            UserShare.viewer_id == viewer_id,
            UserShare.can_view_history.is_(True),
        )
    )
    activity_grant = exists(
        select(1).where(
            ActivityShare.activity_id == Activity.id,
            ActivityShare.viewer_id == viewer_id,
        )
    )
    owner_enabled = exists(select(1).where(User.id == Activity.user_id, User.disabled_at.is_(None)))
    return and_(
        Activity.user_id != viewer_id,
        owner_enabled,
        or_(account_grant, activity_grant),
    )


def get_history_visible_activity(
    session: Session, viewer_id: str, activity_id: str
) -> Activity | None:
    stmt = select(Activity).where(Activity.id == activity_id, history_visible_clause(viewer_id))
    return session.execute(stmt).scalar_one_or_none()


def owners_visible_to(session: Session, viewer_id: str) -> list[User]:
    """Owners with at least one activity the viewer can see — the Owner
    filter on the "Shared with me" tab."""
    visible_owner_ids = select(Activity.user_id).where(history_visible_clause(viewer_id)).distinct()
    stmt = select(User).where(User.id.in_(visible_owner_ids)).order_by(User.display_name, User.id)
    return list(session.execute(stmt).scalars())


# --- live sessions -----------------------------------------------------------

# A session that hasn't updated for this long drops off every viewer's view
# (plan §2.4): the phone is presumably dead or out of signal for good, and an
# "In progress" entry from yesterday helps nobody. The owner still sees it.
LIVE_VIEWER_STALE_AFTER = timedelta(hours=12)

LiveAccess = Literal["live", "finished", "none"]


def _is_closed(live: LiveSession) -> bool:
    return live.activity_id is not None or live.state in ("finished", "converted")


def _holds_live_grant(session: Session, viewer_id: str, live: LiveSession) -> bool:
    """The owner currently lets this viewer watch them live: not themselves,
    owner enabled, owner hasn't paused live sharing, and a Live grant."""
    if live.user_id == viewer_id:
        return False
    owner = session.get(User, live.user_id)
    if owner is None or owner.disabled_at is not None or owner.live_sharing_paused:
        return False
    share = session.get(UserShare, (live.user_id, viewer_id))
    return share is not None and share.can_view_live


def live_access(
    session: Session, viewer_id: str, live: LiveSession, *, now: datetime | None = None
) -> LiveAccess:
    """What a (non-owner) viewer may see of a live session (plan D8):
    "live" while it runs, "finished" once it ends (a notice with no data),
    and "none" otherwise. Live access always ends at completion; the finished
    activity is visible only through a separate History grant."""
    if not _holds_live_grant(session, viewer_id, live):
        return "none"
    if _is_closed(live):
        return "finished"
    now = now or datetime.now(UTC)
    if now - live.last_update_at > LIVE_VIEWER_STALE_AFTER:
        return "none"
    return "live"


def live_sessions_visible_to(session: Session, viewer_id: str) -> list[tuple[LiveSession, User]]:
    """Running sessions the viewer may watch now — the Shared tab's Live now
    list. Same rules as live_access, as one query."""
    cutoff = datetime.now(UTC) - LIVE_VIEWER_STALE_AFTER
    stmt = (
        select(LiveSession, User)
        .join(User, User.id == LiveSession.user_id)
        .join(
            UserShare,
            and_(UserShare.owner_id == LiveSession.user_id, UserShare.viewer_id == viewer_id),
        )
        .where(
            LiveSession.user_id != viewer_id,
            LiveSession.activity_id.is_(None),
            LiveSession.state.in_(("active", "paused")),
            LiveSession.last_update_at >= cutoff,
            UserShare.can_view_live.is_(True),
            User.disabled_at.is_(None),
            User.live_sharing_paused.is_(False),
        )
        .order_by(LiveSession.started_at.desc())
    )
    return [(live, owner) for live, owner in session.execute(stmt).all()]


def live_viewers_of(session: Session, owner: User) -> list[User]:
    """Who can watch the owner live right now (empty while paused)."""
    if owner.live_sharing_paused:
        return []
    stmt = (
        select(User)
        .join(UserShare, UserShare.viewer_id == User.id)
        .where(
            UserShare.owner_id == owner.id,
            UserShare.can_view_live.is_(True),
            User.disabled_at.is_(None),
        )
        .order_by(User.display_name, User.id)
    )
    return list(session.execute(stmt).scalars())
