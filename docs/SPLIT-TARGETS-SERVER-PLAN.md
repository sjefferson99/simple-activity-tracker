# Server split-plan plan — issue #100

Status: **implemented, code-reviewed, and MERGED to `main` via PR #104
(2026-09-15).** All 7 work items (§4) done.
448 server tests, `ruff`/`ruff format`/`mypy --strict` clean, Snyk clean (no
new findings — the only pre-existing findings in touched files are two Low
path-traversal hits in `cli.py`'s `backup()`/Strava-import code, untouched
by this work). `openapi.json` regenerated and diffed — only the expected
new `split_plan` field on `ActivityOut` and the new `SplitPlanOut` schema.

Verified end-to-end against the real rebuilt `deploy/standalone-tls`
container (CLAUDE.md's server workflow): a real multipart upload of a GPX
carrying `sat:split_plan`/`sat:split_targets_as` extensions correctly stored
and returned `split_plan` on `ActivityOut`, with `analysis_version: 7` and
per-split `target_speed_mps`/`verdict` in the result; explicit
`?split_type=&split_value=` re-slicing correctly dropped the plan
(`split_targets_as: null`, no targets on the recomputed splits) while the
no-params path kept it; the web activity detail page rendered a Target
column with green/red-tinted pace cells and a correctly-directional
`▲/▼ ... fast/slow` delta; `docker logs` showed a clean migration
(`5a6b3dd72c96 -> 3f19b6fcb456`) and no tracebacks across the whole session.

**Follow-up fix, same session: "reset to my uploaded plan" link.** The user
found that once you re-slice via the split-size dropdown on the activity
detail page, there was no way back to the uploaded plan's own splits/targets
short of a full page reload (which does work — the top-level page always
renders from the stored, plan-aware `ActivityAnalysis.result` — but was
undiscoverable and unindicated). Added `GET
/activities/{id}/splits/reset` (`app/web/activities.py`): re-serves the
already-stored analysis result (no recompute) as the splits fragment, plus
an `hx-swap-oob` swap of the split-size `<input>`/`<select>` back to the
activity's own `split_type`/`split_value` so the visible controls don't keep
showing a stale re-sliced size. A "Reset to my uploaded plan" button appears
on `activity_detail.html` only when `activity.split_plan` is set (new field
on `_activity_view`, `app/web/activities.py`). 3 new tests (link only shown
when a plan exists, reset restores the plan+controls after a re-slice, 404
for a missing activity) — 451 server tests total, `ruff`/`ruff
format`/`mypy --strict` clean, Snyk clean (no new findings). Verified live
against the rebuilt dev container: uploaded a custom-plan GPX, confirmed the
reset link appears, re-sliced to 2-minute splits (Target column disappeared,
as expected), clicked reset (Target column and `Splits (1 km)` heading came
back, `split_value`/`split_type` controls correctly reset to `1`/`distance_km`
via the OOB swap), clean `docker logs` throughout.

**Second follow-up, same session: layout + a Speed column.** User feedback
after visually reviewing the reset button: it sat as its own block below the
`.split-controls` flex row (extra vertical gap, misaligned with the
row above) rather than reading as part of the same control group. Moved the
button inside the `<form class="split-controls">` flex row itself (now the
last item alongside the size input/unit select) and added `flex-wrap: wrap`
to `.split-controls` so it still wraps sanely on narrow screens instead of
overflowing. Also added a Speed column (`app/web/formatting.py`'s existing
`kmh` filter) to `partials/splits_table.html`, shown for every split
regardless of whether the activity has a plan — previously only Pace was
shown, so comparing a speed-formatted target (`targets_as: "speed"`) against
actual pace needed a mental unit conversion; Speed now sits right next to
Pace so the two speed numbers (actual vs. target) can be compared directly.
1 new test (`test_splits_table_always_shows_a_speed_column`) — 452 server
tests total, `ruff`/`ruff format`/`mypy --strict` clean. Verified live
against the rebuilt dev container: reset button now renders on the same
line as the split-size controls, Speed column present with correct values
(e.g. 14.0 km/h actual next to a 4.0 target correctly shown as 14.4 km/h),
clean `docker logs`.

**Real production gap found after merge, same day: `reanalyze` didn't
backfill `Activity.split_plan`.** After PR #104 merged and the user pulled
the new image to their real prod stack, an activity uploaded on
2026-09-15 (after #99 shipped on the phone, before #100 shipped on the
server) showed the new Speed column but not the reset button or the
custom-plan heading/controls fix. Traced to the database directly
(`activities.split_plan` was `NULL` for every recent row) rather than
guessed at — confirmed the running container's image digest matched the
just-pushed build first, ruling out a stale-image red herring. Root cause:
`Activity.split_plan` is set only at upload/import time (§2's "Storage"
bullet, as designed), and `reanalyze` — the standard recovery path for a
row analyzed under old logic — re-parsed the plan from the GPX only to feed
`AnalyzerV1.analyze()`, never writing it back to the column. Fixed:
`reanalyze` (`app/cli.py`) now sets `activity.split_plan` from the
re-parsed `SplitPlanData` (via the existing `_split_plan_to_json` helper,
imported from `app.api.v1.activities`) whenever the column is currently
null — never overwriting a real value, so this is strictly additive
recovery, not a change to what a fresh upload does. 2 new tests
(`test_reanalyze_backfills_a_null_split_plan_from_the_gpx`,
`test_reanalyze_never_overwrites_an_existing_split_plan`) — 465 server
tests total. Branch `server-100-reanalyze-backfill-split-plan`.

**Code review (direct, no sub-agents), same session.** One confirmed
finding: `format_speed_delta` decided "on target" via a near-zero absolute
threshold (0.05 km/h, or a rounded-to-0 seconds/km delta) instead of the
same ±5% relative ratio `_verdict`/the cell's colour class use — so a split
genuinely `on_target` (e.g. 4.90 m/s actual vs. a 5.0 m/s target, ratio
0.98) could still render a nonzero correction arrow inside its own green
cell. Fixed by computing the same `ratio = avg/target` and using
`_SPLIT_TARGET_TOLERANCE`-equivalent bounds to decide "on target" first,
then only computing the displayed km/h/seconds delta for the off-target
case — mirrors mobile's `formatSpeedDelta` (`units.dart`), which already
did this correctly. New `tests/test_web_formatting.py` (9 tests, including
a direct regression check against `_verdict`'s own boundaries in both pace
and speed modes) — 463 server tests total, `ruff`/`ruff format`/`mypy
--strict` clean, Snyk clean (no new findings). Verified live against the
rebuilt dev container with a real upload sitting exactly in the scenario
the review predicted (4.90 m/s actual, 5.0 target): the split now renders
`on target` in the tinted span instead of a spurious `▲ 0.4 km/h slow`.

**Third follow-up, same session: misleading size on a custom plan.** User
noticed the split-size controls and the "Splits (...)" heading showed "1
min"/"Kilometers" for a custom-plan activity, even though the custom plan's
splits are individually sized and never actually 1 min/1 km — that value is
only `SplitPlanData`'s rolling *base* size (used once the plan runs out),
not the size in effect. Added an `is_custom_plan` flag (true when
`activity.split_plan.custom_splits` is non-empty) threaded through the
initial page render, the reset route, and the re-slice fragment route
(always `False` there, since re-slicing to an explicit size is always a
real, single size). When true: the `<h2>` heading reads a plain "Splits"
instead of "Splits (1 km)", the split-size `<input>` is blank with a "—"
placeholder instead of showing "1", and the `<select>` shows a disabled "—"
placeholder option instead of pre-selecting "Kilometers". Picking a real
size still works exactly as before (a genuine re-slice, which correctly
drops the plan). 2 new tests (plain-plan regression guard showing the real
size is unaffected; custom-plan blanking) plus one existing reset test
updated to assert the corrected behavior — 454 server tests total,
`ruff`/`ruff format`/`mypy --strict` clean. Verified live against the
rebuilt dev container: custom-plan activity shows blank input/placeholder
select and a plain "Splits" heading on load and after Reset; explicit
re-slicing still shows the real picked size ("Splits (2 min)"); clean
`docker logs`.

Follow-up to #99 (merged to `main` via PR #103, 2026-09-15). Read
[docs/SPLIT-TARGETS-PLAN.md](SPLIT-TARGETS-PLAN.md) first — this file only
covers the server side.

Scope, from [issue #100](https://github.com/sjefferson99/simple-activity-tracker/issues/100):
make the server parse and use the `sat:split_target` / `sat:split_plan` /
`sat:split_targets_as` GPX extensions the phone now writes (currently parsed
by nothing — proven ignored by `server/tests/test_gpx_split_targets.py`).

## 1. What the phone writes (already locked in, see SPLIT-TARGETS-PLAN.md §4.2)

Root `<extensions>`, alongside the unchanged `sat:split_type`/`sat:split_value`:

| Element | When | Value |
|---|---|---|
| `sat:split_target` | rolling plan with a target | target speed, m/s, e.g. `2.222` |
| `sat:split_plan` | custom plan | `size@target;size@target;size` — sizes in metres/seconds per `split_type`, targets in m/s, omitted when null |
| `sat:split_targets_as` | always | `pace` or `speed` (display hint only) |

## 2. Design

- **Parsing** (`app/analysis/gpx_parser.py`): new `parse_split_plan(data) ->
  SplitPlanData | None` alongside the existing `parse_split_preference`
  (left as-is — still used standalone by nothing after this lands, but kept
  since it's a clean, separately-tested unit and `parse_split_plan` calls it
  internally for the `split_type`/`split_value` pair). `SplitPlanData` is a
  plain dataclass: `split_type`, `split_value` (from the existing parser),
  `rolling_target_mps: float | None`, `custom_splits: list[tuple[float,
  float | None]]` (size, target), `targets_as: Literal["pace", "speed"]`.
  Returns None under the same "never raises, missing/invalid means no plan"
  contract as `parse_split_preference`. A malformed single entry in
  `split_plan` (bad float, empty segment) invalidates the whole custom list
  (falls back to treating it as absent) rather than silently dropping one
  split — a partial plan is worse than none.
- **Storage**: new nullable `Activity.split_plan` JSON column (migration,
  same pattern as `f02d59257d57`'s `split_type`/`split_value` addition)
  storing `SplitPlanData` as JSON (`custom_splits` as `[[size, target], ...]`,
  `null` target). Written at upload/import time; also backfilled by the
  `reanalyze` CLI when null (see below) — unlike `split_type`/`split_value`,
  which really do stay upload-time-fixed forever. This is what lets a custom
  plan survive reanalysis without re-parsing the GPX's `sat:split_plan`
  every time, and is the source `AnalyzerV1` reads by default (see below)
  instead of taking the plan as a fresh parameter on every call site.
- **`AnalyzerV1.analyze()`**: gains an optional `split_plan: SplitPlanData |
  None = None` parameter. When given and `custom_splits` is non-empty,
  `_compute_splits` walks the custom sizes/targets by index instead of a
  constant boundary, then rolls on at `split_value`'s base size with no
  target once the custom list is exhausted (mirrors mobile's `SplitPlan.sizeOf`/
  `targetOf`, D5). When `split_plan` is given with no custom splits (rolling
  with a target), every split gets `rolling_target_mps` as its target. When
  `split_plan` is None, behavior is unchanged (existing constant-boundary
  splits, no target key). Each split dict gains `target_speed_mps: float |
  None` and `verdict: "on_target" | "too_fast" | "too_slow" | None` — same
  ±5% rule as mobile's `splitVerdict` (`domain/tracking/split_target.dart`),
  no grace period server-side (a finished split's full-duration average is
  never "too early", unlike the live tile). Result dict gains
  `"split_targets_as": "pace" | "speed" | None` (None when no plan) so the
  web page knows how to format the delta without re-deriving it.
- **`_compute_distance_splits`/`_compute_time_splits`**: today take a single
  `boundary_meters`/`boundary_seconds` constant. Refactor to take a
  size-lookup (metres or seconds for 0-based split index N) that returns
  `split_value`'s base size when N is past the custom list — same shape as
  mobile's `SplitPlan.sizeOf`. The interpolation/while-loop logic is
  otherwise unchanged; only what "the boundary for split N" resolves to
  changes. This is the same generalization SPLIT-TARGETS-PLAN.md §2 already
  worked out for the mobile `MetricsEngine` — same reasoning applies here:
  get the per-index lookup wrong and a sparse-GPS step spanning several
  custom splits credits the wrong boundary.
- **Upload/import path** (`app/api/v1/activities.py::_insert_activity_with_gpx`):
  call `parse_split_plan` instead of `parse_split_preference`; store the
  parsed plan on the new `Activity.split_plan` column; pass it into
  `AnalyzerV1.analyze()`.
- **Reanalyze CLI** (`app/cli.py`): re-parses the GPX's `sat:` extensions
  anyway (existing behavior for `split_type`/`split_value`) — do the same
  for the plan rather than reading the stored column, for consistency with
  how `split_type`/`split_value` are handled there (re-derived from the GPX
  every time, never trusted from the row). **Unlike** `split_type`/
  `split_value`, `Activity.split_plan` **is backfilled** when it's currently
  null (found post-merge: a real deployment had activities uploaded after
  #99 shipped on the phone but before #100 shipped on the server, so their
  GPX genuinely carries plan extensions but the row was inserted before the
  server understood them — reanalyze is the only recovery path for those
  rows short of a full re-upload/re-import, and without backfilling
  `split_plan` the analysis result would gain targets/verdicts but the web
  page's reset control and custom-plan heading fix would never appear for
  them). Never overwrites an already-set `split_plan` — same "what the
  activity was actually uploaded with" reasoning as leaving `split_type`/
  `split_value` alone.
- **Re-slice routes** (`GET .../analysis?split_type=&split_value=`, the web
  splits-fragment route): unchanged signature. When explicit query params
  are given, analysis is recomputed at that plain rolling size with **no**
  plan (matches issue #100's explicit instruction: "re-slicing drops
  targets, since they only apply to the planned sizes"). When no query
  params are given, the stored `Activity.split_plan` (if any) is used
  instead of always defaulting to a plain rolling split — this is the one
  behavior change to the "no params" path.
- **API surface** (`app/api/v1/schemas.py` / `ActivityOut`): add
  `split_plan: SplitPlanOut | None` to `ActivityOut` mirroring the stored
  column, so the app (a future #101 history screen) and the web page both
  know whether/what plan was used without inspecting `analysis.result`.
  `AnalysisOut.result` stays a loose `dict[str, Any]` (existing convention)
  — the new per-split `target_speed_mps`/`verdict` keys and the top-level
  `split_targets_as` need no schema change there.
- **Web page** (`app/templates/partials/splits_table.html`): add a Target
  column (blank when the split has none) and tint the pace cell green/red by
  `verdict`, matching mobile's D7 colour rule (`splitTargetTolerance = 0.05`,
  server computes the same ±5% band). `activity_detail.html`'s split-size
  control (`split_type`/`split_value` <select>/<input>) already lets the
  user re-slice — no change needed there beyond it now dropping the plan on
  submit, per the design above.

## 3. Explicitly out of scope (per issue #100)

- Changing what the phone writes.
- On-phone storage of the plan/targets (that's #101).
- A phone-side "view target vs actual after upload" screen.

## 4. Work items, in order (one branch, one PR per CLAUDE.md's server workflow)

1. `SplitPlanData` + `parse_split_plan` in `gpx_parser.py`, tests (malformed
   entries, absent extensions, rolling-with-target, custom, targets_as).
2. `Activity.split_plan` migration + column; wire into upload/import insert
   and `_activity_out`/web view.
3. `AnalyzerV1` generalization: per-index size/target lookup, verdict,
   `split_targets_as` in the result. Tests: custom plan with a sparse step
   spanning two boundaries (mirrors mobile's regression test), roll-on with
   no target, rolling-with-target, verdict boundaries at exactly ±5%,
   `split_plan=None` unchanged-output regression test.
4. Re-slice routes: use stored plan when no explicit params; drop plan when
   explicit params given. Reanalyze CLI re-parses plan from GPX.
5. API schema (`ActivityOut.split_plan`), openapi.json regenerated and
   diffed.
6. Web splits table: Target column + verdict tint.
7. Docs: this file's status line, CLAUDE.md status entry.

Follow CLAUDE.md's "Server dev/test workflow" for branching/testing/sign-off
— local integration test against the real `deploy/standalone-tls` container
with a real custom-plan GPX (the S23 capture already produced during #99's
verification, or a synthetic fixture) before asking for sign-off.
