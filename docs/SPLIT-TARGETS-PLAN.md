# Split targets plan — issue #99

Status: **approved 2026-09-14, implemented and committed to `mobile-99-split-targets`
2026-09-14/15 as a pending/pre-final-testing commit — not yet pushed or PR'd.** All six
work items (§6) done: domain model, engine generalized to variable split sizes,
persistence + GPX extensions + server ignore-test, live-screen tint/detail, the Splits
screen, docs. 279 mobile tests, `flutter analyze` clean, Snyk clean; 428 server tests
(4 new), `ruff`/`mypy --strict` clean, Snyk clean. Verified on a physical Samsung S23
(§7): idle/Splits-screen UI, persistence across relaunch, a real GPX capture's extensions
parsed by the server's real parser, and a real upload to the dev server. One real bug
found and fixed during this pass — see CLAUDE.md's status entry for the full account.
**Still outstanding, deliberately deferred**: the tile's live green/red/arrow behavior
and the grace period, which need real motion — the user has a run planned and will
report back before this is pushed/PR'd.

Handoff plan for whoever implements it — read CLAUDE.md first (architecture rules, the
commit-approval rule, the on-device verification habit), then this file end to end.

Scope, from [issue #99](https://github.com/sjefferson99/simple-activity-tracker/issues/99):

1. Let the user set a **target** for each split (as pace or speed) alongside the existing
   split size (distance or time), and see live whether they are too fast or too slow.
2. Two kinds of split plan: **rolling** (every split the same size, repeating until the
   run ends — what the app does today) or **custom** (an ordered list of splits whose
   size and target may each differ, e.g. 90 s @ 8 km/h, 60 s @ 5 km/h, …).
3. A **pace-or-speed preference** for how targets are entered and shown.
4. The configuration **persists between activities**.
5. A dedicated **Splits configuration screen** reached from the home screen.
6. The **live screen** shows the current split (its size and target) and tints the split
   metric green/red for on/off target.

## 1. Decisions (made with the owner on 2026-09-14 — do not re-open)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Live-screen layout | **Tinted split tile.** Keep the 5-tile grid; the "Split pace" tile gains a detail line (split number, size, target) and a green/red background. The big instantaneous readout stays uncoloured. See §5. |
| D2 | GPX / server | **Write the plan and targets into the GPX as extra `sat:` extensions; the server keeps ignoring them for now.** A follow-up issue will make the server honour them (variable-length splits, target vs actual on the web page). This issue changes no server behaviour — only adds a parser test proving the new extensions are ignored, as was done for `sat:accuracy`/`sat:speed`. |
| D3 | Where configuration lives | **A new Splits screen, opened from a summary row on the idle home screen.** The existing split-preference section moves out of Settings into it (Settings keeps a one-line link). Same reasoning as the Run/Cycle toggle living on the home screen: it changes how the next run is captured. |
| D4 | Target entry | **Pace or speed only**, per one global "targets as pace / speed" preference. The editor shows the equivalent split time (distance splits) or split distance (time splits) as a computed hint beside the field. No separate time-per-split input. |
| D5 | After the last custom split | **Roll on untargeted**: splits continue at the plan's base size with no target; tiles go uncoloured. |
| D6 | Mixing kinds in one plan | **One kind per plan** (all distance-km, all distance-mi, or all time). Only the size and target vary per split. Sizes are finer than the rolling preference's whole units — metres and seconds internally (the owner's own example is 90 s splits). |
| D7 | Colour rule | **Green within ±5 % of target speed, red outside in either direction**, plus an arrow and a delta so direction never relies on colour alone. **The arrow points the way the user must go, not the way they are off:** too fast → `▼ 8 s/km fast` (slow down), too slow → `▲ 8 s/km slow` (speed up). Same in speed units (`▼ 0.6 km/h fast`). Tolerance is a fixed constant in v1, no setting. |
| D8 | Activity modes | **Running mode only.** Cycling's layout is unchanged (it hides splits and shows max speed/elevation). |

Recommendations the owner did not object to, so treat as decided too:

- The verdict is judged on the **current split's average pace so far** (moving time, exactly
  what the Split pace tile already shows), never on instantaneous chip speed, which is far
  too noisy to colour a tile with.
