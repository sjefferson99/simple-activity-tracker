import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.activity import Activity


class InvalidCursorError(ValueError):
    """Raised when a pagination cursor can't be decoded — either tampered
    with or from an incompatible client. Callers map this to a 400."""


@dataclass(frozen=True)
class ActivityPage:
    activities: list[Activity]
    next_cursor: str | None


def encode_cursor(started_at: datetime, activity_id: str) -> str:
    raw = json.dumps([started_at.isoformat(), activity_id])
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        started_at_str, activity_id = json.loads(raw)
        return datetime.fromisoformat(started_at_str), activity_id
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise InvalidCursorError(f"Invalid cursor: {cursor!r}") from exc


class ActivityRepository(Protocol):
    def get_by_id_for_user(self, user_id: str, activity_id: str) -> Activity | None: ...
    def get_by_client_activity_id(
        self, user_id: str, client_activity_id: str
    ) -> Activity | None: ...
    def add(self, activity: Activity) -> None: ...
    def list_for_user(self, user_id: str, *, limit: int, cursor: str | None) -> ActivityPage: ...
    def delete(self, activity: Activity) -> None: ...


class SqlAlchemyActivityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id_for_user(self, user_id: str, activity_id: str) -> Activity | None:
        stmt = select(Activity).where(Activity.id == activity_id, Activity.user_id == user_id)
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_client_activity_id(self, user_id: str, client_activity_id: str) -> Activity | None:
        stmt = select(Activity).where(
            Activity.user_id == user_id, Activity.client_activity_id == client_activity_id
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def add(self, activity: Activity) -> None:
        self._session.add(activity)

    def list_for_user(self, user_id: str, *, limit: int, cursor: str | None) -> ActivityPage:
        stmt = (
            select(Activity)
            .where(Activity.user_id == user_id)
            .order_by(Activity.started_at.desc(), Activity.id.desc())
            .limit(limit + 1)
        )
        if cursor is not None:
            started_at, activity_id = decode_cursor(cursor)
            stmt = stmt.where(
                (Activity.started_at < started_at)
                | ((Activity.started_at == started_at) & (Activity.id < activity_id))
            )

        rows = list(self._session.execute(stmt).scalars())
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = encode_cursor(page[-1].started_at, page[-1].id) if has_more else None
        return ActivityPage(activities=page, next_cursor=next_cursor)

    def delete(self, activity: Activity) -> None:
        self._session.delete(activity)
