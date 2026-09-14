# Activity search plan — issue #76 (with groundwork for #82)

Status: **plan written 2026-09-14, awaiting owner review — nothing implemented.**

Scope, from [issue #76](https://github.com/sjefferson99/simple-activity-tracker/issues/76):

1. A search box on the activities list page: free text over activity **title**,
   **notes** ("description") and **tag names** (tags added to the issue 2026-09-14).
2. Store each activity's **start and finish coordinates** as part of the analysis, and let
   the user search by a lat/lon + radius, choosing whether it applies to the start, the
   finish, or both.
3. A **map** the user can open from the search box to browse and drop a pin, filling in the
   lat/lon for them.
4. A **distance range** filter — minimum and/or maximum length in km (added to the issue
   2026-09-14; "length" is distance, not duration).

All active filters combine with AND.

[Issue #82](https://github.com/sjefferson99/simple-activity-tracker/issues/82) (show a place
name for the start/finish on each list row) is **not** implemented here, but §6 says exactly
what this plan lays down for it and what it still needs. The short version: #82 needs the
same start/finish coordinates as #76's part 2, and nothing else in #76 overlaps with it.

Read CLAUDE.md's "Server dev/test workflow" before starting — every item below follows it
(branch per PR, tests, real-container verification, owner sign-off, then push).

---

## 1. Findings that shape the design

These were checked against the code and the running image, not assumed.

- **The list page already has all the plumbing a filter needs.** `activity_list()` in
  `server/app/web/activities.py` reads `page`/`per_page`/`sort`/`dir` as plain strings,
  defaults anything malformed, calls `SqlAlchemyActivityRepository.list_for_user_page()`
  (a LEFT JOIN of `activities` → `activity_analyses`, count + offset/limit), and renders
  either the whole page or just `#activity-list-region` for an htmx request. Search is
  "more WHERE clauses on that query, more params in that URL" — no new page, no new
  pagination model.
- **The URL state is hardcoded in three templates.** `partials/activity_list_controls.html`
  and `partials/activity_list_pagination.html` each build
  `/?page=…&per_page=…&sort=…&dir=…` by hand (sort links, page links, and the per-page
  `<select>`'s `hx-vals`). Adding five filter params to every one of those by hand is the
  bug farm to avoid — §3.1 replaces them with one URL builder first.
- **Start/finish coordinates already exist on disk for almost every row**, just not in a
  queryable column: `ActivityAnalysis.track` (the R8 cache, `{"segments": [[{lat, lon,
  ele, t}, …], …]}`) always keeps each segment's first and last point (`sample_track()`
  appends `points[-1]` if the stride skipped it). So a migration can **backfill** the new
  columns with `json_extract(track, '$.segments[0][0].lat')` and
  `'$.segments[#-1][#-1].lat'` — SQLite's `[#-1]` last-element syntax is available in both
  the container's SQLite (3.46.1, checked with `docker run … python -c`) and this
  machine's (3.49.1). Only rows analysed before R8 (null `track`) need `reanalyze`.
- **Leaflet is already vendored and the CSP already allows the OSM tile host** (`img-src
  … https://tile.openstreetmap.org` in `app/security_headers.py`, Leaflet 1.9.4 under
  `app/static/vendor/leaflet/`). The pin-drop map in part 3 therefore needs **no mapping
  API, no new dependency, no CSP change** — it is the same map the detail page draws,
  with a click handler. The issue's "this will definitely need a mapping API" only becomes
  true if we add *geocoding* (typing a town name) — that's #82's dependency, see §6.
- **An index cannot make a substring search fast, and it doesn't need to be.** A
  `LIKE '%term%'` can never use a B-tree index (leading wildcard). What bounds the work is
  the existing `ix_activities_user_started_at` narrowing the scan to one user's rows, and
  per-user row counts here are small (the dev stack has 11; a heavy Strava importer might
  reach a few thousand). SQLite scans that in a few milliseconds even with 4 KB notes on
  every row. The only way to make it *index-backed* is an FTS5 virtual table, and both
  SQLites checked do have FTS5 — but see decision §2.1 for why that's the escalation
  path, not the starting point.
- **Tags are already cheap to search.** `tags` is per-user with `uq_tags_user_id_name`,
  and `activity_tags` has `ix_activity_tags_tag_id`, so "activities with a tag whose name
  contains X" is a tiny subquery over one user's tag rows (typically a handful) joined
  through an indexed association table. No new index needed.
- **The distance range is a plain column comparison.** `ActivityAnalysis.distance_meters`
  was denormalised for #75 exactly so the list could sort and display it without JSON
  extraction; a `BETWEEN` on it in the same joined query costs nothing extra.
- **Distance-from-a-point can be done in SQL with plain arithmetic** — no trig functions
  in the DB (the container's SQLite has `ENABLE_MATH_FUNCTIONS`, but CI's Python may not,
  and we don't want the query tied to a compile flag). Equirectangular approximation:
  `((lat − lat0)·111320)² + ((lon − lon0)·111320·cos(lat0))² ≤ r²`, with `cos(lat0)`
  computed in Python. Error is well under 0.5 % for radii up to ~50 km at any latitude a
  runner is likely to be at — far inside GPS noise — and it works with the existing
  count + offset pagination, unlike a Python-side post-filter would.
- **The `{% if total %}` in `partials/activity_list_or_empty.html` conflates "no
  activities at all" with "no matches".** With a filter active and zero matches it would
  show the "Sign in to the phone app…" onboarding card and, worse, drop the sort/page
  controls — leaving no way to see the filter is what's hiding things. §3.4 splits the
  two states.
- **The mobile app is unaffected.** `AnalysisDto` (`mobile/lib/core/api/dto/analysis_dto.dart`)
  holds `result` as a raw map and only reads known keys, so adding `start`/`end` to the
  result JSON is safe. Nothing in this plan touches `/api/v1`, so `openapi.json` stays
  unchanged (the repository filter is written so an API `q=`/geo query could reuse it
  later, but that's not in scope).

---

## 2. Decisions (owner to confirm or overrule)

### 2.1 Text search: `LIKE` now, FTS5 only if it's ever measurably slow — **recommended**

Substring match, case-insensitive, over `title`, `notes` and the names of the activity's
**tags**, with the query split on whitespace and **every term required** (each term may
match any of the three). `%` and `_` in user input are escaped (`ESCAPE '\'`).
Implemented as `lower(col) LIKE lower(:pattern)` — SQLite's own `LIKE` is only
case-insensitive for ASCII; `lower()` on both sides is the same limitation stated
honestly, and fine for a personal tracker. The tag leg is an `EXISTS` subquery per term
(§3.2), so a term matching one tag and another term matching the title still counts as a
match — the terms are ANDed at the activity level, not the column level.

Why not FTS5, which the issue's "add appropriate indexes" points at:

- It needs a virtual table plus three triggers to stay in sync, its own tokenizer rules
  (prefix/stem behaviour differs from "contains"), and a migration that rebuilds the
  index from every row — real complexity for rows-per-user that fit in one page of memory.
- CLAUDE.md's stated justification for waving through Trivy's `libsqlite3-0` CVE on the
  base image (issue #75 notes) is specifically *"the SQLite CVE is about FTS5, which this
  schema doesn't use"*. Adopting FTS5 silently invalidates that reasoning.

If a deployment ever gets slow here, FTS5 is a contained follow-up: same repository
method, same route, a new virtual table behind it. Not worth pre-building.

**Not searched:** device name and activity type (the type badge already makes it visible;
a type filter would be a different, cheap control — say the word).

### 2.1a Distance range: min/max km on the server's analysed distance

`min_km` and `max_km`, each optional, each 0–10000 with up to two decimals, compared
against `COALESCE(activity_analyses.distance_meters, 0)` — the same figure the list
already sorts and displays (#75), so what the user sees is what the filter tests. An
activity with no analysis (or a failed one) has distance 0: it's excluded by any
`min_km > 0` and included by any `max_km`, which matches how it already sorts as 0.
`min_km > max_km` is a validation notice (§2.3's mechanism), not a silent empty result.
"Length" is **distance**, per the owner's steer on the issue; a duration range would be the
same shape on `moving_seconds` if ever wanted.

### 2.2 Where the coordinates live: columns on `activity_analyses` + keys in `result`

Four nullable `Float` columns — `start_lat`, `start_lon`, `end_lat`, `end_lon` — on
`activity_analyses`, mirroring how #75 denormalised `distance_meters`/`moving_seconds`.
`result` also gains `"start": {"lat", "lon"}` and `"end": {"lat", "lon"}` (the first point
of the first segment, the last of the last), and `ANALYSIS_VERSION` bumps 4 → 5 so
`reanalyze --all` is the documented catch-up for any row the migration's backfill can't
reach. The web filter reads the **columns**, so a deployment gets working geo search the
moment the migration runs, without waiting for a reanalyze.

Why not on `activities`: the coordinates are derived from the GPX by the analyser, like
distance; keeping every derived number on the analysis row keeps "reanalyze fixes it"
true for all of them.

### 2.3 Geo filter semantics

- Inputs: `lat`, `lon` (decimal degrees), `radius_km` (default **1**, allowed
  0.05–100), `geo` ∈ `start` | `finish` | `either` | `both`. Four options rather than the
  issue's three because "both" is ambiguous — someone searching "runs near the office"
  wants *either* endpoint; someone searching "loops from home" wants *both*. The extra
  radio button costs nothing and removes the guess.
- The filter is only applied when `lat` **and** `lon` are both present and valid.
  Invalid values (out of range, non-numeric) don't 422 the page — like the existing
  param handling — but they *don't* silently no-op either: the geo filter is skipped and a
  one-line notice renders above the list ("Latitude must be between -90 and 90"), so the
  user isn't left wondering why the pin did nothing.
- Activities with no analysis row, or a failed one, have null coordinates and never match
  a geo filter (they still match with no geo filter set, as today).
- Antimeridian and the poles are ignored on purpose (the approximation degrades there;
  no runner here is affected; noted in a code comment).

### 2.4 Map picker: Leaflet, no geocoding, no new dependency

A "Pick on map" button next to the lat/lon inputs expands a Leaflet map **in the search
form**. Click places (or moves) a draggable marker and writes the coordinates into the
inputs at 5 decimal places (~1 m); a circle shows the current radius and follows the
radius input. Editing the inputs by hand moves the marker. There is no "type a place name"
box — that is geocoding, which needs an external service (see §6); the owner has asked
for the pin-drop map, and typing a lat/lon still works as the issue describes.

Initial view: if the form already has a lat/lon, centre there at zoom 13; otherwise centre
on the **user's most recent analysed activity's start point** (the server passes it as
`map_default_center` — one extra tiny query, only on the full-page render) at zoom 11;
otherwise the world at zoom 2. That makes the first open land somewhere useful without
assuming a country.

### 2.5 Delivery: three PRs, in this order

| PR | Branch | Contents | Why separate |
|---|---|---|---|
| A | `server-76a-endpoint-coordinates` | §3.0 — columns, migration + backfill, analyser `start`/`end`, version bump, reanalyze | Smallest, safest, and it is *all* that #82 needs from #76. Ships value on its own (coordinates via the API). |
| B | `server-76b-text-search` | §3.1–3.4 — URL builder refactor, search form, text filter (title/notes/tags), distance range, empty-state split | Pure web + repository work with no schema change; reviewable on its own. |
| C | `server-76c-geo-search` | §3.5–3.6 — geo filter + map picker | Depends on A (columns) and B (form/URL builder). |

B and C can be one branch if the owner prefers fewer reviews; A should stay separate.
Each gets a `docs/`-free commit except where noted; CLAUDE.md's status block is updated
per PR as usual.

---

## 3. Work items

### 3.0 Endpoint coordinates (PR A)

- **Do (analyser):** in `app/analysis/v1.py`, add `start`/`end` to `AnalyzerV1.analyze()`'s
  result (`{"lat": …, "lon": …}` from `all_points[0]` / `all_points[-1]`). Bump
  `ANALYSIS_VERSION` to 5 with the usual comment line ("5: start/end endpoints, issue
  #76"). Add `endpoints_from_result(result) -> tuple[float | None, float | None, float | None, float | None]`
  next to `distance_and_duration_from_result()` — same contract (all-None for a
  missing/failed result), and wire it into **both** writers of `ActivityAnalysis`:
  `_insert_activity_with_gpx()` in `app/api/v1/activities.py` and `reanalyze()` in
  `app/cli.py`.
- **Do (model + migration):** `ActivityAnalysis` gains `start_lat`, `start_lon`,
  `end_lat`, `end_lon` (`Float`, nullable, no default — null means "unknown", never 0/0
  which is a real place). One Alembic migration, following `0aff3bc612d3`'s shape:
  `add_column` ×4, then a backfill `UPDATE activity_analyses SET start_lat =
  json_extract(track, '$.segments[0][0].lat'), … end_lat = json_extract(track,
  '$.segments[#-1][#-1].lat'), … WHERE track IS NOT NULL AND status = 'done'`. Downgrade
  drops the four columns. No index — the list query is already scoped by `user_id` on the
  joined table and the per-user cardinality doesn't justify one (say so in the migration
  docstring, same as the LIKE reasoning).
- **Do (docs):** nothing user-facing yet; CLAUDE.md status entry on merge, plus a line in
  the standalone-tls README's existing "reanalyze" mention that `reanalyze --all` after
  this upgrade only matters for activities analysed before the R8 track cache existed.
- **Verify (tests):**
  - `test_analysis_v1.py`: the synthetic fixture's result has `start`/`end` equal to its
    first/last points; a single-point track gives `start == end`.
  - `test_activities_api.py`: after upload, the analysis row's four columns are populated
    and equal `result["start"]`/`result["end"]`.
  - `test_cli_reanalyze.py`: a row with the columns nulled and a stale version gets them
    filled by `reanalyze --all`; a failed analysis leaves them null.
  - A migration test (pattern: `tests/conftest.py::run_migrations()` against a tmp DB at
    the previous head, insert a row with a hand-built `track` JSON and a null-track row,
    upgrade to head, assert the first is backfilled and the second stays null).
- **Verify (container):** on the dev stack, `docker compose up -d` runs the migration;
  `docker exec … sqlite3` (or a one-off `python -c`) shows all 11 analysis rows with
  non-null columns from the backfill alone; `reanalyze --all` then reports the 11 rows
  (version bump) and leaves the coordinates unchanged.

### 3.1 One URL builder for the list (PR B, do first)

- **Do:** add a `list_url()` Jinja global (in `app/web/templating.py`, implementation in a
  small pure module such as `app/web/list_query.py`) that takes the current list state
  (a frozen dataclass `ActivityListQuery`: page, per_page, sort, dir, q, min_km, max_km,
  lat, lon, radius_km, geo) plus keyword overrides and returns `/?…` with **only non-default**
  params included, via `urllib.parse.urlencode` (so `q` is escaped correctly). The
  route builds one `ActivityListQuery` from the request and puts it in the context as
  `list_query`; every existing hand-built URL in `activity_list_controls.html` and
  `activity_list_pagination.html` becomes `{{ list_url(list_query, page=p) }}` /
  `{{ list_url(list_query, sort=…, dir=…, page=1) }}`. The per-page `<select>` keeps
  `hx-include="this"` for its own value but its `hx-vals` becomes the same dict minus
  `per_page` (a `list_vals()` sibling, or just `list_query` serialised with `tojson`).
- **Verify:** existing pagination/sort tests keep passing unchanged (this is a pure
  refactor until 3.2 adds params); one new unit test on `list_url()` covering
  omit-defaults, override, and `q` containing `&`/spaces/unicode.

### 3.2 Search form + text filter + distance range (PR B)

- **Do (repository):** `list_for_user_page()` gains a `filters: ActivityListFilters`
  argument (frozen dataclass: `text: str | None`, `min_m: float | None`,
  `max_m: float | None`, and the geo fields used by 3.5, all None by default). A private
  `_apply_filters(stmt)` adds the WHERE clauses, and the **count query must use the same
  filters** as the page query (build the filtered base select once, derive both from it).
  - Text: split on whitespace, drop empties, cap at 10 terms and 200 chars total. For
    each term with `p = f"%{escaped_term}%"`:
    `or_(lower(Activity.title).like(p, escape="\\"), lower(Activity.notes).like(p, escape="\\"), tag_match)`
    where `tag_match = exists(select(1).select_from(activity_tags).join(Tag, Tag.id ==
    activity_tags.c.tag_id).where(activity_tags.c.activity_id == Activity.id,
    lower(Tag.name).like(p, escape="\\")))`. (`Tag.user_id` needn't be re-checked — the
    outer query is already scoped to the user's activities, and tags are per-user.)
  - Distance: `distance >= min_m` / `distance <= max_m` on the same
    `func.coalesce(ActivityAnalysis.distance_meters, 0.0)` expression the sort already
    uses (extract it into a module-level helper so the two can't drift).
- **Do (route):** read `q` (strip, truncate to 200), `min_km`, `max_km` (parse as float;
  blank → None; non-numeric, negative or > 10000 → notice and ignored; `min > max` →
  notice and both ignored), convert km → m, build the filters, pass them through.
  Context gains `list_query` (3.1), `filters_active: bool`, and
  `filter_errors: list[str]` (distance notices here; 3.5 adds geo ones).
- **Do (template):** new `partials/activity_search_form.html`, included in
  `activities_list.html` **above** `#activity-list-region`, *outside* it — the region gets
  swapped on every sort/page/search response and swapping the input the user is typing in
  would steal focus and drop keystrokes. The form: `hx-get="/" hx-target="#activity-list-region"
  hx-select="#activity-list-region" hx-swap="outerHTML" hx-push-url="true"
  hx-indicator="#activity-list-spinner"`, with hidden `sort`/`dir`/`per_page` inputs
  carrying the current state (so a search keeps the user's sort) and `page` **not**
  included (a new search always starts at page 1). The `q` input gets
  `hx-trigger="input changed delay:400ms, search"` (`type="search"` gives a native clear
  button, and `search` fires on it). Next to it, a "Distance" pair: `min_km` and `max_km`
  (`type="number" min="0" max="10000" step="0.01"`, placeholders "min km" / "max km"),
  triggering on `change` and on `input changed delay:400ms` like the text box. A visible
  "Search" submit button too, for keyboard users and no-JS fallback (the form is a real
  GET form, so it works with htmx absent). A "Clear" link → `/` (plain, not htmx — a full
  reload is the simplest way to reset every field). Notices from `filter_errors` render
  inside `#activity-list-region` above the controls so they update with each response.
- **Do (history):** htmx restores `#activity-list-region` from its history cache on Back,
  but the search form lives outside the swapped region so its **values** are whatever
  the user last typed, not what the restored URL says. Add a few lines to the page's
  nonce'd script: on `htmx:historyRestore` and on initial load, set each form field from
  `new URLSearchParams(location.search)`. (Fallback if this proves flaky in the browser
  pass: `htmx.config.historyCacheSize = 0` on this page only, which makes Back a full
  server render — one more request, but the form is then rendered from the URL by the
  server. Prefer the first; verify with the headless pass below.)
- **Verify (tests, `test_web_pages.py`):** `?q=` matches title, matches notes, matches a
  tag name (add the tag via the existing `POST /activities/{id}/tags` route), does *not*
  match another user's tag of the same name, is case-insensitive, requires all terms
  (including one term matching a tag and another matching the title), escapes `%`/`_`
  (a note containing "100%" is found by `q=100%25` and a note "abc" is *not* found by
  `q=%`), ignores a 201-char query's tail, is preserved in every sort/page link and in
  the per-page `hx-vals`, and resets to page 1. Distance: with activities at known
  analysed distances (use `_set_activity_started_at_and_distance` from the #75 tests),
  `min_km` alone, `max_km` alone, both, boundary equality (an exactly-5.00 km activity
  matches `min_km=5`), an unanalysed activity excluded by `min_km=0.01` but included by
  `max_km=1`, `min_km > max_km` renders the notice and the unfiltered total, and
  `min_km=abc` likewise. Repository-level tests for the count matching the page (a
  filter that leaves 3 of 5 rows reports `total == 3`) and for text + distance combining
  with AND.

### 3.3 (folded into 3.2 — kept as a numbered reminder) "Export all" and "Delete selected"

`Export all` (`/export`, no ids) exports everything regardless of the filter, which is
what its label says; `Export selected`/`Delete selected` act on checked rows, which can
only be rows the filter showed. Leave both alone; **do not** make "Export all" secretly
mean "export matches". If the owner wants an "Export these results" button later it's a
`list_url()`-built link to `/export?…`, which would need `export_activities` to accept the
same filters — out of scope, note it in the PR.

### 3.4 Empty-state split (PR B)

- **Do:** `partials/activity_list_or_empty.html` branches on three states: `total > 0`
  (list as now); `total == 0 and filters_active` (the controls stay, and the card says
  "No activities match — Clear filters" with the clear link); `total == 0 and not
  filters_active` (the existing onboarding card). `filters_active` is computed in the
  route (any of q / min_km / max_km / lat+lon set), so no second count query.
- **Verify:** a test for each of the two empty states asserting the right copy and that
  the "no matches" one still renders the `#activity-list-region` wrapper with controls.

### 3.5 Geo filter (PR C)

- **Do (repository):** `ActivityListFilters` gains `lat`, `lon`, `radius_m`, `geo`.
  `_apply_filters` adds, for `k_lat = 111_320.0` and `k_lon = 111_320.0 * cos(radians(lat))`
  computed in Python: `near(lat_col, lon_col) = ((lat_col - lat) * k_lat) ** 2 +
  ((lon_col - lon) * k_lon) ** 2 <= radius_m ** 2` on the already-joined
  `ActivityAnalysis` columns; `start` → `near(start_*)`, `finish` → `near(end_*)`,
  `either` → `or_`, `both` → `and_`. Null columns evaluate to NULL and are excluded, as
  wanted. Pure function `equirectangular_scale(lat) -> (k_lat, k_lon)` lives in
  `app/analysis/geo_math.py` next to the haversine, with a docstring stating the
  approximation and its error bound.
- **Do (route):** parse `lat`, `lon`, `radius_km`, `geo`; validate ranges (lat ±90, lon
  ±180, radius 0.05–100, geo in the four values, default `either`); on any failure skip
  the geo filter and append a message to `filter_errors` (the same list and rendering
  the distance range already uses from 3.2).
- **Verify (tests):** repository tests with three activities whose analysis rows are
  given known coordinates directly (start A / end B, etc.): `start` within 1 km finds
  the right one, `finish` likewise, `either` finds both, `both` finds only the loop;
  radius 0.1 km excludes a point 300 m away and 0.5 km includes it (use a real
  displacement, e.g. 0.0027° lat ≈ 300 m); null-coordinate rows never match. Route
  tests: an out-of-range latitude renders the notice and the unfiltered total; params
  survive in sort/page links.

### 3.6 Map picker (PR C)

- **Do (template):** in `activity_search_form.html`, the geo fieldset: `lat`, `lon`
  (`type="number" step="any"`), `radius_km` (number, min/max/step 0.05), the four `geo`
  radios, and a `<button type="button" id="map-picker-toggle">Pick on map</button>` with
  a `<div id="map-picker" hidden>` containing `<div id="search-map">` (height ~320 px, CSS
  in `app.css` next to `#map`). `activities_list.html`'s `{% block head %}` adds the
  Leaflet CSS and `{% block scripts %}` adds `leaflet.js` plus a nonce'd inline script
  (pattern: `activity_detail.html`).
- **Do (script):** on first toggle create the map (Leaflet needs a laid-out container —
  call `map.invalidateSize()` after un-hiding; re-call on every subsequent open), tile
  layer identical to the detail page's (same URL, attribution, `maxZoom: 19`), initial
  view per §2.4 (`map_default_center` is passed as `{{ … | tojson }}`; null when the user
  has no analysed activity). Click → set/move a draggable `L.marker`, update the inputs
  (`toFixed(5)`), update/create an `L.circle` of `radius_km * 1000` m, then
  `htmx.trigger(form, 'submit')` so the list refreshes. `dragend` on the marker does the
  same. `input` on lat/lon/radius updates the marker/circle when the map is open. Keep
  the whole thing under ~80 lines; no state outside the closure except what the form
  holds.
- **Do (CSP):** nothing — `script-src 'self' 'nonce-…'` covers the vendored Leaflet and
  the nonce'd inline script; `img-src` already lists the tile host; Leaflet's
  `style=""` attributes are covered by the existing `style-src 'unsafe-inline'`. Confirm
  in the browser pass that the console shows **no** CSP violation (the S5 verification
  did exactly this for the detail page).
- **Verify:** a route test that the list page includes the picker markup and the Leaflet
  script tag (cheap smoke, like `test_activity_detail_renders_with_map_and_analysis`);
  the real check is the browser pass in §4.

---

## 4. Verification in the real container (per PR, before sign-off)

Follow CLAUDE.md's workflow: build the branch, tag it as the exact
`ghcr.io/sjefferson99/simple-activity-tracker-server:latest` reference, `docker compose
up -d` in `deploy/standalone-tls/`, check `docker logs` for a clean migrate + startup, then:

- **PR A:** query the four new columns for every row (all 11 non-null after the
  migration alone); run `docker exec standalone-tls-app-1 simple-activity-tracker-server
  reanalyze --all` and confirm it reports the version-5 rows with unchanged coordinates;
  `GET /api/v1/activities/{id}/analysis` shows `start`/`end`.
- **PR B:** web login with `-c cookies.txt`; `curl -b cookies.txt 'https://127.0.0.1/?q=…'`
  with a title word, a notes word, a tag name (the dev stack's Strava-imported activities
  carry "Strava"/"running"/"cycling" tags), two terms, an escaped `%25`, and a nonsense
  term (the "no matches" card with controls still present). `?min_km=5`, `?max_km=5`,
  `?min_km=3&max_km=6` against the 11 known distances, and `?min_km=6&max_km=3` showing the
  notice. Confirm an `HX-Request: true` request returns only the region. **Headless-browser pass** (as done for #75): type in the box,
  see the list narrow after the delay, click a page/sort link, press Back, confirm both
  the list *and the search box* reflect the previous URL.
- **PR C:** pick one activity's start coordinates from PR A's columns; `?lat=…&lon=…&radius_km=0.2&geo=start`
  returns it and `geo=finish` doesn't (for an out-and-back both do — pick one that isn't);
  an out-of-range latitude shows the notice and the full list. Browser pass: open the
  picker, confirm tiles load with no CSP console errors, click → inputs fill, circle
  follows the radius input, list refreshes; drag the marker; Back button as above.
- **After merge (each PR):** pull the real GHCR image, restart the dev stack, repeat the
  one probe that changed. The owner's separate prod host needs `reanalyze --all` after PR
  A only if it has pre-R8 rows (the migration backfill covers the rest).

---

## 5. Explicitly out of scope for #76

- Searching device name or activity type, a tag *picker* (as opposed to tag names
  matching the free text, which is in), and a duration range (the badges make type
  visible; each would be a different, cheap control — say the word).
- API (`/api/v1/activities?q=…`) — the repository filter is reusable; the route and
  `openapi.json` change are a separate, small PR if the mobile app ever wants it.
- Filter-aware "Export all" (§3.3).
- FTS5 (§2.1) — only if a real deployment measures the LIKE scan as slow.
- Geocoding in either direction (§6).

---

## 6. Issue #82 — place names on the list rows: what #76 prepares, what remains

**Prepared by PR A:** `start_lat/lon` and `end_lat/lon` on every analysis row, backfilled
for existing data. That is the *only* input #82 needs from the activity side, and PR A is
sized so it could ship alone if #82 were picked up first.

**Recommendation: do #82 as its own PR after #76, not alongside.** Everything it adds is
orthogonal to search and carries its own decisions — chiefly a call to an external
service with the user's home coordinates in it. Sketch, so the later implementer starts
from the same findings:

- **Service:** OSM Nominatim's public `/reverse` (`zoom=10`–`14` gives town/suburb
  granularity; `format=jsonv2`). Its usage policy requires an identifying `User-Agent`,
  **max 1 request/second**, and no bulk use — a Strava import of hundreds of activities
  would violate it if geocoded inline. Alternatives (Photon, a self-hosted Nominatim) are
  heavier than this project wants; a pluggable `SR_GEOCODER_URL` keeps the door open.
- **Storage:** `start_place`/`end_place` (`String(200)`, nullable) on `activity_analyses`
  (derived, like the coordinates), plus a `geocode_cache` table keyed on coordinates
  rounded to 3 decimals (~100 m) — nearly every run starts from the same few places, so
  the cache turns hundreds of lookups into a handful.
- **When it runs:** never inline in an upload or import request. A lazy, rate-limited
  background fill (a `BackgroundTasks` job after upload, plus a `geocode --pending` CLI
  for backfills and imports, sleeping ≥1 s between uncached calls) writes the names as it
  goes; rows render "—" until then. `httpx` is already a dev dependency; it becomes a
  runtime one, or use `urllib` to avoid the addition.
- **Privacy and config:** the feature must be **off by default** (`SR_GEOCODER_ENABLED`
  or a blank `SR_GEOCODER_URL`) and documented in both `.env.example` files: enabling it
  sends the start/finish coordinates of every activity — the user's home, in practice —
  to a third party. The `app` container has unrestricted egress today (the compose
  hardening from D2 restricts the filesystem and capabilities, not the network), so
  nothing blocks the call, but a deployment that locks egress down later needs to allow
  the geocoder host.
- **UI:** the list row's muted line gains `· Bristol → Bath` (or just the start when
  both names match). The activity detail page could show the same under the title.
- **Bonus for #76's picker once the client exists:** a "search for a place" box in the
  map picker calling Nominatim `/search` (forward geocoding) — the same client, the same
  rate limit, same opt-in flag.
- **Tests:** the client is mocked (`httpx.MockTransport` or a fake at the protocol seam);
  cache hit avoids a call; rate limiting sleeps between misses; disabled flag makes every
  call a no-op; a network error leaves the row null and is logged, never raised.
