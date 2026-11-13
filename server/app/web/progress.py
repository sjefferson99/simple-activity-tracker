"""The Progress page (issue #190): period totals, trends and records across
the signed-in user's own activities of one type."""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.deps import db_session
from app.progress import (
    TREND_ROLLING_WINDOW,
    Granularity,
    activity_records,
    activity_types_for,
    compare_periods,
    load_activity_stats,
    period_buckets,
    resolve_timezone,
    trend,
)
from app.records import best_effort_records
from app.web.deps import WebUser
from app.web.templating import templates

router = APIRouter(tags=["web"], include_in_schema=False)


def _buckets_json(stats: Any, tz: Any, now: datetime) -> dict[str, list[dict[str, object]]]:
    return {
        granularity.value: [
            {
                "label": bucket.label,
                "count": bucket.totals.count,
                "distance_km": round(bucket.totals.distance_m / 1000, 2),
                "moving_h": round(bucket.totals.moving_s / 3600, 2),
                "gain_m": round(bucket.totals.gain_m),
            }
            for bucket in period_buckets(stats, tz, granularity, now)
        ]
        for granularity in Granularity
    }


def _trend_json(stats: Any) -> list[dict[str, object]]:
    return [
        {
            "t": int(point.started_at.timestamp()),
            "id": point.activity_id,
            "distance_km": round(point.distance_m / 1000, 3),
            "speed_kmh": round(point.avg_speed_mps * 3.6, 2),
            "rolling_distance_km": round(point.rolling_distance_m / 1000, 3),
            "rolling_speed_kmh": round(point.rolling_speed_mps * 3.6, 2),
        }
        for point in trend(stats)
    ]


@router.get("/progress")
def progress_page(
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    activity_type: Annotated[str | None, Query(alias="type", max_length=20)] = None,
    tz: Annotated[str | None, Query(max_length=64)] = None,
) -> Response:
    types = activity_types_for(session, user.id)
    tz_info, tz_name = resolve_timezone(tz)
    context: dict[str, object] = {
        "user": user,
        "types": types,
        "tz_name": tz_name,
        "tz_given": tz is not None,
    }
    if not types:
        return templates.TemplateResponse(request, "progress.html", context)

    selected = activity_type if activity_type in types else types[0]
    stats = load_activity_stats(session, user.id, selected)
    now = datetime.now(UTC)
    context.update(
        {
            "activity_type": selected,
            "show_pace": selected != "cycling",
            "comparisons": compare_periods(stats, tz_info, now),
            "buckets": _buckets_json(stats, tz_info, now),
            "trend_points": _trend_json(stats),
            "rolling_window": TREND_ROLLING_WINDOW,
            "effort_records": best_effort_records(session, user.id, selected),
            "activity_records": activity_records(stats, selected),
        }
    )
    return templates.TemplateResponse(request, "progress.html", context)
