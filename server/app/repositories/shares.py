from datetime import UTC, datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.models.share import ActivityShare, UserShare
from app.models.user import User


class SqlAlchemyShareRepository:
    """Owner-side reads and writes of UserShare/ActivityShare (issue #130).
    Every write method takes the owner explicitly: callers pass the signed-in
    user, never an id from the request, so a user can only ever change their
    own grants. Visibility *checks* live in app/sharing.py, not here."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- account-level grants -------------------------------------------

    def list_history_viewers(self, owner_id: str) -> list[User]:
        stmt = (
            select(User)
            .join(UserShare, UserShare.viewer_id == User.id)
            .where(UserShare.owner_id == owner_id, UserShare.can_view_history.is_(True))
            .order_by(User.display_name, User.id)
        )
        return list(self._session.execute(stmt).scalars())

    def get(self, owner_id: str, viewer_id: str) -> UserShare | None:
        return self._session.get(UserShare, (owner_id, viewer_id))

    def grant_history(self, owner_id: str, viewer_id: str) -> None:
        now = datetime.now(UTC)
        share = self.get(owner_id, viewer_id)
        if share is None:
            self._session.add(
                UserShare(
                    owner_id=owner_id,
                    viewer_id=viewer_id,
                    can_view_live=False,
                    can_view_history=True,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            share.can_view_history = True
            share.updated_at = now
        self._session.flush()

    def revoke_history(self, owner_id: str, viewer_id: str) -> bool:
        """Returns whether anything was revoked."""
        share = self.get(owner_id, viewer_id)
        if share is None or not share.can_view_history:
            return False
        if share.can_view_live:
            share.can_view_history = False
            share.updated_at = datetime.now(UTC)
        else:
            # Both flags false: delete rather than keep an empty grant.
            self._session.delete(share)
        self._session.flush()
        return True

    # --- per-activity extras ---------------------------------------------

    def list_activity_viewers(self, activity_id: str) -> list[User]:
        stmt = (
            select(User)
            .join(ActivityShare, ActivityShare.viewer_id == User.id)
            .where(ActivityShare.activity_id == activity_id)
            .order_by(User.display_name, User.id)
        )
        return list(self._session.execute(stmt).scalars())

    def add_activity_viewer(self, activity_id: str, viewer_id: str) -> None:
        if self._session.get(ActivityShare, (activity_id, viewer_id)) is None:
            self._session.add(
                ActivityShare(
                    activity_id=activity_id, viewer_id=viewer_id, created_at=datetime.now(UTC)
                )
            )
            self._session.flush()

    def remove_activity_viewer(self, activity_id: str, viewer_id: str) -> bool:
        share = self._session.get(ActivityShare, (activity_id, viewer_id))
        if share is None:
            return False
        self._session.delete(share)
        self._session.flush()
        return True

    # --- cascades ----------------------------------------------------------
    # No ON DELETE CASCADE / relationship() anywhere in this schema (see
    # Activity.tags' comment), so every activity/user delete path calls these
    # explicitly, before the parent row is deleted.

    def delete_for_activity(self, activity_id: str) -> None:
        self._session.execute(delete(ActivityShare).where(ActivityShare.activity_id == activity_id))

    def delete_for_user(self, user_id: str) -> None:
        """Every grant the user made or received, and every per-activity share
        they received. Shares *of* their activities go with each activity via
        delete_for_activity."""
        self._session.execute(
            delete(UserShare).where(
                or_(UserShare.owner_id == user_id, UserShare.viewer_id == user_id)
            )
        )
        self._session.execute(delete(ActivityShare).where(ActivityShare.viewer_id == user_id))


def shareable_users(session: Session, owner_id: str, *, exclude_ids: set[str]) -> list[User]:
    """The dropdown of users the owner can pick (D5): every enabled user
    except the owner and `exclude_ids` (already granted)."""
    stmt = (
        select(User)
        .where(User.id != owner_id, User.disabled_at.is_(None))
        .order_by(User.display_name, User.id)
    )
    return [u for u in session.execute(stmt).scalars() if u.id not in exclude_ids]
