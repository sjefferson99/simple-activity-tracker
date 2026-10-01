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

    def list_shares(self, owner_id: str) -> list[tuple[User, UserShare]]:
        """Every user the owner has granted anything to, with the grant."""
        stmt = (
            select(User, UserShare)
            .join(UserShare, UserShare.viewer_id == User.id)
            .where(UserShare.owner_id == owner_id)
            .order_by(User.display_name, User.id)
        )
        return [(user, share) for user, share in self._session.execute(stmt).all()]

    def get(self, owner_id: str, viewer_id: str) -> UserShare | None:
        return self._session.get(UserShare, (owner_id, viewer_id))

    def set_flags(self, owner_id: str, viewer_id: str, *, live: bool, history: bool) -> None:
        """Creates, updates or (both flags false) deletes the grant."""
        now = datetime.now(UTC)
        share = self.get(owner_id, viewer_id)
        if not live and not history:
            if share is not None:
                self._session.delete(share)
        elif share is None:
            self._session.add(
                UserShare(
                    owner_id=owner_id,
                    viewer_id=viewer_id,
                    can_view_live=live,
                    can_view_history=history,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            share.can_view_live = live
            share.can_view_history = history
            share.updated_at = now
        self._session.flush()

    def delete_share(self, owner_id: str, viewer_id: str) -> bool:
        share = self.get(owner_id, viewer_id)
        if share is None:
            return False
        self._session.delete(share)
        self._session.flush()
        return True

    def set_live_viewers(self, owner_id: str, viewer_ids: set[str]) -> None:
        """The phone's "live share with" list (issue #130 D4): exactly these
        users get Live; History flags are left as they are."""
        existing = {share.viewer_id: share for _, share in self.list_shares(owner_id)}
        for viewer_id in existing.keys() | viewer_ids:
            share = existing.get(viewer_id)
            self.set_flags(
                owner_id,
                viewer_id,
                live=viewer_id in viewer_ids,
                history=share.can_view_history if share is not None else False,
            )

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
