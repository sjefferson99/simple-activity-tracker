"""Best-effort records and ranks across a user's activities (issue #190).

`activity_best_efforts` mirrors each analysis's result["best_efforts"]; owner,
type and start time come from a join to `activities` (see ActivityBestEffort).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.activity import Activity
from app.models.activity_analysis import ActivityAnalysis, AnalysisStatus
from app.models.best_effort import ActivityBestEffort


def replace_best_efforts(session: Session, activity_id: str, result: dict[str, Any] | None) -> None:
    """Rewrites this activity's rows from an analysis result. Called wherever
    a result is set (upload/import, live-recovery replacement, reanalyze),
    after the activity row itself has been flushed. A failed analysis
    (result None) leaves the activity with no rows."""
    session.execute(delete(ActivityBestEffort).where(ActivityBestEffort.activity_id == activity_id))
    efforts = (result or {}).get("best_efforts") or []
    for effort in efforts:
        distance = effort.get("distance_meters")
        duration = effort.get("duration_seconds")
        if isinstance(distance, int | float) and isinstance(duration, int | float):
            session.add(
                ActivityBestEffort(
                    activity_id=activity_id, distance_m=float(distance), duration_s=float(duration)
                )
            )


def best_effort_ranks(session: Session, activity: Activity) -> dict[float, int]:
    """This activity's rank for each of its best efforts among the owner's
    same-type activities **as of its own start time** (D4): 1 is a PR when
    it was recorded, and a later faster effort doesn't change that. On an
    equal time, the earlier activity ranks first. Keyed by distance_m.

    Virtual activities are left out on both sides: a virtual activity gets
    no ranks (empty dict), and never pushes an outdoor one down."""
    if activity.is_virtual:
        return {}
    mine = list(
        session.execute(
            select(ActivityBestEffort.distance_m, ActivityBestEffort.duration_s).where(
                ActivityBestEffort.activity_id == activity.id
            )
        )
    )
    other = aliased(ActivityBestEffort)
    ranks: dict[float, int] = {}
    for distance_m, duration_s in mine:
        faster_before = session.execute(
            select(func.count())
            .select_from(other)
            .join(Activity, Activity.id == other.activity_id)
            .where(
                Activity.user_id == activity.user_id,
                Activity.activity_type == activity.activity_type,
                Activity.is_virtual.is_(False),
                Activity.id != activity.id,
                Activity.started_at <= activity.started_at,
                other.distance_m == distance_m,
                or_(
                    other.duration_s < duration_s,
                    and_(
                        other.duration_s == duration_s,
                        Activity.started_at < activity.started_at,
                    ),
                ),
            )
        ).scalar_one()
        ranks[distance_m] = faster_before + 1
    return ranks


@dataclass(frozen=True)
class BestEffortRecord:
    distance_m: float
    duration_s: float
    activity_id: str
    activity_title: str | None
    started_at: datetime

    @property
    def avg_speed_mps(self) -> float:
        return self.distance_m / self.duration_s if self.duration_s > 0 else 0.0


def best_effort_records(
    session: Session, user_id: str, activity_type: str
) -> list[BestEffortRecord]:
    """The current all-time fastest effort at each distance the user has one
    for, shortest distance first, from outdoor activities only (virtual
    ones never hold a record). Ties go to the earlier activity."""
    rows = session.execute(
        select(
            ActivityBestEffort.distance_m,
            ActivityBestEffort.duration_s,
            Activity.id,
            Activity.title,
            Activity.started_at,
        )
        .join(Activity, Activity.id == ActivityBestEffort.activity_id)
        .join(ActivityAnalysis, ActivityAnalysis.activity_id == Activity.id)
        .where(
            Activity.user_id == user_id,
            Activity.activity_type == activity_type,
            Activity.is_virtual.is_(False),
            ActivityAnalysis.status == AnalysisStatus.done,
        )
        .order_by(
            ActivityBestEffort.distance_m,
            ActivityBestEffort.duration_s,
            Activity.started_at,
        )
    )
    records: list[BestEffortRecord] = []
    for distance_m, duration_s, activity_id, title, started_at in rows:
        if records and records[-1].distance_m == distance_m:
            continue
        records.append(BestEffortRecord(distance_m, duration_s, activity_id, title, started_at))
    return records