- A **neutral grace period** at the start of every split: no tint until the split has at
  least 10 s of moving time. Otherwise every split opens red for its first few seconds.
- The **Last split** tile is tinted by its own final result against its own target (no
  grace), and each row in the expandable splits list shows its target and delta.
- The pace/speed preference (D4) also **seeds the live screen's speed/pace toggle** at
  Start, so a user who thinks in min/km no longer has to tap the toggle every run.

## 2. Findings that shape the design

Read these before touching the code — each one is a place where a naive change breaks
something that already works.

- **`SplitPreference` is a wire format, not just a preference.** `kind`/`value` are written
  to the GPX root as `sat:split_type`/`sat:split_value` and mirror the server's
  `Activity.split_type/split_value` columns and `AnalyzerV1`'s parameters exactly (whole
  km / mi / minutes, positive int). The web activity page lets the user re-slice at any
  size and re-analyses server-side. **Leave that contract alone** — the new plan is written
  as *additional* extensions (§4), and for a custom plan `split_type`/`split_value` still
  carry the plan's kind and the rolling base size, so the server's own analysis and the web
  page keep working unchanged.
- **`MetricsEngine` resolves the split size once, in its constructor**
  (`_splitDistanceMeters` / `_splitDurationTarget`, `metrics_engine.dart`). Both
  `_applySegmentDistanceMode` and `_applySegmentTimeMode` loop while a segment straddles
  boundaries (one GPS gap can cross several small splits) and each iteration currently
  reuses the single constant. With variable sizes, **each iteration must look up the size
  of the split it is about to complete** (`_completedSplits.length` is that split's
  0-based index) and then the *next* split's size for the loop condition. Get this wrong and
  a 30 s gap over a 90 s / 60 s plan credits the wrong boundary.
- **Everything the tiles show comes from `LiveMetrics`**, stamped by the engine per
  accepted fix and by a 1 s tick for the wall clock. The UI never sees the plan itself. The
  cleanest way to give tiles the split number/size/target is for the engine to put a small
  "current split" descriptor into `LiveMetrics` (§3.3) rather than teaching the widgets
  about `SplitPlan`.
- **`MetricSpec.valueOf` returns a single string** and `_MetricTile` renders value + label.
  A tint and a detail line need two new optional members on `MetricSpec` (§5.1); the grid
  and tile widgets change, the spec-list mechanism does not.
- **The live screen is a fixed, non-scrolling layout** sized off `constraints.maxHeight /
  100`. A detail line under the split tile's value makes that tile taller than its
  neighbours; use a smaller value font when a detail line is present (the Distance tile's
  two-line case already does exactly this: `unit * 4.5` instead of `unit * 7`), and check
  on the S10 that nothing overflows with the splits panel expanded.
- **Persisted preferences use `flutter_secure_storage` with a `_userHasSelected` guard**
  (`split_preference_controller.dart`, `activity_mode_controller.dart`). Any new persisted
  state must follow the same pattern, or a slow storage read completing after a fast user
  edit silently reverts the edit.
- **The number field commit pattern** (`_SplitValueField` in `settings_screen.dart`)
  commits on submit *and* on tap-outside, and reverts garbage to the last good value. The
  per-split editor rows must do the same — a plain `onChanged` that persists every keystroke
  would write half-typed values.
- **`Split` is what the splits list and Last split tile read.** Adding the target the split
  was run against to `Split` itself (§3.2) means those widgets need no plan lookup.
- **`SpeedUnit.initialFor(unit)` always picks the speed member**, and `_SpeedUnitNotifier.
  startRun` is fired once when a run reaches `LiveRunActive`. Seeding pace-first is a
  one-line change there, but the pace preference has to reach the screen through
  `LiveRunActive`/`LiveRunFinished` (which already carry `distanceUnit` for the same
  fixed-for-the-run reason).
- The server parser (`server/app/analysis/gpx_parser.py`) reads only the two known root
  extensions and ignores anything else; `server/tests/test_gpx_point_accuracy.py` is the
  precedent for "prove a new mobile extension is ignored".

