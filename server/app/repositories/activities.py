import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from sqlalchemy import UnaryExpression, func, select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.activity_analysis import ActivityAnalysis

ActivityListSort = Literal["date", "distance"]
ActivityListDirection = Literal["asc", "desc"]


class InvalidCursorError(ValueError):
    """Raised when a pagination cursor can't be decoded — either tampered
    with or from an incompatible client. Callers map this to a 400."""


@dataclass(frozen=True)
class ActivityPage:
    activities: list[Activity]
    next_cursor: str | None


@dataclass(frozen=True)
class ActivityListPage:
    """Offset/page-numbered result for the web activity list (issue #75) —
    distinct from ActivityPage's cursor-based "load more" shape, which the
    mobile sync API, export, and admin still use unchanged. Each activity is
    paired with its analysis (None if not yet analyzed/failed) since there's
    no ORM relationship() between the two models (see Activity.tags' comment
    on why — plain FKs throughout, no delete cascade to rely on)."""

    activities: list[tuple[Activity, ActivityAnalysis | None]]
    total: int
    page: int
    per_page: int | None  # None means "all"
    total_pages: int


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
    def list_for_user_page(
        self,
        user_id: str,
        *,
        page: int,
        per_page: int | None,
        sort: ActivityListSort,
        direction: ActivityListDirection,
    ) -> ActivityListPage: ...
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

    def list_for_user_page(
        self,
        user_id: str,
        *,
        page: int,
        per_page: int | None,
        sort: ActivityListSort,
        direction: ActivityListDirection,
    ) -> ActivityListPage:
        """Page-numbered, sortable listing for the web activity list (issue
        #75) — a LEFT JOIN against activity_analyses so activities with no
        analysis row yet (upload/analysis failed) still appear, sorted as if
        their distance were 0 (see ActivityAnalysis.distance_meters' own
        default, which this mirrors via COALESCE for pre-migration rows).
        `page` is clamped to the real last page here (not just floored to 1
        by the caller) so a stale/out-of-range page number — a bookmarked
        URL, or activities deleted since — costs one extra query at most,
        never a second full page+count round trip."""
        total = self._session.execute(
            select(func.count(Activity.id)).where(Activity.user_id == user_id)
        ).scalar_one()

        effective_per_page = per_page if per_page is not None else max(total, 1)
        total_pages = max(1, -(-total // effective_per_page))
        page = min(max(page, 1), total_pages)

        distance = func.coalesce(ActivityAnalysis.distance_meters, 0.0)
        primary_order: UnaryExpression[Any]
        if sort == "distance":
            primary_order = distance.asc() if direction == "asc" else distance.desc()
        else:
            primary_order = (
                Activity.started_at.asc() if direction == "asc" else Activity.started_at.desc()
            )
        # A stable tiebreaker keeps page boundaries deterministic when the
        # sort key repeats (e.g. two activities with the same distance).
        tiebreaker = Activity.id.asc() if direction == "asc" else Activity.id.desc()

        stmt = (
            select(Activity, ActivityAnalysis)
            .outerjoin(ActivityAnalysis, ActivityAnalysis.activity_id == Activity.id)
            .where(Activity.user_id == user_id)
            .order_by(primary_order, tiebreaker)
            .offset((page - 1) * per_page if per_page is not None else 0)
        )
        if per_page is not None:
            stmt = stmt.limit(per_page)

        activities = [tuple(row) for row in self._session.execute(stmt).all()]
        return ActivityListPage(
            activities=activities,
            total=total,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
        )

    def delete(self, activity: Activity) -> None:
        self._session.delete(activity)
