from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base
from app.models.types import TZDateTime
from app.models.user import _new_uuid

# LiveSession.state values. "converted" is set by phase D's Convert to
# activity; until then a session ends as "finished".
LIVE_STATES = ("active", "paused", "finished", "converted")


class LiveSession(Base):
    """An activity in progress, uploaded point by point from the phone
    (issue #130, docs/LIVE-TRACKING-PLAN.md §2.1). Kept apart from
    `activities` so lists, filters, stats and export never see a half
    activity. Keyed by the phone's client_activity_id, which is also the
    final upload's idempotency key: that's how the two are linked."""

    __tablename__ = "live_sessions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "client_activity_id", name="uq_live_sessions_user_client_activity_id"
        ),
        Index("ix_live_sessions_last_update_at", "last_update_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_activity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    # Same JSON shape as SplitPlanIn; phase D writes it into a converted GPX.
    split_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # The phone's latest on-screen numbers (LiveMetricsIn), shown verbatim.
    latest_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Index of the next point the server expects; also the stored point count.
    next_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_update_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    # Set when the final upload (or phase D's convert) produced the activity.
    # A linked session takes no more points.
    activity_id: Mapped[str | None] = mapped_column(ForeignKey("activities.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)


class LivePoint(Base):
    __tablename__ = "live_points"

    session_id: Mapped[str] = mapped_column(ForeignKey("live_sessions.id"), primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    t: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    ele: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Increments on each resume after a pause, so the map doesn't draw a
    # straight line across the paused gap.
    segment: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
