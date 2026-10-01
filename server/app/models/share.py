from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime


class UserShare(Base):
    """One owner -> viewer grant (issue #130, docs/LIVE-TRACKING-PLAN.md §2.1).
    Only the owner ever creates, changes or deletes it. A row with both flags
    false is deleted rather than kept, so "has a row" always means "can see
    something". `can_view_live` is unused until live sessions exist (phase B)."""

    __tablename__ = "user_shares"
    __table_args__ = (
        CheckConstraint("owner_id <> viewer_id", name="ck_user_shares_not_self"),
        Index("ix_user_shares_viewer_id", "viewer_id"),
    )

    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    viewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    can_view_live: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_view_history: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)


class ActivityShare(Base):
    """One finished activity shared with one extra viewer (issue #130 D2),
    independent of any account-level UserShare. History only."""

    __tablename__ = "activity_shares"
    __table_args__ = (Index("ix_activity_shares_viewer_id", "viewer_id"),)

    activity_id: Mapped[str] = mapped_column(ForeignKey("activities.id"), primary_key=True)
    viewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
