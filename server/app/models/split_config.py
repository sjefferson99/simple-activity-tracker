from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base
from app.models.types import TZDateTime
from app.models.user import _new_uuid


class SplitConfig(Base):
    """A named, reusable split plan (issue #126), owned by one user — the
    server-side counterpart of mobile's SplitPlanController state, except
    there can be many of these per user and they are only ever copied into
    the phone's single "current plan" on selection, never live-linked to it
    (see docs/SPLIT-CONFIGS-PLAN.md O5). Distinct from Activity.split_plan,
    which is a per-activity snapshot taken at upload time and never
    references a SplitConfig row."""

    __tablename__ = "split_configs"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_split_configs_user_id_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Same JSON shape as Activity.split_plan / app.api.v1.schemas.SplitPlanOut
    # / app.analysis.gpx_parser.SplitPlanData — split_type, split_value,
    # rolling_target_mps, custom_splits, targets_as. Validated at the API
    # boundary (app.split_configs.validation), not by a DB constraint, same
    # convention as Activity's own untyped JSON columns.
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
