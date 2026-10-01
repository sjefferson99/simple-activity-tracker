"""Who may see whose activities (issue #130, docs/LIVE-TRACKING-PLAN.md §2.2).

This is the only place viewer access is decided. Every owner route keeps
scoping by `get_by_id_for_user(user.id, ...)`; viewer routes go through
`get_history_visible_activity`, and the "Shared with me" list through
`history_visible_clause`. Rules are evaluated on every request, never cached,
so a revocation applies to the viewer's very next request.
"""

from typing import Any

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.models.activity import Activity
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
