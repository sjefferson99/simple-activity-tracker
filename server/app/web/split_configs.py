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
from app.validation import (
    SPLIT_CONFIG_MAX_CUSTOM_SPLITS,
    SPLIT_CONFIG_NAME_MAX_LENGTH,
    ValidationFailedError,
    validate_name,
)
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
    # Set by _number_entries for rendering: "#3" for a single split, "a",
    # "b", … inside a repeat block, and the row's flat position in the form.
    label: str = ""
    index: int = 0


@dataclass
class _Entry:
    """One entry of a custom plan as the editor lays it out (issue #233): a
    single split, or a repeat block of rows run `repeat` times. `repeat` is
    the typed text (None for a single split), so an invalid count survives a
    re-render for Save to report."""

    rows: list[_CustomRow]
    repeat: str | None = None
    # "splits #first-#last" for a block, when every count before it parses.
    first_number: int | None = None
    last_number: int | None = None
    # Expanded splits one more row in this block adds (its repeat count).
    add_cost: int = 1

    @property
    def is_repeat(self) -> bool:
        return self.repeat is not None


@dataclass
class _PreviewRow:
    label: str
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
    over_cap: bool = False


_MAX_SPLITS = SPLIT_CONFIG_MAX_CUSTOM_SPLITS


def _parse_repeat(raw: str | None) -> int | None:
    """A block's repeat count, or None when it isn't a whole number >= 1."""
    try:
        count = int((raw or "").strip())
    except ValueError:
        return None
    return count if count >= 1 else None


def _row_letter(j: int) -> str:
    # Same labels as mobile's repeat block rows: a…z, then numbers.
    return chr(ord("a") + j) if j < 26 else str(j + 1)


def _entries_from_form(
    sizes: list[str],
    targets: list[str],
    entry_kind: list[str] | None,
    entry_repeat: list[str] | None,
    entry_rows: list[str] | None,
) -> list[_Entry]:
    """Rebuilds the editor's entries from the posted form. The rows arrive
    as one flat list (DOM order); entry_kind/entry_repeat/entry_rows say how
    many of them each entry takes. Anything inconsistent (or a form from
    before issue #233) falls back to one single split per row."""
    rows = [_CustomRow(size=s, target=t) for s, t in zip(sizes, targets, strict=False)]
    kinds = entry_kind or []
    repeats = entry_repeat or []
    try:
        counts = [int(c) for c in entry_rows or []]
    except ValueError:
        counts = []
    if (
        not kinds
        or not (len(kinds) == len(repeats) == len(counts))
        or any(c < 1 for c in counts)
        or sum(counts) != len(rows)
    ):
        return [_Entry(rows=[r]) for r in rows]
    entries: list[_Entry] = []
    position = 0
    for kind, repeat, count in zip(kinds, repeats, counts, strict=True):
        chunk = rows[position : position + count]
        position += count
        if kind == "repeat":
            entries.append(_Entry(rows=chunk, repeat=repeat))
        else:
            entries.extend(_Entry(rows=[r]) for r in chunk)
    return entries


def _entries_from_plan(plan: dict[str, object]) -> list[_Entry]:
    """A saved plan's entries: its stored layout when it has one (issue
    #233), else one single split per custom split."""

    def row(pair: object) -> _CustomRow:
        size, target = pair[0], pair[1]  # type: ignore[index]
        return _CustomRow(
            size=_display_size(plan, float(size)),
            target=_display_target(plan, float(target) if target is not None else None),
        )

    layout = plan.get("layout")
    if isinstance(layout, list) and layout:
        entries: list[_Entry] = []
        for item in layout:
            if "repeat" in item:
                entries.append(
                    _Entry(rows=[row(p) for p in item["splits"]], repeat=str(item["repeat"]))
                )
            else:
                entries.append(_Entry(rows=[row(item["split"])]))
        return entries
    custom_splits: list[object] = plan.get("custom_splits") or []  # type: ignore[assignment]
    return [_Entry(rows=[row(pair)]) for pair in custom_splits]


