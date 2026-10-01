"""Rows that hang off an activity or a user and must go before it does.

No table here has ON DELETE CASCADE or an ORM relationship() to rely on (see
Activity.tags' comment), so every delete path calls these explicitly, before
deleting the parent row. One place, so a new dependent table (issue #130's
shares and live sessions) can't be missed by one of the five delete paths.
"""

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.orm import Session

from app.models.live import LivePoint, LiveSession
from app.repositories.shares import SqlAlchemyShareRepository


def _delete_live_sessions(session: Session, condition: ColumnElement[bool]) -> None:
    ids = select(LiveSession.id).where(condition)
    session.execute(delete(LivePoint).where(LivePoint.session_id.in_(ids)))
    session.execute(delete(LiveSession).where(condition))


def delete_activity_dependents(session: Session, activity_id: str) -> None:
    """Per-activity shares, and the live session the activity came from."""
    SqlAlchemyShareRepository(session).delete_for_activity(activity_id)
    _delete_live_sessions(session, LiveSession.activity_id == activity_id)


def delete_user_dependents(session: Session, user_id: str) -> None:
    """Grants the user made or received, and their remaining live sessions.
    Call after their activities (and so delete_activity_dependents) are gone."""
    SqlAlchemyShareRepository(session).delete_for_user(user_id)
    _delete_live_sessions(session, LiveSession.user_id == user_id)
