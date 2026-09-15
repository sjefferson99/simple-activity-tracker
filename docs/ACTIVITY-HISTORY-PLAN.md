# Activity history & server analysis plan — issues #97 and #101

Status: **draft, awaiting owner sign-off — nothing implemented yet.**

Handoff plan for whoever implements this — read CLAUDE.md first (architecture rules, the
commit-approval rule, the on-device verification habit), then this file end to end.

Scope, from the two linked issues:

- [#97](https://github.com/sjefferson99/simple-activity-tracker/issues/97) — "App should
  show the summary analysis from the server if online." No body text; folded into #101
  per that issue's own suggestion, and treated below as **Slice 1**.
- [#101](https://github.com/sjefferson99/simple-activity-tracker/issues/101) — "App: show
  server analysis, split targets and activity history by calling the server API." States
  three rough pieces (post-Stop summary showing server analysis = #97; an activity list;
  an activity detail screen with splits/targets), explicitly **not** detailed yet, and
  explicitly prefers a server-backed read model over persisting analysis on the phone.

This plan turns those three pieces into three delivery slices on **one branch**, per the
"stacked PRs" lesson in CLAUDE.md — this feature is exactly the tightly-coupled case that
doc warns against splitting into dependent PRs. **Build order is detail screen → list
screen → summary-screen link**, not the issue-text order, because the summary screen's
link (§3, Slice C) points *at* the detail screen, and the detail screen's splits/targets
widget is what Slice C reuses rather than duplicates — see the owner's design in §2's D5.
One branch, one PR, checkpointed commits, owner sign-off at each checkpoint before moving
to the next slice — not three separate GitHub PRs.

## 1. Current state (verified by research, 2026-09-16 — re-check before relying on this if picked up later)

- **Mobile has no activity-list or activity-detail screen at all.** The whole app is one
  `LiveRunScreen` (`mobile/lib/features/live_run/live_run_screen.dart`) pushed screens
  from (Settings, Splits) via `Navigator.push` — no bottom nav, no drawer, no route table.
- **`ApiClient`** (`mobile/lib/core/api/api_client.dart`) has `login`, `logout`, `me`,
  `uploadRun`, `getAnalysis` only. No list-activities, get-activity, or get-track method
  exists yet — all new for this plan.
- **`RunDto`** (`mobile/lib/core/api/dto/run_dto.dart`) doesn't carry `split_plan`, `tags`,
  `device_name`, `created_at`/`updated_at` — the server's `ActivityOut` already has all of
  these (per #75/#76/#99/#100), the mobile DTO just hasn't caught up.
- **The server API already has everything Slice 1 and the detail screen (Slice 3) need**:
  - `GET /api/v1/activities/{id}/analysis` → `AnalysisOut{status, result}` where `result`
    (from `AnalyzerV1`, `ANALYSIS_VERSION = 7`) already contains per-split
    `target_speed_mps`/`verdict` (`"on_target"|"too_fast"|"too_slow"|null`, ±5% tolerance —
    same rule as the phone's live tint) whenever the uploaded GPX carried split-plan
    extensions (#99/#100). Nothing server-side needs to change for Slices 1 or 3.
  - `GET /api/v1/activities` → `ActivityListResponse{activities: [ActivityListItem], next_cursor}`
    exists and is paginated (cursor-based, `started_at DESC, id DESC`), but is **plainer**
    than the web app's list: no sort direction choice, no text/distance/geo filters (those
    live only in `list_for_user_page`, used by the web `/activities` route, not this API
    route). `ActivityListItem` has `id, activity_type, started_at, ended_at, title,
    distance_meters, moving_seconds, tags` — enough for a first mobile list, not enough to
    match the web app's search/filter UI.
  - `GET /api/v1/activities/{id}` → full `ActivityOut` (adds `notes`, `device_name`,
    `client_summary`, `source_platform/version`, `tags`, `split_plan: SplitPlanOut|null`,
    `analysis`).
  - `GET /api/v1/activities/{id}/track` → `TrackOut{segments: [[{lat,lon,ele,t}]]}` for a
    map, if wanted later.
- **`SyncService`** already fetches analysis once, fire-and-forget, right after a
  successful upload (`_fetchAnalysis` in `sync_service.dart`), and persists it via
  `RunStore.updateAnalysisResult`. **If analysis is still `pending` at that single attempt,
  nothing retries it** — today's gap that Slice 1 must close, since a slow server would
  otherwise leave the summary screen stuck showing nothing past that point.
- **`RunSyncSection`/`_Insights`** (`mobile/lib/features/live_run/run_insights.dart`)
  already renders elevation gain/loss, best efforts, and server distance/moving-time from
  the cached `analysisResult` — but **never renders `result['splits']`, i.e. no split
  targets/verdicts on the summary screen today**, despite the data already being fetched
  and cached. This is the concrete, narrow gap #97 is actually asking to close.
- **Web app's splits table** (`server/app/templates/partials/splits_table.html`) is the
  reference UI to mirror: a Target column shown only when `has_targets` (any split has a
  non-null target), pace/speed cells coloured by `verdict`, values formatted as pace or
  speed per `result['split_targets_as']`. Mobile already has this exact colour/format logic
  live, in `domain/tracking/split_target.dart` (`splitVerdict`,
  `splitTargetTolerance = 0.05`) — reuse it rather than re-deriving verdicts from
  `target_speed_mps` a second way; the server already computed and returned `verdict`
  directly, so the mobile UI layer only needs to map that string to a colour, not
  recompute anything.
- Full research detail (every DTO/schema field, Riverpod patterns, nav structure) is
  preserved in the PR/commit history of this plan's implementation — see the exploration
  notes folded into §2 below rather than duplicated twice.

## 2. Decisions needed before implementation (raise with the owner, do not guess)

| # | Question | Recommendation | Why it needs a decision |
|---|----------|-----------------|--------------------------|
| D1 | Where does the activity list live in the nav? | An icon button (e.g. a list/history icon) in the idle home screen's app bar, pushing a new `ActivityListScreen` — matches the existing "push from idle screen" pattern (Settings, Splits) rather than introducing a bottom-nav shell. | No nav shell exists today; this is a real structural choice, not a detail. |
| D2 | List API: use the plain cursor-paginated `/api/v1/activities`, or add sort/filter parity with the web app now? | **Start with the plain endpoint** (date-sorted, no filters) for the first mobile slice; treat web-parity search/filter as a later follow-up issue, not part of #101's "roughly" scope. | #101's own text only asks for "same paging/sort as the web list from #75" as a rough goal, not filters/search (that's #76, web-only so far). Keeps Slice 2 small. |
| D3 | Offline / signed-out behaviour for the new list/detail screens | Per #101's own stated constraint: show a clear "sign in to see your activity history" state (reusing the pattern `RunSyncSection` already uses for "Sign in to upload"), no local cache fallback in v1. | #101 explicitly flags this as an open question, and explicitly says a read-through cache is "not a requirement for the first slice." |
| D4 | Does a locally-recorded-but-unsynced run show up in the new activity list? | **No** — the list is purely server-backed (per #101's direction); a pending/failed local run keeps showing only via the existing `RunSyncSection`/summary-screen flow, never duplicated into the new server list until it's actually uploaded. | Avoids merging two different data models (local `RunRecord` vs. server `ActivityListItem`) in one screen for v1. |
| D5 | Analysis-still-pending retry on the summary screen | Add a bounded retry (e.g. a few attempts with backoff) so the fetch keeps trying briefly after upload, **and** the summary screen shows a simple link/state rather than inline splits — see the owner's design in §3a below: "Analysis not available yet" until done, then "View full summary" linking to Slice 3's detail screen for the now-uploaded activity. | Directly blocks #97 — without the retry, a slow server analysis leaves the screen stuck on "not available" past the single fire-and-forget attempt; without the link design, the finished screen would have to duplicate the whole splits/targets UI instead of reusing Slice 3's. |
| D6 | `RunDto` schema catch-up | Extend `RunDto` to carry `split_plan` (mirroring server's `SplitPlanOut`) and any other `ActivityOut` fields the detail screen needs; leave fields the app has no UI for yet (`created_at`/`updated_at`) un-mapped rather than adding dead fields. | Needed for Slice 3's detail screen to show targets; keep it minimal, not a 1:1 schema mirror. |
| D7 | Map/track view on the detail screen | **Deferred to a follow-up issue**, not part of this plan. | Owner confirmed 2026-09-16: no technical blocker (server already serves `/track`; would need a new Flutter map dependency e.g. `flutter_map` plus tile/attribution/Snyk-license review), just kept out to keep this pass's scope small. Filed as [#107](https://github.com/sjefferson99/simple-activity-tracker/issues/107). |

**Confirmed out of scope, raised and settled with the owner 2026-09-16:**

- **The `LiveRunFinished` screen/state is discarded once the user leaves it** (`LiveRunController.reset()`/`goHome()` sets `state = const LiveRunIdle()`) — the rich "just finished" summary view cannot be reopened today, though the underlying `RunRecord` (GPX + sync status) does survive on disk and is still visible/manageable in Settings → Activities (see below). Fixing "the finished-screen UI itself can't be revisited" is a separate local-persistence/re-entry problem, not the server-API-loading problem #97/#101 describe — **not in scope for this plan.** Filed as a follow-up: [#106](https://github.com/sjefferson99/simple-activity-tracker/issues/106).
- **Settings' `_SyncQueueSection` (the local pending/failed/uploaded activity list, `settings_screen.dart`) is untouched by this plan.** It manages local-only concerns (retry, clear failed, delete-locally-only) for runs recorded on *this* device. Slice 2's new activity list is a different, server-backed screen (every activity that exists on the server, from any device) — separate data source, separate purpose, no merge between the two.

## 3. Slices (checkpointed commits, one branch, one PR — built in this order)

### Slice A — Activity detail screen (server analysis + split targets, full activity)

Built first because Slice C's link points here, and Slice C reuses this slice's
splits/targets widget rather than duplicating it.

- Extend `RunDto`/`AnalysisDto` per D6; new `ApiClient.getActivity({baseUrl, token, id})`
  (or reuse `getAnalysis` + a new plain-detail call, whichever avoids two round trips
  where one suffices).
- New `features/activity_history/activity_detail_screen.dart`, plus a standalone
  `SplitsTargetsView`-style widget (shared with Slice C): per-split distance/duration/avg
  speed, and — only when any split has a non-null `target_speed_mps` (mirroring the web's
  `has_targets` gate) — a Target column/line with `splitVerdict`-driven colour, reusing
  `domain/tracking/split_target.dart` for the colour/delta-arrow logic already proven
  live. Respect `result['split_targets_as']` for pace-vs-speed formatting (existing
  `core/units` helpers). Also shows headline stats and tags. Map/track view explicitly
  deferred per D7 — see §4.
- Tests: widget tests for the shared splits/targets widget (with/without targets, each
  verdict, pending/done/failed analysis states), detail-screen tests (tags rendering,
  missing-analysis state).
- **Verify on-device**: open a real activity's detail (navigated to directly / via a
  temporary debug entry point until Slice B's list exists), confirm it matches the web
  page's splits table for the same activity.

### Slice B — Activity list screen

- New `core/api/dto` fields/DTO for `ActivityListItem`/`ActivityListResponse`; new
  `ApiClient.listActivities({baseUrl, token, cursor, limit})` method.
- New `features/activity_history/activity_list_screen.dart` (name tentative) + a Riverpod
  provider following the `AuthStateController`-style async pattern (§2's D3/D4 govern
  signed-out/offline and local-vs-server-run behaviour, not this section). Cursor-based
  "load more"/infinite scroll, matching the API's own pagination style (a page-number UI
  like the web app's isn't available from this endpoint per D2).
- Nav entry point per D1. Tapping a row opens Slice A's detail screen.
- Tests: DTO/API-client tests (mocked `MockClient`, matching existing
  `http_api_client_test.dart` conventions), provider tests, widget tests for
  empty/loading/error/signed-out states.
- **Verify on-device**: real list against the dev server account, scroll-load-more,
  signed-out state, tap-through to Slice A's detail screen.

### Slice C — #97: link to server analysis from the post-Stop summary screen

Per the owner's design (2026-09-16): **not** an inline splits section — a lightweight
link/state row in `run_insights.dart`'s `_Insights` widget:

- While analysis is `pending` (or not yet fetched): show **"Analysis not available yet"**
  (plain text, no action).
- Once analysis is `done`: show a **"View full summary"** link/button that navigates to
  Slice A's activity detail screen for this now-uploaded activity (`serverRunId` from the
  `RunDto` returned by upload). No new rendering logic here — purely a link plus a
  pending/failed/done state check.
- If analysis comes back `failed`, show that plainly too (not silently indistinguishable
  from "not available yet").
- Close the D5 gap: bounded retry (a few attempts with backoff) for a `pending` analysis
  fetched right after upload, so the link has a real chance to become available without
  the user needing to background/reopen the app.
- Tests: widget tests for the three states (not-available/link-available/failed), a
  `SyncService` test for the retry/backoff behaviour.
- **Verify on-device** (per CLAUDE.md's habit): a real upload should show "Analysis not
  available yet", then flip to a working "View full summary" link once the server
  finishes analysing, landing on Slice A's detail screen for that activity.

## 4. Explicitly out of scope (per #101's own text, plus owner decisions 2026-09-16)

- Persisting the server's activity list/analysis on the phone (no local cache/database of
  server activities — v1 always calls through).
- Search/filter parity with the web app's #76 work (text/distance/geo) — a candidate
  follow-up issue if wanted later, not part of this plan.
- Map/track rendering on mobile detail screen (server already exposes `/track`; deferred
  per D7 — no technical blocker, kept out to bound this pass's scope. Filed as
  [#107](https://github.com/sjefferson99/simple-activity-tracker/issues/107)).
- Reopening a locally-recorded run's finished-screen summary after leaving it — separate
  local-persistence problem, filed as [#106](https://github.com/sjefferson99/simple-activity-tracker/issues/106).
- Settings' local pending/failed/uploaded activity list (`_SyncQueueSection`) — untouched;
  different data source and purpose than the new server-backed list (§2).
- Any server-side change — #100 already shipped everything the server side of this plan
  needs; this is a mobile-only plan.

## 5. Test/verify checklist (mirrors CLAUDE.md's server/mobile workflow habits)

- `flutter analyze` and `flutter test` clean after each slice, not just at the end.
- Snyk clean on `mobile/` after each slice (per the global always-on Snyk rule).
- Real on-device verification per slice before moving to the next (per CLAUDE.md's
  "verify device-visible changes" habit) — a physical phone against the real dev-stack
  server, not just widget tests.
- Follow the commit-approval rule: this plan produces implementation work across three
  slices, but commit/push/PR/merge are each still their own explicit ask — this plan being
  approved is not itself a commit approval.