def _number_entries(entries: list[_Entry]) -> int:
    """Labels every row for rendering and returns the expanded split count
    (an unparseable repeat count counts as 1, so the cap checks still work
    while it's being typed)."""
    total = 0
    numbering_ok = True
    index = 0
    for entry in entries:
        if entry.is_repeat:
            count = _parse_repeat(entry.repeat)
            entry.add_cost = count or 1
            size = entry.add_cost * len(entry.rows)
            if count is None:
                numbering_ok = False
            entry.first_number = total + 1 if numbering_ok else None
            entry.last_number = total + size if numbering_ok else None
            for j, r in enumerate(entry.rows):
                r.label, r.index = _row_letter(j), index
                index += 1
            total += size
        else:
            for r in entry.rows:
                r.label = f"#{total + 1}" if numbering_ok else "#?"
                r.index = index
                index += 1
                total += 1
    return total


def _flat_rows(entries: list[_Entry]) -> list[_CustomRow]:
    return [r for e in entries for r in e.rows]


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
    entries: list[_Entry],
) -> _Preview:
    """Best-effort: an unparseable field just leaves its estimate blank
    rather than erroring — reporting validation errors is Save's job. One
    row per split as it will run: a repeat block is listed in full,
    numbered as if every repetition had been typed out."""
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
    number = 0  # the split's position in the expanded plan, as it will run
    for entry in entries:
        # Each row's estimate, worked out once: (equivalent, distance,
        # duration, targeted), or None when it doesn't parse.
        estimates: list[tuple[str, float | None, float | None, bool] | None] = []
        for r in entry.rows:
            if not r.size.strip():
                continue
            try:
                size = (
                    parse_mm_ss(r.size, field="")
                    if is_time
                    else parse_distance_size_to_meters(
                        r.size, field="", distance_unit=distance_unit
                    )
                )
                target = target_or_none(r.target, "")
            except SplitConfigFormError:
                preview.invalid = True
                estimates.append(None)
                continue
            distance, duration = _estimate(split_type, size, target)
            equivalent = _format_derived(split_type, distance_unit, distance, duration)
            estimates.append((equivalent, distance, duration, target is not None))
        times = 1
        if entry.is_repeat:
            parsed = _parse_repeat(entry.repeat)
            if parsed is None:
                # Can't expand without a count: show the rows once, no totals.
                preview.invalid = True
            elif number + parsed * len(estimates) > _MAX_SPLITS:
                # Over the cap (Save will refuse it): don't expand a huge
                # typed count, just show the rows once and say why.
                preview.invalid = preview.over_cap = True
                parsed = None
            times = parsed or 1
        # A repeat block is listed in full, one row per split it runs, as if
        # every repetition had been typed out (issue #233).
        for _ in range(times):
            for estimate in estimates:
                number += 1
                if estimate is None:
                    preview.rows.append(_PreviewRow(label=f"#{number}", equivalent=""))
                    continue
                equivalent, distance, duration, targeted = estimate
                if not targeted:
                    preview.untargeted += 1
                total_distance += distance or 0.0
                total_duration += duration or 0.0
                preview.rows.append(_PreviewRow(label=f"#{number}", equivalent=equivalent))
    if not preview.rows or preview.invalid:
        return preview
    if not is_time or preview.untargeted == 0:
        preview.total_distance = _format_preview_distance(total_distance, distance_unit)
    if is_time or preview.untargeted == 0:
        preview.total_time = format_duration(total_duration)
    return preview


