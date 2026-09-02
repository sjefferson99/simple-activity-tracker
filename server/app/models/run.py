from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base
from app.models.types import TZDateTime
from app.models.user import _new_uuid


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("user_id", "client_run_id", name="uq_runs_user_client_run_id"),
        Index("ix_runs_user_started_at", "user_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    started_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    ended_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    # The phone's own numbers, stored verbatim — see RunSummary (app/api/v1/schemas.py).
    client_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    gpx_blob_key: Mapped[str] = mapped_column(String, nullable=False)
    gpx_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    gpx_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    source_platform: Mapped[str] = mapped_column(String(50), nullable=False)
    source_app_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
