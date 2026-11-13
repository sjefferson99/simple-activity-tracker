from sqlalchemy import Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ActivityBestEffort(Base):
    """One row per entry of an analysis's result["best_efforts"] (issue #190),
    so records and "PR / 2nd / 3rd" ranks are a plain indexed query instead
    of loading every activity's result JSON.

    Owner, activity type and start time are deliberately *not* copied here:
    they're joined from `activities`, so editing an activity's type can never
    leave a stale copy behind. Rewritten by app.records.replace_best_efforts()
    everywhere an analysis result is set, and removed by
    app.cascades.delete_activity_dependents() before its activity is deleted.
    """

    __tablename__ = "activity_best_efforts"

    activity_id: Mapped[str] = mapped_column(ForeignKey("activities.id"), primary_key=True)
    distance_m: Mapped[float] = mapped_column(Float, primary_key=True)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