def _attach_preview(context: dict[str, object]) -> dict[str, object]:
    """Adds the estimate panel plus what the entry list needs to render: row
    labels, the expanded split count and the 50-split cap."""
    entries: list[_Entry] = context["custom_entries"]  # type: ignore[assignment]
    context["preview"] = _build_preview(
        split_type=str(context["split_type"]),
        split_value_raw=str(context["split_value"]),
        targets_as=str(context["targets_as"]),
        plan_kind=str(context["plan_kind"]),
        rolling_target_raw=str(context["rolling_target"]),
        entries=entries,
    )
    context["expanded_total"] = _number_entries(entries)
    context["has_repeats"] = any(e.is_repeat for e in entries)
    context["max_splits"] = _MAX_SPLITS
    return context


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
        "custom_entries": [_Entry(rows=[_CustomRow(size="", target="")])],
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
    entries = (
        _entries_from_plan(plan) if is_custom else [_Entry(rows=[_CustomRow(size="", target="")])]
    )
    return {
        "config_id": config.id,
        "name": config.name,
        "split_type": plan.get("split_type") or "distance_km",
        "split_value": str(plan.get("split_value") or 1),
        "targets_as": plan.get("targets_as") or "pace",
        "plan_kind": "custom" if is_custom else "rolling",
        "rolling_target": rolling_target,
        "custom_entries": entries,
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


def _copy_name(name: str, taken: set[str]) -> str:
    """First free "<name> (copy)", "<name> (copy 2)", … for the user, with the
    original name shortened if needed so the suffix still fits the limit."""
    n = 1
    while True:
        suffix = " (copy)" if n == 1 else f" (copy {n})"
        candidate = name[: SPLIT_CONFIG_NAME_MAX_LENGTH - len(suffix)].rstrip() + suffix
        if candidate not in taken:
            return candidate
        n += 1


@router.get("/split-configs/{config_id}/duplicate")
def duplicate_split_config_page(
    config_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    """Opens the editor as a *new* config pre-filled from an existing one
    (issue #231). Nothing is saved until Save, which goes through the normal
    create path (validation, name-collision handling), so abandoning the
    page leaves no stray copy behind."""
    repo = SqlAlchemySplitConfigRepository(session)
    config = repo.get_for_user(user.id, config_id)
    if config is None:
        return Response(status_code=404)
    taken = {c.name for c in repo.list_for_user(user.id)}
    context = {
        "user": user,
        **_form_context_from_config(config),
        "config_id": None,
        "name": _copy_name(config.name, taken),
    }
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
    entry_kind: Annotated[list[str] | None, Form()] = None,
    entry_repeat: Annotated[list[str] | None, Form()] = None,
    entry_rows: Annotated[list[str] | None, Form()] = None,
    remove_row: Annotated[int | None, Form()] = None,
    remove_entry: Annotated[int | None, Form()] = None,
    add_to_block: Annotated[int | None, Form()] = None,
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
    setting changes (see _convert_target_text).

    Repeat blocks (issue #233): row_action=add_repeat appends a block of
    2 x [two blank rows]; add_to_block / remove_entry name an entry by its
    position, remove_row a row by its flat position. A block whose last
    row is removed goes with it. The 50-split cap applies to the expanded
    plan, so the add buttons are disabled at the cap and Save rejects a
    plan over it."""
    entries = _entries_from_form(
        split_size or [], split_target or [], entry_kind, entry_repeat, entry_rows
    )
    if remove_row is not None:
        position = 0
        for entry in entries:
            if remove_row < position + len(entry.rows):
                if remove_row >= position:
                    entry.rows.pop(remove_row - position)
                break
            position += len(entry.rows)
        entries = [e for e in entries if e.rows]
    elif remove_entry is not None and 0 <= remove_entry < len(entries):
        entries.pop(remove_entry)
    elif (
        add_to_block is not None
        and 0 <= add_to_block < len(entries)
        and entries[add_to_block].is_repeat
    ):
        entries[add_to_block].rows.append(_CustomRow(size="", target=""))
    elif row_action == "add":
        entries.append(_Entry(rows=[_CustomRow(size="", target="")]))
    elif row_action == "add_repeat":
        entries.append(
            _Entry(
                rows=[_CustomRow(size="", target=""), _CustomRow(size="", target="")],
                repeat="2",
            )
        )
    if not entries:
        entries = [_Entry(rows=[_CustomRow(size="", target="")])]
    rows = _flat_rows(entries)

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

        for r in rows:
            r.size = _convert_size_text(
                r.size,
                target_mps=_parse_target_or_none(
                    r.target, targets_as=from_targets_as, split_type=from_split_type
                ),
                from_split_type=from_split_type,
                to_split_type=split_type,
            )
            r.target = convert(r.target)
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
        "custom_entries": entries,
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
    entry_kind: Annotated[list[str] | None, Form()] = None,
    entry_repeat: Annotated[list[str] | None, Form()] = None,
    entry_rows: Annotated[list[str] | None, Form()] = None,
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
        entries=_entries_from_form(
            split_size or [], split_target or [], entry_kind, entry_repeat, entry_rows
        ),
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
    entries: list[_Entry],
) -> dict[str, object]:
    try:
        split_value = int(split_value_raw)
    except ValueError:
        raise SplitConfigFormError("split_value", "Enter a whole number") from None
    if split_value <= 0:
        raise SplitConfigFormError("split_value", "Must be greater than zero")

    distance_unit = "mi" if split_type == "distance_mi" else "km"

    if plan_kind == "custom":

        def parse_row(r: _CustomRow, i: int) -> list[float | None]:
            if split_type == "time_min":
                size = parse_mm_ss(r.size, field=f"split_size_{i}")
            else:
                size = parse_distance_size_to_meters(
                    r.size, field=f"split_size_{i}", distance_unit=distance_unit
                )
            target: float | None = None
            if r.target.strip():
                target = parse_target_to_mps(
                    r.target,
                    field=f"split_target_{i}",
                    targets_as=targets_as,
                    distance_unit=distance_unit,
                )
            return [size, target]

        too_many = SplitConfigFormError(
            "custom_rows", f"A plan can have at most {_MAX_SPLITS} splits after repeats"
        )
        custom_splits: list[list[float | None]] = []
        layout: list[dict[str, object]] = []
        index = 0
        for e, entry in enumerate(entries):
            parsed = []
            for r in entry.rows:
                if r.size.strip():
                    parsed.append(parse_row(r, index))
                index += 1
            if not parsed:
                continue
            if not entry.is_repeat:
                for pair in parsed:
                    layout.append({"split": pair})
                    custom_splits.append(pair)
                continue
            count = _parse_repeat(entry.repeat)
            if count is None:
                raise SplitConfigFormError(
                    f"entry_repeat_{e}", "Repeat counts must be whole numbers of at least 1"
                )
            # Check the size before expanding, so a huge count never
            # allocates a huge list.
            if len(custom_splits) + count * len(parsed) > _MAX_SPLITS:
                raise too_many
            layout.append({"repeat": count, "splits": parsed})
            custom_splits.extend(parsed * count)
        if not custom_splits:
            raise SplitConfigFormError("custom_rows", "Add at least one custom split")
        if len(custom_splits) > _MAX_SPLITS:
            raise too_many
        plan: dict[str, object] = {
            "split_type": split_type,
            "split_value": split_value,
            "rolling_target_mps": None,
            "custom_splits": custom_splits,
            "targets_as": targets_as,
        }
        if any("repeat" in item for item in layout):
            plan["layout"] = layout
        return plan

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
    entry_kind: Annotated[list[str] | None, Form()] = None,
    entry_repeat: Annotated[list[str] | None, Form()] = None,
    entry_rows: Annotated[list[str] | None, Form()] = None,
    overwrite: Annotated[bool, Form()] = False,
) -> Response:
    def form_entries() -> list[_Entry]:
        return _entries_from_form(
            split_size or [], split_target or [], entry_kind, entry_repeat, entry_rows
        )

    def _rerender(
        error: str, *, name_conflict: str | None = None, status_code: int = 400
    ) -> Response:
        entries = form_entries() or [_Entry(rows=[_CustomRow(size="", target="")])]
        context: dict[str, object] = {
            "user": user,
            "config_id": config_id or None,
            "name": name,
            "split_type": split_type,
            "split_value": split_value,
            "targets_as": targets_as,
            "plan_kind": plan_kind,
            "rolling_target": rolling_target,
            "custom_entries": entries,
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
        plan_input = _build_plan_json(
            split_type=split_type,
            split_value_raw=split_value,
            targets_as=targets_as,
            plan_kind=plan_kind,
            rolling_target_raw=rolling_target,
            entries=form_entries(),
        )
    except SplitConfigFormError as exc:
        return _rerender(str(exc))

    # Reuse SplitPlanIn's own validation as the final boundary — same
    # checks as the JSON API, so a web-saved config can never be stricter
    # or looser than one saved from the phone (docs/SPLIT-CONFIGS-PLAN.md
    # §1) — and its storage shape too.
    from app.api.v1.schemas import SplitPlanIn, split_plan_in_to_json

    try:
        plan_json = split_plan_in_to_json(SplitPlanIn.model_validate(plan_input))
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