## 3. Domain model (pure Dart — `mobile/lib/domain/`, unit-tested, no Flutter imports)

### 3.1 `SplitPlan` (new file `domain/tracking/split_plan.dart`)

```dart
/// One split of a custom plan. [size] is metres for a distance kind, seconds
/// for a time kind — always finer than SplitPreference's whole units.
class PlannedSplit {
  final double size;
  final double? targetSpeedMps;   // null = no target for this split
}

class SplitPlan {
  /// Kind + rolling size + time-split display unit — unchanged wire format.
  final SplitPreference base;
  /// Target applied to every rolling split (and to roll-on splits after a
  /// custom plan ends: none — see D5). Null = no target.
  final double? rollingTargetSpeedMps;
  /// Empty = rolling plan. Otherwise these are splits 1..N, in order.
  final List<PlannedSplit> customSplits;
  /// How targets are entered and shown, and the live toggle's initial state.
  final bool targetsAsPace;

  bool get isCustom => customSplits.isNotEmpty;

  /// Size of the 0-based [index]th split, in metres or seconds per base.kind:
  /// customSplits[index].size while inside the plan, else the base size.
  double sizeOf(int index);
  /// customSplits[index].targetSpeedMps inside the plan; rollingTargetSpeedMps
  /// for a rolling plan; null once a custom plan has been exhausted (D5).
  double? targetOf(int index);
  /// customSplits.length for a custom plan, null for rolling — the "/6" in "Split 3/6".
  int? get plannedCount;

  static const SplitPlan defaultPlan = SplitPlan(base: SplitPreference.defaultPreference, ...);
  Map<String, Object?> toJson(); factory SplitPlan.fromJson(Map<String, Object?>);  // §4.1
  String? get gpxPlanValue;   // §4.2, null for a rolling plan
  == / hashCode / copyWith
}
```

Targets are **always stored as speed in m/s** — pace and speed are one number, and
`core/units` already converts both ways. Validation lives in the model (`size > 0`,
`targetSpeedMps > 0`, `customSplits.length <= 50`); the editor just calls it.

### 3.2 `Split` gains `targetSpeedMps`

`domain/models/split.dart`: add `final double? targetSpeedMps` (the target the engine was
holding for that split when it completed). The list rows and Last split tile read it
directly.

### 3.3 `LiveMetrics` gains a current-split descriptor

```dart
class CurrentSplitInfo {
  final int index;            // 1-based, == completedSplits.length + 1
  final int? plannedCount;    // SplitPlan.plannedCount
  final double sizeMeters;    // or
  final double sizeSeconds;   // exactly one of these is non-zero per kind — or model as
                              // a small sealed type; implementer's call, keep it obvious
  final double? targetSpeedMps;
}
```

