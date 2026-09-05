from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base
from app.models.types import TZDateTime
from app.models.user import _new_uuid


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "client_activity_id", name="uq_activities_user_client_activity_id"
        ),
        Index("ix_activities_user_started_at", "user_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_activity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    started_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    ended_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    # Phone uploads: a snapshot of DeviceToken.name at upload time (not a live
    # FK — survives the token later being revoked/deleted). Manual GPX
    # uploads: defaulted from the file's <gpx creator="..."> if present, else
    # blank; editable afterward either way.
    device_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # "running" or "cycling" — mirrors mobile's ActivityMode enum values on
    # the wire (mobile/lib/domain/tracking/activity_mode.dart).
    activity_type: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    # The phone's own numbers, stored verbatim — see ActivitySummary (app/api/v1/schemas.py).
    client_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    gpx_blob_key: Mapped[str] = mapped_column(String, nullable=False)
    gpx_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    gpx_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    source_platform: Mapped[str] = mapped_column(String(50), nullable=False)
    source_app_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
