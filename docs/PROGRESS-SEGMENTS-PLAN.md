# Progress & segments plan: issues #190 and #102

Status: **all §2 decisions confirmed by the owner** (2026-11-13). PR 1 built on branch `server-190-progress`, awaiting owner sign-off.

Scope, from [issue #190](https://github.com/sjefferson99/simple-activity-tracker/issues/190)
(show performance across all activities):

1. Show how the current activity stacks up against history: PR for 5k, PR for a segment.
2. Performance improvement over time.
3. Period summaries: activities done, distance covered, trends in distance and speed per ride.
4. Later: heart rate etc. once sensors exist (design for it, don't build it).

And from [issue #102](https://github.com/sjefferson99/simple-activity-tracker/issues/102)
(segment analysis), which #190's "PR for this segment" depends on:

5. Recalculate stats for a section of the graph the user selects.
6. Save that section as a segment and apply it to other rides.
7. Auto-generate segments per ride, stored in the database, reusing an existing one where it
   fits and creating a new one where needed.
8. User-created segments, shareable with other users (like activities), for cases auto ones
   don't cover.

Every server PR below follows CLAUDE.md's "Server dev/test workflow" (branch per PR, tests,
real-container verification, owner sign-off, then push).

---

## 1. Findings that shape the design

Checked against the code and the dev stack's real database, not assumed.

- **Best efforts already exist, but only inside the JSON.** `_best_efforts()` in
  `app/analysis/v1.py` computes the fastest 1/5/10 km window per activity, stored in
  `ActivityAnalysis.result["best_efforts"]`. Ranking across activities ("is this a PR?")
  needs them in a queryable table, following the existing pattern for `distance_meters` and
  `start_lat`, which are denormalised columns kept in sync wherever `result` is set
  (upload/import, `reanalyze`, live convert).
- **Period totals are cheap.** One user's whole history is a few hundred rows (the dev stack
  has 291: 262 cycling, 27 running, 2 walking, 254 of them Strava imports going back to
  2024-09). Summing them in Python per request is milliseconds. Only `elevation gain` and
  `elapsed_seconds` are missing as columns; both backfill from the JSON with `json_extract`
  in the migration, the same way #76 backfilled start/end.
- **The server has no user timezone.** Every date is rendered in the browser
  (`<time class="local-time">`). Week/month/year buckets are timezone-dependent, so the page
  must pass the browser's IANA zone (`Intl.DateTimeFormat().resolvedOptions().timeZone`) and
  bucket with `zoneinfo`. **To verify:** the `python:3.12-slim` image has tzdata (if not, add
  the `tzdata` package, which needs the owner's OK under WEB-PLAN §13).
- **The routes are very repetitive.** Grouping by start/end rounded to ~1 km finds the same
  ~8.5 km commute variants 51, 45, 29, 23 and 17 times. Auto-detected segments will find
  plenty to match, and this data is the replay set for tuning the matcher (§4.3).
- **uPlot supports drag-to-select natively** (`cursor.drag.x` plus the `setSelect` hook),
  and the detail page already maps a chart distance to a map position
  (`latLngAtDistance`). Range selection needs no new dependency. Leaflet is already vendored
  for highlighting the range on the map.
- **Web routes are excluded from the OpenAPI schema** (`include_in_schema=False` on every
  web router). A web-only delivery doesn't touch `openapi.json`, so no `API_LEVEL` bump.
- **The app reads `best_efforts` by looking up 1000 m and 5000 m**
  (`activity_detail_screen.dart`), and `contract/analysis-result/app-reads.json` only
  requires `distance_meters`/`duration_seconds` per entry. Adding more distances is
  additive; 1000 and 5000 must stay.
- **Track density:** the average stored activity has ~2,600 points, the largest 17,207. The
  `track` cache is capped at 2,000 points, so long rides are thinned to ~40 m spacing there.
  Segment matching should therefore read the full GPX, not the cache, and run in the
  background (see D11).

## 2. Decisions (recommendation in each; owner to confirm)

| # | Question | Recommendation |
|---|---|---|
| D1 | Whose activities feed stats and PRs? | **Your own only.** Shared activities never count toward your records or totals. |
| D2 | Period boundaries | Browser timezone, weeks start **Monday**, and "this week/month/year so far" compared with the same span of the previous one (e.g. 1–13 Nov vs 1–13 Oct). |
| D3 | Best-effort distances | Per activity type. **Running/walking:** 400 m, 1 km, 1 mi, 5 km, 10 km, half, marathon. **Cycling:** 1 km, 5 km, 10 km, 20 km, 40 km, 50 km, 100 km. Analyzer bump to v14 (stored history re-analysed on startup, so the PR gets the `upgrade-note` label). |
| D4 | What "PR" means on an activity page | **As of that activity's date**, Strava-style: "PR", "2nd best", "3rd best" among your same-type efforts up to then. A later, faster ride doesn't take the badge off an old one. The Progress page shows current all-time records separately. |
| D5 | "Fastest ride" record | Average moving speed, only for activities over a minimum distance (cycling **5 km**, running 3 km) so a 400 m test ride doesn't hold the record. Plus longest distance, longest moving time and biggest climb. Cycling was planned at 10 km, lowered in PR 1 because the typical ride in the dev data is an ~8.5 km commute. |
| D6 | Stats for a chart selection (#102 part 5) | Computed **in the browser** from the chart's own series. Instant, no request per drag; resolution is the chart's (≤300 samples), which is what the user selected on anyway. Saving it as a segment cuts the exact geometry from the full GPX on the server. |
| D7 | Segment effort time | **Elapsed clock** (pauses excluded, standing still included) between the interpolated start and finish crossings, the same clock as splits (#161). Speed = segment's own length ÷ that time, so efforts on one segment compare fairly. |
| D8 | Auto-segments: what they are | **Per user, never shared across users** (a global pool would leak where other people ride). Two kinds: **climbs** (sustained uphill) and **repeated stretches** (a path you've ridden ≥3 times for ≥1 km). An existing segment is reused when a new ride matches it; a new one is created only when nothing covers it. You can rename, hide or delete them; a hidden one stays hidden and isn't recreated. |
| D9 | Sharing segments (#102 part 8) | Share a **user-created** segment with chosen users, like activity shares. A viewer then gets it matched against their own activities. Its leaderboard shows the viewer's own efforts plus efforts on activities the viewer can already see (existing history grants); it never reveals anything a viewer can't already open. |
| D10 | Phone app | **Web only** in this work. The mobile Progress/segments views are tracked on [#101](https://github.com/sjefferson99/simple-activity-tracker/issues/101) (that's when the API endpoints and the API-level bump happen). |
| D11 | When matching runs | In the background (like Strava imports): after each upload/import, and across all your activities when a segment is created. Versioned by `SEGMENT_MATCH_VERSION`, re-run on startup when it bumps, the same pattern as `ANALYSIS_VERSION`. |
| D12 | Activity types | A segment belongs to one activity type; rides only rank against rides. |
| D14 | Virtual rides (added during PR 1) | Strava imports "Virtual Ride" as plain cycling, so Zwift/ROUVY rides held most cycling records (1 km at 65 km/h). A per-activity **Virtual / indoor** flag: set by the Strava import for Virtual Ride/Run, editable on the activity page, carried in backup export/import. Virtual activities count in totals but never in records, PR ranks or trends. Confirmed by the owner 2026-11-13. |
| D13 | Heart rate etc. later | Stats are computed by a small metric registry (key, label, unit, how to sum or average). Adding heart rate later means adding entries plus a new GPX field, with no redesign. |

## 3. Data model (all additive; one Alembic migration per PR that needs it)

```
activity_analyses  + elevation_gain_m float null, elapsed_seconds float null   (backfilled)
                   + min_lat/max_lat/min_lon/max_lon float null                 (backfilled; bbox prefilter)

activity_best_efforts   activity_id FK, user_id, activity_type, started_at,
                        distance_m, duration_s          PK(activity_id, distance_m)
                        ix(user_id, activity_type, distance_m, duration_s)

segments                id, owner_id, name, activity_type, kind (user|auto_climb|auto_stretch),
                        geometry JSON [[lat,lon,ele|null],…] (simplified, ≤1000 pts),
                        length_m, elevation_gain_m, avg_grade,
                        start/end lat/lon, bbox (4 cols), hidden bool,
                        created_from_activity_id null, created_at, updated_at

segment_efforts         id, segment_id FK, activity_id FK, user_id, started_at,
                        start_dist_m, end_dist_m,       (positions on the activity, for highlighting)
                        elapsed_s, avg_speed_mps, match_version
                        ix(segment_id, elapsed_s), ix(activity_id)

segment_shares          segment_id FK, viewer_id FK     PK(segment_id, viewer_id)
```

All derived rows (`activity_best_efforts`, `segment_efforts`) are written by one helper
called everywhere `result` is set, and deleted explicitly before their activity (no ORM
cascades here; see the FK-delete gotcha in CLAUDE.md). Activity delete, bulk delete and
live-recovered replacement all need covering by tests.

## 4. Algorithms

### 4.1 Records and ranks
SQL over `activity_best_efforts` with D4's "up to this date" filter:
`count(*) where user, type, distance, started_at <= this.started_at, duration_s < this.duration_s`
gives the rank (+1). Ties go to the earlier activity.

### 4.2 Segment matching (one segment against one activity)
1. Prefilter: bboxes intersect and activity type matches (SQL).
2. Start candidates: runs of fixes within 30 m of the segment start; take each run's closest
   approach, projected onto the track (interpolated, like split boundaries).
3. Finish: walking forward from each start, the closest approach within 30 m of the segment
   end, with track distance between 0.9× and 1.2× the segment length.
4. Path check, both ways: resample the segment every 25 m and require ≥95% of the samples
   within 35 m of the activity's sub-path, and ≥90% of the activity's sub-path within 50 m
   of the segment. This rejects parallel roads, the reverse direction and out-and-back
   detours.
5. Effort = elapsed clock at finish minus at start (D7). Several non-overlapping efforts per
   activity are allowed (laps).

### 4.3 Auto-segments
- **Climbs:** on the smoothed elevation profile, from a local minimum to the next maximum,
  merging dips under 10 m; keep it if gain ≥ 25 m, length ≥ 400 m and average grade ≥ 3%.
- **Repeated stretches:** compare a new activity with your earlier same-type activities
  that share many ~100 m grid cells with it, and keep the runs where both follow the same
  path in the same direction. Where a run ≥ 1 km is shared by ≥ 3 activities and no
  existing segment covers > 50% of it, create a segment. Segment ends fall where routes
  diverge, which gives "junction to junction" stretches instead of arbitrary chunks.
- **Tuning by replay**, the way GPS-METRICS-PLAN does it: run the matcher and generator
  over the dev stack's 291 activities offline and report segment count, efforts per
  segment, and any obvious false matches before shipping. Expected: the commute stretches
  match nearly all of their ~50 rides, no segment matches in reverse, and there are tens of
  auto-segments, not thousands. Thresholds above are starting points; the replay decides.

## 5. Delivery: PRs, in order

Each PR targets `main`. "Part of #190/#102" in all but the final ones; the PR that
completes an issue carries `Closes #<n>`.

### PR 1: Records foundation and Progress page (#190)
- Do: migration (new analysis columns + `activity_best_efforts`, backfilled); the D3
  distances (`ANALYSIS_VERSION` 14); a new **Progress** nav page with an activity-type
  filter; this week/month/year vs the previous one (count, distance, moving time,
  elevation); a bar chart of distance per week/month/year (uPlot bars, metric switchable);
  a speed-and-distance-per-activity trend with a rolling average; a records table (D3, D5)
  linking to each record's activity; and "PR / 2nd / 3rd" badges on the detail page's
  best-efforts table.
- Verify: unit tests for bucketing across DST and year boundaries, rank ties, delete
  cleanup and the backfill; `test_api_contract` still green; in the container, compare
  the page's totals with a hand `sqlite3` sum over the dev DB, and confirm startup
  re-analysis of all 291 activities completes cleanly.
- Labels: `enhancement` + `upgrade-note` (re-analysis on startup).

### PR 2: Chart range selection (#102 part 5)
- Do: drag on the detail chart to select a range. A stats panel shows distance, time,
  average speed/pace, elevation gain/loss and average grade, with the range highlighted on
  the map. Clear the selection with a button or a double-click. Works on shared activities.
- Verify: JS logic covered by a page test of the rendered numbers for a fixture; manual
  check in the container on a real ride (selection matches a split's numbers when it
  spans exactly that split).
- Labels: `enhancement`.

### PR 3: User segments and matching (#102 parts 6, and #190 part 1 for segments)
- Do: `segments`/`segment_efforts`; "Save as segment" from a PR 2 selection; background
  matcher (D11) with a progress indicator; a **Segments** page (list, rename, delete; per
  segment: map, your efforts ranked, best-time-over-time chart); a "Segments on this
  activity" card on the detail page with PR/2nd/3rd badges and click-to-highlight on the
  chart and map.
- Verify: matcher unit tests with synthetic tracks (exact, noisy, reversed, parallel road
  40 m away, detour, two laps); the §4.3 replay report on dev data; container check that
  saving a commute stretch finds roughly the expected ~50 efforts.
- Labels: `enhancement`.

### PR 4: Segment sharing (#102 part 8)
- Do: `segment_shares`, share controls on the segment page, shared segments listed
  separately, leaderboard visibility per D9.
- Verify: visibility tests for every grant combination (no grant, history grant, segment
  share only, revoked); container check with a second user.
- Labels: `enhancement`. `Closes #102` waits for PR 5.

### PR 5: Auto-segments (#102 part 7)
- Do: climb and repeated-stretch generation (§4.3), run per activity after analysis and as
  a one-off backfill over history; hide/unhide; auto-segments badged as such on the
  Segments page.
- Verify: replay report signed off **before** the PR opens; generator unit tests (no
  duplicates on re-run, hidden not recreated, reuse instead of create).
- Labels: `enhancement`. `Closes #102`.

### PR 6: Tie-ins (#190 remainder)
- Do: segment PRs and recent achievements on the Progress page; on the detail page, "vs
  your last 10 rides of this route" when the activity's main stretch is a known segment
  (falls back to same activity type otherwise).
- Labels: `enhancement`. `Closes #190`.

## 6. Compatibility (docs/VERSIONING.md)
- PRs 1–6 are web-only: no `openapi.json` change, no `API_LEVEL` bump.
- PR 1 changes `analysis.result` only additively (more `best_efforts` entries; 1000 and 5000
  kept). `app-reads.json` is unchanged.
- No GPX `sat:` change.

## 7. Out of scope
- Mobile views of progress/segments (D10, tracked on #101).
- Heart rate, cadence and power (D13 makes room for them).
- Cross-user public leaderboards, and segments discovered from other users' rides.
