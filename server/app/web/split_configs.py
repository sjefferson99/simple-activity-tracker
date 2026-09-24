"""Web editor for saved split configs (issue #126) — an ordinary
authenticated page (no admin gating), reachable from the main nav. Talks to
the repository layer directly, not to /api/v1/split-configs internally
(established rule — see CLAUDE.md's W2 notes), but reuses SplitPlanIn for
validation so a config saved from the web gets exactly the same checks as
one saved from the phone. See docs/SPLIT-CONFIGS-PLAN.md §4.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.rate_limit import account_action_rate_limiter
from app.deps import db_session
from app.models.split_config import SplitConfig
from app.repositories.split_configs import SqlAlchemySplitConfigRepository
from app.validation import SPLIT_CONFIG_NAME_MAX_LENGTH, ValidationFailedError, validate_name
from app.web.deps import WebUser, require_htmx_header
from app.web.formatting import format_duration
from app.web.split_config_forms import (
    SplitConfigFormError,
    parse_distance_size_to_meters,
    parse_mm_ss,
    parse_target_to_mps,
)
from app.web.templating import templates

router = APIRouter(tags=["web"], include_in_schema=False)

_METERS_PER_MILE = 1609.344


@dataclass
class _CustomRow:
    size: str
    target: str


@dataclass
class _PreviewRow:
    number: int
    equivalent: str


@dataclass
class _Preview:
    """What the plan being edited works out to at its targets (issue #134),
    mirroring mobile's Splits screen: a distance split's target gives a
    time, a time split's target gives a distance. A custom plan's measured
    dimension is always totalled; the derived one only when every split has
    a target, since a partial sum would understate it."""

    plan_kind: str
    derived_label: str
    per_split: str = ""
    rows: list[_PreviewRow] = field(default_factory=list)
    total_distance: str = ""
    total_time: str = ""
    untargeted: int = 0
    invalid: bool = False


def _trim_decimal(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _format_preview_distance(meters: float, distance_unit: str) -> str:
    """Mirrors mobile's formatSplitSizeMeters: whole metres/feet for short
    distances, otherwise km/mi trimmed to at most 2 decimals."""
    if distance_unit == "mi":
        miles = meters / _METERS_PER_MILE
        if miles < 0.1:
            return f"{round(meters * 3.280839895)} ft"
        return f"{_trim_decimal(miles)} mi"
    # Compare the rounded value: a computed 999.9999… m (e.g. 5 min at
    # 12 km/h) should read "1 km", not "1000 m".
    if round(meters) < 1000:
        return f"{round(meters)} m"
    return f"{_trim_decimal(meters / 1000)} km"


def _format_min_sec(seconds: float) -> str:
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes}:{secs:02d}"


def _estimate(
    split_type: str, size: float, target_mps: float | None
) -> tuple[float | None, float | None]:
    """(distance_m, duration_s) for one split; the derived half is None
    without a target."""
    if split_type == "time_min":
        return (size * target_mps if target_mps else None, size)
    return (size, size / target_mps if target_mps else None)


def _format_derived(
    split_type: str, distance_unit: str, distance: float | None, duration: float | None
) -> str:
    if split_type == "time_min":
        return _format_preview_distance(distance, distance_unit) if distance is not None else ""
    return _format_min_sec(duration) if duration is not None else ""


def _build_preview(
    *,
    split_type: str,
    split_value_raw: str,
    targets_as: str,
    plan_kind: str,
    rolling_target_raw: str,
    split_sizes: list[str],
    split_targets: list[str],
) -> _Preview:
    """Best-effort: an unparseable field just leaves its estimate blank
    rather than erroring — reporting validation errors is Save's job."""
    distance_unit = "mi" if split_type == "distance_mi" else "km"
    is_time = split_type == "time_min"
    preview = _Preview(
        plan_kind=plan_kind,
        derived_label="Distance at target" if is_time else "Time at target",
    )

    def target_or_none(raw: str, field_name: str) -> float | None:
        if not raw.strip():
            return None
        return parse_target_to_mps(
            raw, field=field_name, targets_as=targets_as, distance_unit=distance_unit
        )

    if plan_kind != "custom":
        try:
            value = int(split_value_raw)
            target = target_or_none(rolling_target_raw, "rolling_target")
        except (ValueError, SplitConfigFormError):
            return preview
        if value <= 0 or target is None:
            return preview
        meters_per_unit = _METERS_PER_MILE if split_type == "distance_mi" else 1000.0
        size = value * 60.0 if is_time else value * meters_per_unit
        distance, duration = _estimate(split_type, size, target)
        derived = _format_derived(split_type, distance_unit, distance, duration)
        preview.per_split = f"{derived} per split"
        return preview

    total_distance = 0.0
    total_duration = 0.0
    for i, (size_raw, target_raw) in enumerate(zip(split_sizes, split_targets, strict=False)):
        if not size_raw.strip():
            continue
        try:
            size = (
                parse_mm_ss(size_raw, field=f"split_size_{i}")
                if is_time
                else parse_distance_size_to_meters(
                    size_raw, field=f"split_size_{i}", distance_unit=distance_unit
                )
            )
            target = target_or_none(target_raw, f"split_target_{i}")
        except SplitConfigFormError:
            preview.invalid = True
            preview.rows.append(_PreviewRow(number=i + 1, equivalent=""))
            continue
        distance, duration = _estimate(split_type, size, target)
        if target is None:
            preview.untargeted += 1
        total_distance += distance or 0.0
        total_duration += duration or 0.0
        preview.rows.append(
            _PreviewRow(
                number=i + 1,
                equivalent=_format_derived(split_type, distance_unit, distance, duration),
            )
        )
    if not preview.rows or preview.invalid:
        return preview
    if not is_time or preview.untargeted == 0:
        preview.total_distance = _format_preview_distance(total_distance, distance_unit)
    if is_time or preview.untargeted == 0:
        preview.total_time = format_duration(total_duration)
    return preview


def _attach_preview(context: dict[str, object]) -> dict[str, object]:
    rows: list[_CustomRow] = context["custom_rows"]  # type: ignore[assignment]
    context["preview"] = _build_preview(
        split_type=str(context["split_type"]),
        split_value_raw=str(context["split_value"]),
        targets_as=str(context["targets_as"]),
        plan_kind=str(context["plan_kind"]),
        rolling_target_raw=str(context["rolling_target"]),
        split_sizes=[r.size for r in rows],
        split_targets=[r.target for r in rows],
    )
    return context


def _rows_from_plan(plan: dict[str, object]) -> list[_CustomRow]:
    custom_splits_raw = plan.get("custom_splits") or []
    custom_splits: list[list[object]] = custom_splits_raw  # type: ignore[assignment]
    rows = []
    for entry in custom_splits:
        size, target = float(entry[0]), entry[1]  # type: ignore[arg-type]
        rows.append(
            _CustomRow(
                size=_display_size(plan, size),
                target=_display_target(plan, float(target) if target is not None else None),  # type: ignore[arg-type]
            )
        )
    return rows


def _display_size(plan: dict[str, object], size_value: float) -> str:
    split_type = plan.get("split_type") or "distance_km"
    if split_type == "time_min":
        minutes, seconds = divmod(round(size_value), 60)
        return f"{minutes}:{seconds:02d}"
    meters_per_unit = 1609.344 if split_type == "distance_mi" else 1000.0
    return f"{size_value / meters_per_unit:g}"


def _display_target(plan: dict[str, object], target_mps: float | None) -> str:
    if target_mps is None:
        return ""
    targets_as = plan.get("targets_as") or "pace"
    if targets_as == "speed":
        return f"{round(target_mps * 3.6, 1):g}"
    split_type = plan.get("split_type") or "distance_km"
    meters_per_unit = 1609.344 if split_type == "distance_mi" else 1000.0
    total_seconds = round(meters_per_unit / target_mps)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _convert_target_text(
    raw: str, *, from_targets_as: str, from_split_type: str, to_plan: dict[str, object]
) -> str:
    """Re-expresses a typed target in the form's new pace/speed or km/mi
    setting (issue #134) — the phone keeps targets as m/s and just
    re-displays them, so the web form does the same rather than leaving
    "5:00" sitting in a field that now expects km/h. Text that doesn't parse
    under the old setting is left untouched for Save to report."""
    mps = _parse_target_or_none(raw, targets_as=from_targets_as, split_type=from_split_type)
    return raw if mps is None else _display_target(to_plan, mps)


def _parse_target_or_none(raw: str, *, targets_as: str, split_type: str) -> float | None:
    if not raw.strip():
        return None
    try:
        return parse_target_to_mps(
            raw,
            field="",
            targets_as=targets_as,
            distance_unit="mi" if split_type == "distance_mi" else "km",
        )
    except SplitConfigFormError:
        return None


def _convert_size_text(
    raw: str, *, target_mps: float | None, from_split_type: str, to_split_type: str
) -> str:
    """A custom split's size across a Minutes <-> km/mi switch (issue #134):
    converted through the split's own target so the workout stays the same
    (5:00 at 6 km/h <-> 0.5 km). Without a target (or with a size that
    doesn't parse) there's no sensible equivalent, so the size is blanked
    for the user to fill in. km <-> mi keeps the typed number unchanged —
    the owner's call, not converted."""
    from_time = from_split_type == "time_min"
    if from_time == (to_split_type == "time_min"):
        return raw
    if target_mps is None or not raw.strip():
        return ""
    try:
        if from_time:
            seconds = parse_mm_ss(raw, field="")
        else:
            meters = parse_distance_size_to_meters(
                raw,
                field="",
                distance_unit="mi" if from_split_type == "distance_mi" else "km",
            )
    except SplitConfigFormError:
        return ""
    if from_time:
        meters_per_unit = _METERS_PER_MILE if to_split_type == "distance_mi" else 1000.0
        # 3 decimals (metre-level), matching mobile's own size field — 2
        # would round a short interval to "0" and drift on a round trip.
        return f"{seconds * target_mps / meters_per_unit:.3f}".rstrip("0").rstrip(".")
    return _format_min_sec(meters / target_mps)


def _default_form_context(user: object) -> dict[str, object]:
    return {
        "user": user,
        "config_id": None,
        "name": "",
        "split_type": "distance_km",
        "split_value": "1",
        "targets_as": "pace",
        "plan_kind": "rolling",
        "rolling_target": "",
        "custom_rows": [_CustomRow(size="", target="")],
        "error": None,
        "name_conflict": None,
    }


def _form_context_from_config(config: SplitConfig) -> dict[str, object]:
    plan = config.plan
    is_custom = bool(plan.get("custom_splits"))
    rolling_target_mps = plan.get("rolling_target_mps")
    rolling_target = ""
    if rolling_target_mps is not None:
        rolling_target = _display_target(plan, float(rolling_target_mps))
    rows = _rows_from_plan(plan) if is_custom else [_CustomRow(size="", target="")]
    return {
        "config_id": config.id,
        "name": config.name,
        "split_type": plan.get("split_type") or "distance_km",
        "split_value": str(plan.get("split_value") or 1),
        "targets_as": plan.get("targets_as") or "pace",
        "plan_kind": "custom" if is_custom else "rolling",
        "rolling_target": rolling_target,
        "custom_rows": rows,
        "error": None,
        "name_conflict": None,
    }


@router.get("/split-configs")
def split_configs_page(
    request: Request, user: WebUser, session: Annotated[Session, Depends(db_session)]
) -> Response:
    configs = SqlAlchemySplitConfigRepository(session).list_for_user(user.id)
    context = {"user": user, "configs": configs}
    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse(request, "partials/split_config_list.html", context)
    return templates.TemplateResponse(request, "split_configs.html", context)


@router.get("/split-configs/new")
def new_split_config_page(request: Request, user: WebUser) -> Response:
    return templates.TemplateResponse(
        request, "split_config_form.html", _attach_preview(_default_form_context(user))
    )


@router.get("/split-configs/{config_id}/edit")
def edit_split_config_page(
    config_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    config = SqlAlchemySplitConfigRepository(session).get_for_user(user.id, config_id)
    if config is None:
        return Response(status_code=404)
    context = {"user": user, **_form_context_from_config(config)}
    return templates.TemplateResponse(request, "split_config_form.html", _attach_preview(context))


@router.post("/split-configs/custom-rows", dependencies=[Depends(require_htmx_header)])
def add_custom_row(
    request: Request,
    user: WebUser,
    config_id: Annotated[str, Form()] = "",
    name: Annotated[str, Form()] = "",
    split_type: Annotated[str, Form()] = "distance_km",
    split_value: Annotated[str, Form()] = "1",
    targets_as: Annotated[str, Form()] = "pace",
    plan_kind: Annotated[str, Form()] = "custom",
    rolling_target: Annotated[str, Form()] = "",
    split_size: Annotated[list[str] | None, Form()] = None,
    split_target: Annotated[list[str] | None, Form()] = None,
    remove_row: Annotated[int | None, Form()] = None,
    row_action: Annotated[str, Form()] = "refresh",
    prev_targets_as: Annotated[str, Form()] = "",
    prev_split_type: Annotated[str, Form()] = "",
) -> Response:
    """Re-renders the whole form: with one more custom-split row appended
    (row_action=add, sent only by the Add split button), one fewer
    (remove_row given), or otherwise unchanged — the Unit/Targets as/Every/
    plan-kind controls post here just to re-render for their new value, and
    must not grow the list (issue #134). The rest of the form's current
    values are carried through as hidden/regular fields on every request,
    same pattern as partials/activity_search_form.html's hidden filter
    fields. No validation here: rows are just text until Save is pressed,
    except that typed targets are converted when the pace/speed or km/mi
    setting changes (see _convert_target_text)."""
    sizes = split_size or []
    targets = split_target or []
    rows = [_CustomRow(size=s, target=t) for s, t in zip(sizes, targets, strict=False)]
    if remove_row is not None and 0 <= remove_row < len(rows):
        rows.pop(remove_row)
    elif row_action == "add":
        rows.append(_CustomRow(size="", target=""))
    if not rows:
        rows = [_CustomRow(size="", target="")]

    if (prev_targets_as and prev_targets_as != targets_as) or (
        prev_split_type and prev_split_type != split_type
    ):
        to_plan: dict[str, object] = {"split_type": split_type, "targets_as": targets_as}
        from_targets_as = prev_targets_as or targets_as
        from_split_type = prev_split_type or split_type

        def convert(text: str) -> str:
            return _convert_target_text(
                text,
                from_targets_as=from_targets_as,
                from_split_type=from_split_type,
                to_plan=to_plan,
            )

        rows = [
            _CustomRow(
                size=_convert_size_text(
                    r.size,
                    target_mps=_parse_target_or_none(
                        r.target, targets_as=from_targets_as, split_type=from_split_type
                    ),
                    from_split_type=from_split_type,
                    to_split_type=split_type,
                ),
                target=convert(r.target),
            )
            for r in rows
        ]
        rolling_target = convert(rolling_target)

    context: dict[str, object] = {
        "user": user,
        "config_id": config_id or None,
        "name": name,
        "split_type": split_type,
        "split_value": split_value,
        "targets_as": targets_as,
        "plan_kind": plan_kind,
        "rolling_target": rolling_target,
        "custom_rows": rows,
        "error": None,
        "name_conflict": None,
    }
    return templates.TemplateResponse(
        request, "partials/split_config_form_fields.html", _attach_preview(context)
    )


@router.post("/split-configs/preview", dependencies=[Depends(require_htmx_header)])
def split_config_preview(
    request: Request,
    user: WebUser,
    split_type: Annotated[str, Form()] = "distance_km",
    split_value: Annotated[str, Form()] = "1",
    targets_as: Annotated[str, Form()] = "pace",
    plan_kind: Annotated[str, Form()] = "rolling",
    rolling_target: Annotated[str, Form()] = "",
    split_size: Annotated[list[str] | None, Form()] = None,
    split_target: Annotated[list[str] | None, Form()] = None,
) -> Response:
    """Re-renders just the estimate panel as the user types (issue #134) —
    swapping only this panel, not the whole form, keeps focus in whichever
    field is being edited. Pure computation, nothing persisted."""
    preview = _build_preview(
        split_type=split_type,
        split_value_raw=split_value,
        targets_as=targets_as,
        plan_kind=plan_kind,
        rolling_target_raw=rolling_target,
        split_sizes=split_size or [],
        split_targets=split_target or [],
    )
    return templates.TemplateResponse(
        request, "partials/split_config_preview.html", {"user": user, "preview": preview}
    )


def _build_plan_json(
    *,
    split_type: str,
    split_value_raw: str,
    targets_as: str,
    plan_kind: str,
    rolling_target_raw: str,
    split_sizes: list[str],
    split_targets: list[str],
) -> dict[str, object]:
    try:
        split_value = int(split_value_raw)
    except ValueError:
        raise SplitConfigFormError("split_value", "Enter a whole number") from None
    if split_value <= 0:
        raise SplitConfigFormError("split_value", "Must be greater than zero")

    distance_unit = "mi" if split_type == "distance_mi" else "km"

    if plan_kind == "custom":
        custom_splits: list[list[float | None]] = []
        for i, (size_raw, target_raw) in enumerate(zip(split_sizes, split_targets, strict=False)):
            if not size_raw.strip():
                continue
            if split_type == "time_min":
                size = parse_mm_ss(size_raw, field=f"split_size_{i}")
            else:
                size = parse_distance_size_to_meters(
                    size_raw, field=f"split_size_{i}", distance_unit=distance_unit
                )
            target: float | None = None
            if target_raw.strip():
                target = parse_target_to_mps(
                    target_raw,
                    field=f"split_target_{i}",
                    targets_as=targets_as,
                    distance_unit=distance_unit,
                )
            custom_splits.append([size, target])
        if not custom_splits:
            raise SplitConfigFormError("custom_rows", "Add at least one custom split")
        return {
            "split_type": split_type,
            "split_value": split_value,
            "rolling_target_mps": None,
            "custom_splits": custom_splits,
            "targets_as": targets_as,
        }

    rolling_target_mps = None
    if rolling_target_raw.strip():
        rolling_target_mps = parse_target_to_mps(
            rolling_target_raw,
            field="rolling_target",
            targets_as=targets_as,
            distance_unit=distance_unit,
        )
    return {
        "split_type": split_type,
        "split_value": split_value,
        "rolling_target_mps": rolling_target_mps,
        "custom_splits": [],
        "targets_as": targets_as,
    }


@router.post("/split-configs", dependencies=[Depends(require_htmx_header)])
def create_or_update_split_config(
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    config_id: Annotated[str, Form()] = "",
    name: Annotated[str, Form()] = "",
    split_type: Annotated[str, Form()] = "distance_km",
    split_value: Annotated[str, Form()] = "1",
    targets_as: Annotated[str, Form()] = "pace",
    plan_kind: Annotated[str, Form()] = "rolling",
    rolling_target: Annotated[str, Form()] = "",
    split_size: Annotated[list[str] | None, Form()] = None,
    split_target: Annotated[list[str] | None, Form()] = None,
    overwrite: Annotated[bool, Form()] = False,
) -> Response:
    def _rerender(
        error: str, *, name_conflict: str | None = None, status_code: int = 400
    ) -> Response:
        rows = [
            _CustomRow(size=s, target=t)
            for s, t in zip(split_size or [], split_target or [], strict=False)
        ] or [_CustomRow(size="", target="")]
        context: dict[str, object] = {
            "user": user,
            "config_id": config_id or None,
            "name": name,
            "split_type": split_type,
            "split_value": split_value,
            "targets_as": targets_as,
            "plan_kind": plan_kind,
            "rolling_target": rolling_target,
            "custom_rows": rows,
            "error": error,
            "name_conflict": name_conflict,
        }
        return templates.TemplateResponse(
            request, "split_config_form.html", _attach_preview(context), status_code=status_code
        )

    client_ip = request.client.host if request.client else "unknown"
    if not account_action_rate_limiter.allow(f"ip:{client_ip}"):
        return _rerender("Too many attempts, try again shortly", status_code=429)

    try:
        clean_name = validate_name(name, field="Name")
        if len(clean_name) > SPLIT_CONFIG_NAME_MAX_LENGTH:
            raise ValidationFailedError(
                f"Name must be at most {SPLIT_CONFIG_NAME_MAX_LENGTH} characters"
            )
    except ValidationFailedError as exc:
        return _rerender(str(exc))

    try:
        plan_json = _build_plan_json(
            split_type=split_type,
            split_value_raw=split_value,
            targets_as=targets_as,
            plan_kind=plan_kind,
            rolling_target_raw=rolling_target,
            split_sizes=split_size or [],
            split_targets=split_target or [],
        )
    except SplitConfigFormError as exc:
        return _rerender(str(exc))

    # Reuse SplitPlanIn's own validation as the final boundary — same
    # checks as the JSON API, so a web-saved config can never be stricter
    # or looser than one saved from the phone (docs/SPLIT-CONFIGS-PLAN.md
    # §1).
    from app.api.v1.schemas import SplitPlanIn

    try:
        SplitPlanIn.model_validate(plan_json)
    except ValidationError as exc:
        return _rerender(str(exc.errors()[0]["msg"]) if exc.errors() else "Invalid split plan")

    repo = SqlAlchemySplitConfigRepository(session)

    if config_id:
        existing = repo.get_for_user(user.id, config_id)
        if existing is None:
            return Response(status_code=404)
        if clean_name != existing.name:
            collision = repo.get_by_name_for_user(user.id, clean_name)
            if collision is not None and collision.id != existing.id:
                return _rerender(
                    f"A split config named '{clean_name}' already exists.",
                    name_conflict=clean_name,
                    status_code=409,
                )
        existing.name = clean_name
        existing.plan = plan_json
        existing.updated_at = datetime.now(UTC)
        return Response(status_code=200, headers={"HX-Redirect": "/split-configs"})

    collision = repo.get_by_name_for_user(user.id, clean_name)
    if collision is not None and not overwrite:
        return _rerender(
            f"A split config named '{clean_name}' already exists.",
            name_conflict=clean_name,
            status_code=409,
        )
    if collision is not None and overwrite:
        collision.plan = plan_json
        collision.updated_at = datetime.now(UTC)
        return Response(status_code=200, headers={"HX-Redirect": "/split-configs"})

    now = datetime.now(UTC)
    new_config = SplitConfig(
        user_id=user.id, name=clean_name, plan=plan_json, created_at=now, updated_at=now
    )
    repo.add(new_config)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        # See app/api/v1/split_configs.py's create_split_config for why the
        # explicit rollback is required before the Session is usable again.
        session.rollback()
        return _rerender(
            f"A split config named '{clean_name}' already exists.",
            name_conflict=clean_name,
            status_code=409,
        )
    return Response(status_code=200, headers={"HX-Redirect": "/split-configs"})


@router.delete("/split-configs/{config_id}", dependencies=[Depends(require_htmx_header)])
def delete_split_config(
    config_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    client_ip = request.client.host if request.client else "unknown"
    if not account_action_rate_limiter.allow(f"ip:{client_ip}"):
        return Response(status_code=429)

    repo = SqlAlchemySplitConfigRepository(session)
    config = repo.get_for_user(user.id, config_id)
    if config is not None:
        repo.delete(config)
        # get_session_factory() disables autoflush (app/db.py) — without an
        # explicit flush, the immediately-following list_for_user query
        # below would still see the just-deleted row (caught by
        # test_delete_removes_config_from_list, which re-lists in the same
        # request rather than redirecting like activity_delete does).
        session.flush()
    configs = repo.list_for_user(user.id)
    return templates.TemplateResponse(
        request, "partials/split_config_list.html", {"user": user, "configs": configs}
    )
