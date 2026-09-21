import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from sqlalchemy import Select, UnaryExpression, and_, exists, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Exists

from app.analysis.geo_math import equirectangular_scale
from app.models.activity import Activity
from app.models.activity_analysis import ActivityAnalysis
from app.models.tag import Tag, activity_tags

ActivityListSort = Literal["date", "distance"]
ActivityListDirection = Literal["asc", "desc"]
ActivityListGeoMode = Literal["start", "finish", "either", "both"]
ActivityListType = Literal["running", "cycling", "walking"]

# LIKE needs its wildcard/escape characters escaped in user-supplied text, or
# a search for a literal "%" or "_" would behave as a wildcard instead —
# see ActivityListFilters/_apply_filters below.
_LIKE_ESCAPE = "\\"
_MAX_TEXT_TERMS = 10
_MAX_TEXT_CHARS = 200


def _escape_like(term: str) -> str:
    return (
        term.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", f"{_LIKE_ESCAPE}%")
        .replace("_", f"{_LIKE_ESCAPE}_")
    )


@dataclass(frozen=True)
class ActivityListFilters:
    """Optional filters for `list_for_user_page` (issue #76). Every field
    defaults to "no filter" so existing callers (and every pre-#76 test) are
    unaffected. `text` matches title, notes, or any attached tag's name —
    every whitespace-separated term must match *something* (not necessarily
    the same column), case-insensitively. `min_m`/`max_m` bound the same
    denormalized distance the list already sorts and displays (issue #75).
    `lat`/`lon`/`radius_m`/`geo` filter by proximity to an activity's start
    and/or finish coordinates (see ActivityAnalysis.start_lat etc., added in
    a companion PR) — only applied when both `lat` and `lon` are set.
    `activity_type` restricts to exactly one of running/cycling/walking
    (issue #129) — None means "any type", not "none"."""

    text: str | None = None
    min_m: float | None = None
    max_m: float | None = None
    lat: float | None = None
    lon: float | None = None
    radius_m: float | None = None
    geo: ActivityListGeoMode = "either"
    activity_type: ActivityListType | None = None

    def is_active(self) -> bool:
        return (
            bool(self.text)
            or self.min_m is not None
            or self.max_m is not None
            or (self.lat is not None and self.lon is not None)
            or self.activity_type is not None
        )


