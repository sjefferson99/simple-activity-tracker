from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.live import LivePoint, LiveSession


@dataclass(frozen=True)
class NewLivePoint:
    t: datetime
    lat: float
    lon: float
    ele: float | None
    accuracy: float | None
    speed: float | None
    segment: int


class SqlAlchemyLiveSessionRepository:
    """Live sessions and their points (issue #130). Owner scoping is by
    `user_id` on every phone-facing lookup; viewer access is decided in
    app/sharing.py, never here."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_user(self, user_id: str, client_activity_id: str) -> LiveSession | None:
        stmt = select(LiveSession).where(
            LiveSession.user_id == user_id,
            LiveSession.client_activity_id == client_activity_id,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get(self, session_id: str) -> LiveSession | None:
        return self._session.get(LiveSession, session_id)

    def create(
        self,
        *,
        user_id: str,
        client_activity_id: str,
        activity_type: str,
        started_at: datetime,
        split_plan: dict[str, Any] | None,
    ) -> LiveSession:
        now = datetime.now(UTC)
        live = LiveSession(
            user_id=user_id,
            client_activity_id=client_activity_id,
            activity_type=activity_type,
            started_at=started_at,
            split_plan=split_plan,
            state="active",
            next_index=0,
            last_update_at=now,
            created_at=now,
        )
        self._session.add(live)
        self._session.flush()
        return live

    def append_points(
        self, live: LiveSession, from_index: int, points: Sequence[NewLivePoint]
    ) -> int:
        """Stores the points not already held (index >= live.next_index) and
        returns how many were new. The caller has already rejected a gap
        (from_index > next_index), so the batch always overlaps or abuts
        what's stored, and a retried batch is simply a no-op."""
        skip = live.next_index - from_index
        fresh = points[skip:] if skip > 0 else points
        for offset, point in enumerate(fresh):
            self._session.add(
                LivePoint(
                    session_id=live.id,
                    idx=live.next_index + offset,
                    t=point.t,
                    lat=point.lat,
                    lon=point.lon,
                    ele=point.ele,
                    accuracy=point.accuracy,
                    speed=point.speed,
                    segment=point.segment,
                )
            )
        live.next_index += len(fresh)
        return len(fresh)

    def points_since(self, session_id: str, from_index: int, limit: int) -> list[LivePoint]:
        stmt = (
            select(LivePoint)
            .where(LivePoint.session_id == session_id, LivePoint.idx >= from_index)
            .order_by(LivePoint.idx)
            .limit(limit)
        )
        return list(self._session.execute(stmt).scalars())

    def list_open_for_owner(self, user_id: str) -> list[LiveSession]:
        """The owner's sessions with no activity yet: in progress, paused,
        or finished but not uploaded (phase D's convert candidates)."""
        stmt = (
            select(LiveSession)
            .where(LiveSession.user_id == user_id, LiveSession.activity_id.is_(None))
            .order_by(LiveSession.started_at.desc())
        )
        return list(self._session.execute(stmt).scalars())

    def link_to_activity(self, user_id: str, client_activity_id: str, activity_id: str) -> None:
        """The final upload arrived: the session is finished, its points are
        no longer needed (the uploaded GPX is the record), and an open live
        page now points at the activity."""
        live = self.get_for_user(user_id, client_activity_id)
        if live is None or live.activity_id is not None:
            return
        now = datetime.now(UTC)
        live.activity_id = activity_id
        if live.state != "converted":
            live.state = "finished"
        live.finished_at = live.finished_at or now
        live.last_update_at = now
        self._delete_points(live.id)

    def delete(self, live: LiveSession) -> None:
        self._delete_points(live.id)
        self._session.delete(live)
        self._session.flush()

    def purge_last_updated_before(self, cutoff: datetime) -> int:
        """Drops every session (and its points) not updated since `cutoff` —
        plan §2.4's 30-day retention. Linked activities are untouched."""
        stale_ids = list(
            self._session.execute(
                select(LiveSession.id).where(LiveSession.last_update_at < cutoff)
            ).scalars()
        )
        if stale_ids:
            self._session.execute(delete(LivePoint).where(LivePoint.session_id.in_(stale_ids)))
            self._session.execute(delete(LiveSession).where(LiveSession.id.in_(stale_ids)))
        return len(stale_ids)

    def _delete_points(self, session_id: str) -> None:
        self._session.execute(delete(LivePoint).where(LivePoint.session_id == session_id))