`LiveMetrics.currentSplit` (non-null once a run has started; `LiveMetrics.zero` carries the
default plan's first split). Stamped by the engine in `_buildMetrics()`.

### 3.4 `MetricsEngine` takes a `SplitPlan`

- Constructor: `MetricsEngine({ActivityMode mode, SplitPlan splitPlan = SplitPlan.defaultPlan})`.
  Keep the existing `splitPreference:` named parameter as a convenience that wraps into a
  rolling plan, so the existing tests and call sites keep compiling.
- Replace `_splitDistanceMeters`/`_splitDurationTarget` with per-index lookups:
  `_boundaryFor(int splitIndex)` returning metres or a `Duration` from `plan.sizeOf`.
- In both `_applySegment*Mode` loops: the size used for `distanceIntoSplit`/
  `durationIntoSplit` and for the `Split` record is the size of split
  `_completedSplits.length`; after appending, the loop condition re-evaluates against the
  new `_completedSplits.length`. The `Split` record gets `targetSpeedMps: plan.targetOf(index)`.
- Roll-on (D5): `sizeOf` past the plan returns the base size and `targetOf` returns null —
  no engine special-casing beyond that.

### 3.5 Verdict (new file `domain/tracking/split_target.dart`)

```dart
enum SplitVerdict { onTarget, tooFast, tooSlow }
const double splitTargetTolerance = 0.05;
const Duration splitVerdictGrace = Duration(seconds: 10);

/// Null when there is no target, no speed yet, or [elapsedInSplit] < grace.
SplitVerdict? splitVerdict({required double? avgSpeedMps, required double? targetSpeedMps,
                            required Duration elapsedInSplit});
```

`avg / target` within `[1 - tol, 1 + tol]` → onTarget; above → tooFast; below → tooSlow.
The Last split tile calls it with `elapsedInSplit: split.duration` (which is always ≥ grace
in practice; if a split is shorter than the grace it simply shows neutral, which is fine).

### 3.6 Units (`core/units/units.dart`)

- `String formatSpeedDelta(double avgMps, double targetMps, SpeedUnit unit)` →
  `"▼ 8 s/km fast"` / `"▲ 0.6 km/h slow"` / `"on target"`. The arrow is the correction
  the user must make (D7): ▼ when too fast, ▲ when too slow, regardless of whether the
  unit is pace or speed. For pace units the delta is in whole seconds per km/mi (pace
  difference, so "fast" means *lower* pace); for speed units it is in km/h or mph to one
  decimal. Test both arrows in all four `SpeedUnit`s — it is easy to get the pace case
  backwards, since a faster runner has a *lower* number.
- `String formatSplitSize(sizeMeters/Seconds, kind, DistanceUnit)` → `"1 km"`, `"400 m"`,
  `"0.25 mi"`, `"1:30"` (m:ss for time). Metres for sub-km distances under the km kind;
  decimal miles under the mi kind.
- Parsing helpers for the editor live in `core/units` too (`parsePace("5:00") → sec`,
  `parseMinSec("1:30") → Duration`), tested.

## 4. Persistence and GPX

### 4.1 `SplitPlanController` replaces `SplitPreferenceController`

`core/tracking/split_plan_controller.dart`, `NotifierProvider<SplitPlanController, SplitPlan>`.
One secure-storage key `split_plan` holding `jsonEncode(plan.toJson())`. On load, if that
key is absent, read the three legacy keys (`split_kind`, `split_value`,
`split_time_display_unit`) into a rolling plan so nobody's existing preference is lost,
then write the new key. Same `_userHasSelected` guard. Rename the provider everywhere
(`live_run_controller.dart`, `live_run_screen.dart`, `settings_screen.dart`) — the old
`splitPreferenceControllerProvider` goes away; `SplitPreference` the *type* stays.

### 4.2 GPX root extensions (`core/files/run_gpx_log.dart`)

`RunGpxLog` takes the `SplitPlan`; `split_type`/`split_value` are written from `plan.base`
exactly as today. Added, all under the existing `sat:` namespace:

| Element | When written | Value |
|---------|-------------|-------|
| `sat:split_target` | rolling plan with a target | target speed in m/s, e.g. `2.222` |
| `sat:split_plan` | custom plan | one entry per planned split, `size@target` joined by `;`, target omitted when null: `90@2.222;60@1.389;120` — sizes in metres or seconds per `split_type`, speeds in m/s. Plain text, no JSON, so a future Python parser is a `split(';')`. |
| `sat:split_targets_as` | always | `pace` or `speed` — display hint only |

Server: add `server/tests/test_gpx_split_targets.py` asserting a GPX carrying all three
parses to the same `split_type/split_value` and points as one without them. No server code
change. The server-side follow-up is already raised as
[#100](https://github.com/sjefferson99/simple-activity-tracker/issues/100) — if the
extension names or the `size@target;…` format change during implementation, update #100
to match, since that issue's table is copied from here.

## 5. UI

### 5.1 `MetricSpec` (`features/live_run/metric_spec.dart`)

Add two optional members, both defaulting to "none" so every other tile is untouched:

```dart
final String? Function(LiveMetrics metrics, SpeedUnit unit)? detail;   // second line
final SplitVerdict? Function(LiveMetrics metrics)? verdict;             // tint
```

- `_currentSplitSpec`: `detail` → `"Split 3/6 · 1 km @ 5:00 /km"` then, on the next line
  when a verdict exists, the `formatSpeedDelta` text; `"Split 3 · 1 km"` with no target.
  `verdict` → `splitVerdict(avg-so-far, currentSplit.targetSpeedMps, currentSplitElapsed)`.
  Description updated to mention the target and the colours.
- `_lastSplitSpec`: `detail` → `formatSpeedDelta` against `split.targetSpeedMps` when set;
  `verdict` → its own result.
- `_MetricTile` draws a rounded background when `verdict` is non-null: green for onTarget
  (a fixed `Colors.green` shade with alpha over the surface — theme has no "success"
  colour), `colorScheme.errorContainer`-style red for either off-target case. Value font
  drops to the two-line size when a detail line is present. The detail line uses the label
  font size.
- `_MetricGrid` passes the extra strings through; no layout change.

### 5.2 Splits list (`_SplitRow`)

Add the target after the pace column when `split.targetSpeedMps` is set (`"@ 5:00"`), and
tint the pace text (not the row) green/red by that split's verdict.

### 5.3 Speed/pace toggle seeding

`LiveRunActive`/`LiveRunFinished` gain `bool prefersPace` (fixed at Start like
`distanceUnit`); `_SpeedUnitNotifier.startRun(unit, prefersPace)` picks the pace member
when true. Cycling still forces speed (existing logic).

### 5.4 Home screen row (`live_run_screen.dart`)

Under the Run/Cycle toggle, only while `canSwitchActivityMode` (idle), a tappable row
summarising the plan and opening the Splits screen:

- rolling, no target: `Splits: every 1 km ›`
- rolling with target: `Splits: every 1 km @ 5:00 /km ›`
- custom: `Splits: custom, 6 splits ›`

Hidden in cycling mode (D8) — the row would promise something the cycling layout doesn't
show. Keep it one line, same muted style as the status line.

### 5.5 Splits screen (new `features/splits/splits_screen.dart`)

A scrollable `ListView` (this screen may legitimately be long), sections top to bottom:

1. **Split type** — the existing Km / Miles / Minutes segmented control, moved from
   Settings. Changing it converts nothing: custom sizes/targets are cleared with a
   confirmation ("Changing the split type clears the custom splits") because a 400 m plan
   is meaningless in minutes.
2. **Display units** (time kind only) — the existing km/mi control, moved.
3. **Targets as** — Pace / Speed segmented (`targetsAsPace`). Labels read `min/km` /
   `km/h` or `min/mi` / `mph` per the effective distance unit. Re-renders every target
   field in the new unit; values are stored as m/s so nothing is lost.
4. **Plan** — Rolling / Custom segmented.
5. **Rolling** (when selected): `Every [1] km` (existing field) and
   `Target [5:00] /km` with a Clear (×) to remove the target. Hint line: `= 5:00 per split`
   (distance) or `= 1.25 km per split` (time).
6. **Custom** (when selected):
   - `Number of splits [6]` — growing appends rows prefilled with the base size and the
     last row's target; shrinking truncates from the end.
   - One row per split: `#3  [0.4] km  @ [4:30] /km   = 1:48   🗑`. Size is decimal km/mi
     for distance kinds and `m:ss` for time; both commit on submit/blur via the
     `_SplitValueField` pattern. Delete icon per row; `Add split` button at the bottom.
   - `Apply target to all` next to the first row's target — a common workout has one
     target.
7. Settings keeps a `ListTile("Splits", subtitle: summary, trailing chevron)` that pushes
   the same screen, and loses `_SplitPreferenceSection` entirely.

Persistence is immediate on every committed field (as today) — no Save button.

## 6. Work items, in order (one branch `mobile-99-split-targets`, one PR, one commit per step — ask before each commit)

1. **Domain**: `SplitPlan`, `PlannedSplit`, `Split.targetSpeedMps`, `CurrentSplitInfo` on
   `LiveMetrics`, `MetricsEngine` on variable sizes, `splitVerdict`, units helpers. Tests:
   - engine: distance-kind custom plan (400 m, 1000 m, 200 m) with a constant-speed track
     → three splits of exactly those sizes, then roll-on at base size; time-kind plan
     (90 s, 60 s) with one long gap segment spanning both boundaries → both crossings
     interpolated at the right sizes; `Split.targetSpeedMps` stamped; `currentSplit`
     index/size/target/plannedCount correct before, inside and after the plan.
   - verdict: boundaries at exactly ±5 %, grace, null inputs.
   - units: delta formatting both directions in all four `SpeedUnit`s; size formatting;
     pace/`m:ss` parsing round trips.
   - `SplitPlan` JSON round trip, `gpxPlanValue` encoding, validation.
2. **Persistence + GPX**: `SplitPlanController` with legacy-key migration (test it: seed
   the three old keys, assert the loaded plan and that `split_plan` is now written);
   `RunGpxLog` extensions (test presence for custom/rolling-with-target, absence for plain
   rolling); the server ignore-test. `LiveRunController.start()` reads the plan.
3. **Live screen**: `MetricSpec.detail`/`verdict`, `_MetricTile` tint, splits list, toggle
   seeding, home-screen row. `metric_spec_test` covers detail/verdict text for
   with-target, no-target, and after-plan cases.
4. **Splits screen** + Settings link; remove the old Settings section.
5. **Docs**: `docs/how-it-works.html` gains a short "Split targets" paragraph (what is
   judged, the 5 % band, the 10 s grace); regenerate the PDF per CLAUDE.md. CLAUDE.md
   status entry. This file's status line.

Steps 1–2 are testable without a device; run `flutter analyze` and `flutter test` after
each. Snyk code scan on `mobile/` (and `server/tests` for the one new file) before the PR.

## 7. Verification on device (before asking for sign-off)

On the S10 (real GPS) — the emulator is fine for iterating on layout, but the verdict
colouring depends on real pace noise:

1. Rolling plan, 1 km @ a target ~10 % slower than your walking pace: tile opens neutral,
   goes green within ~15 s, then red with `▼ … fast` (arrow down = slow down) once your
   pace settles above target. Slow to a dawdle: red with `▲ … slow`. Toggle to km/h: same
   verdict and arrow, delta now in km/h.
2. Custom time plan: `1:30 @ 4.0 km/h`, `1:00 @ 6.0 km/h`, `1:30 @ 4.0 km/h`, then walk for
   5 minutes. Expect: three tinted splits in the list with targets and deltas, "Split 4"
   untargeted and untinted, tile reads `Split 4 · 1 min` (base size) after the plan.
3. Pause mid-split, resume: verdict continues from the split's moving-time average, no
   flash to red on resume.
4. Kill and relaunch the app: the Splits screen shows the same plan (persistence), and
   an install *over* a build that only had the old three keys shows the old rolling
   preference (migration).
5. Open the finished run's GPX (`Downloads/SimpleActivityTracker/`): root `<extensions>`
   carries `sat:split_plan` / `sat:split_target` / `sat:split_targets_as` alongside the
   unchanged `split_type`/`split_value`.
6. Upload to the dev server (`deploy/standalone-tls`): activity analyses and renders as
   before; the web splits table still re-slices at any size. No server tracebacks.
7. Screenshot the live screen with the splits panel expanded on the S10 and confirm nothing
   overflows (`adb exec-out screencap -p`).

## 8. Explicitly out of scope

- Server-side use of the plan/targets (web page showing target vs actual, variable-length
  server splits) — [#100](https://github.com/sjefferson99/simple-activity-tracker/issues/100).
- Cycling mode (D8).
- Repeating a custom plan (D5), audio/vibration cues, a configurable tolerance, targets in
  the run-finished summary beyond what the tiles/list already show.
- Rolling splits finer than whole km/mi/min (would change the server wire format).
- Targets in the persisted `RunSummary` / `RunSummarySplit` sidecar. Tempting for a future
  on-phone history screen, but the server's `SplitSummary` schema is `extra="forbid"`
  (`server/app/api/v1/schemas.py`), so an extra field on a split makes every upload 422
  until the server schema gains it. Do it together with the server follow-up, not here.
- An on-phone activity history / reopening a finished run's summary. The phone currently
  keeps only a `RunRecord` sidecar (headline numbers + per-split duration/speed/distance)
  and the GPX; the `LiveRunFinished` screen state is not persisted at all. The owner's
  direction is to fetch this from the server API rather than store it on the phone —
  [#101](https://github.com/sjefferson99/simple-activity-tracker/issues/101).