_NO_FILTERS = ActivityListFilters()


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
        filters: ActivityListFilters = _NO_FILTERS,
    ) -> ActivityListPage: ...
    def most_recent_start_point(self, user_id: str) -> tuple[float, float] | None: ...
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
        filters: ActivityListFilters = _NO_FILTERS,
    ) -> ActivityListPage:
        """Page-numbered, sortable, filterable listing for the web activity
        list (issues #75, #76) — a LEFT JOIN against activity_analyses so
        activities with no analysis row yet (upload/analysis failed) still
        appear, sorted/filtered as if their distance were 0 (see
        ActivityAnalysis.distance_meters' own default, which this mirrors
        via COALESCE for pre-migration rows). `page` is clamped to the real
        last page here (not just floored to 1 by the caller) so a stale/
        out-of-range page number — a bookmarked URL, activities deleted
        since, or a filter that now matches fewer rows — costs one extra
        query at most, never a second full page+count round trip.

        The count and page queries are both derived from one filtered base
        statement (`_filtered_base`) so they can never drift apart — a bug
        where the count ignored a filter the page query applied (or vice
        versa) would silently show the wrong total_pages/total."""
        base = self._filtered_base(user_id, filters)
        base_subquery = base.subquery()

        total = self._session.execute(select(func.count()).select_from(base_subquery)).scalar_one()

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
            .select_from(base_subquery)
            .join(Activity, Activity.id == base_subquery.c.id)
            .outerjoin(ActivityAnalysis, ActivityAnalysis.activity_id == Activity.id)
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

    def _filtered_base(self, user_id: str, filters: ActivityListFilters) -> Select[tuple[str]]:
        """The set of activity ids matching `user_id` plus every active
        filter — the single source of truth both the count and the page
        query in list_for_user_page build on, so they can't disagree about
        which rows match. Selects just `Activity.id`: the outer queries
        re-select the full rows/columns they need, this only decides *which*
        ones."""
        stmt = (
            select(Activity.id)
            .outerjoin(ActivityAnalysis, ActivityAnalysis.activity_id == Activity.id)
            .where(Activity.user_id == user_id)
        )

        if filters.text:
            terms = filters.text.split()[:_MAX_TEXT_TERMS]
            for term in terms:
                term = term[:_MAX_TEXT_CHARS]
                pattern = f"%{_escape_like(term.lower())}%"
                tag_match: Exists = exists(
                    select(1)
                    .select_from(activity_tags)
                    .join(Tag, Tag.id == activity_tags.c.tag_id)
                    .where(
                        activity_tags.c.activity_id == Activity.id,
                        func.lower(Tag.name).like(pattern, escape=_LIKE_ESCAPE),
                    )
                )
                stmt = stmt.where(
                    or_(
                        func.lower(Activity.title).like(pattern, escape=_LIKE_ESCAPE),
                        func.lower(Activity.notes).like(pattern, escape=_LIKE_ESCAPE),
                        tag_match,
                    )
                )

        distance = func.coalesce(ActivityAnalysis.distance_meters, 0.0)
        if filters.min_m is not None:
            stmt = stmt.where(distance >= filters.min_m)
        if filters.max_m is not None:
            stmt = stmt.where(distance <= filters.max_m)

        if filters.activity_type is not None:
            stmt = stmt.where(Activity.activity_type == filters.activity_type)

        if filters.lat is not None and filters.lon is not None and filters.radius_m is not None:
            stmt = stmt.where(self._near_clause(filters))

        return stmt

    @staticmethod
    def _near_clause(filters: ActivityListFilters) -> Any:
        """Builds the "within radius_m of (lat, lon)" WHERE clause for the
        given geo mode — see equirectangular_scale's docstring for the
        approximation this is built on. A null start/end coordinate (an
        activity with no analysis, a failed one, or one analyzed before
        issue #76's endpoint columns existed) never satisfies the
        comparison — SQL's NULL semantics already give the right answer
        with no extra `IS NOT NULL` guard needed."""
        assert filters.lat is not None  # noqa: S101 -- caller already checked
        assert filters.lon is not None  # noqa: S101 -- caller already checked
        assert filters.radius_m is not None  # noqa: S101 -- caller already checked
        k_lat, k_lon = equirectangular_scale(filters.lat)
        radius_sq = filters.radius_m**2

        def near(lat_col: Any, lon_col: Any) -> Any:
            # Plain multiplication rather than func.power()/POWER(): SQLite
            # only exposes that as a math function when compiled with
            # -DSQLITE_ENABLE_MATH_FUNCTIONS (true for the dev/container
            # builds checked, but not guaranteed for every SQLite this app
            # might run against) — squaring by multiplying is portable SQL.
            d_lat = (lat_col - filters.lat) * k_lat
            d_lon = (lon_col - filters.lon) * k_lon
            return (d_lat * d_lat) + (d_lon * d_lon) <= radius_sq

        start_near = near(ActivityAnalysis.start_lat, ActivityAnalysis.start_lon)
        finish_near = near(ActivityAnalysis.end_lat, ActivityAnalysis.end_lon)

        if filters.geo == "start":
            return start_near
        if filters.geo == "finish":
            return finish_near
        if filters.geo == "both":
            return and_(start_near, finish_near)
        return or_(start_near, finish_near)  # "either"

    def most_recent_start_point(self, user_id: str) -> tuple[float, float] | None:
        """The user's most recently started activity's start coordinates, or
        None if they have no analysed activity with one — used only to pick
        a sensible initial center for the map picker (issue #76) so it
        doesn't open on the middle of the ocean for a first-time user.
        Deliberately ignores whether that activity's coordinates are null
        (no analysis, or analysed before the endpoint columns existed):
        `started_at DESC` naturally skips it in favor of an older activity
        that does have coordinates, at the cost of one extra row scanned in
        the rare case the very latest activity lacks them."""
        stmt = (
            select(ActivityAnalysis.start_lat, ActivityAnalysis.start_lon)
            .join(Activity, Activity.id == ActivityAnalysis.activity_id)
            .where(
                Activity.user_id == user_id,
                ActivityAnalysis.start_lat.isnot(None),
                ActivityAnalysis.start_lon.isnot(None),
            )
            .order_by(Activity.started_at.desc())
            .limit(1)
        )
        row = self._session.execute(stmt).first()
        return (row[0], row[1]) if row is not None else None

    def delete(self, activity: Activity) -> None:
        self._session.delete(activity)
