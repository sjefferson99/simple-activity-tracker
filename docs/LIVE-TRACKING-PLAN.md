# Live tracking and sharing plan — issue #130

Status: **approved 2026-10-01. Phases A to D done; review and README refresh before the PR.**

Scope, from [issue #130](https://github.com/sjefferson99/simple-activity-tracker/issues/130):

1. While an activity is recorded, the phone uploads the route so far to the server
   about once a minute. That gives a **backup** if the phone dies mid-route and
   lets **chosen users on the same server follow the activity live**.
2. A user chooses which other users can see their **live** activities and their
   **history**, plus per-activity extra viewers for finished activities.
3. The web activities page gets **Mine / Shared with me** tabs, both with the
   existing filters.

The guiding rule: **the tracked user is always in control.** Every grant is made
by the owner, every revocation takes effect on the viewer's next request, and a
viewer can never keep or take away more than the owner currently allows.

## 0. Decisions (made with the owner on 2026-10-01 — do not re-open)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Grant granularity | Per viewer, two independent switches: **Live** and **History**. |
| D2 | Per-activity sharing | A finished activity can be shared with extra users from its detail page (web). Applies to **history only**; there are no per-session live grants. |
| D3 | Live upload on the phone | **On by default**, a single Settings toggle "Live upload" (off saves mobile data). Takes effect immediately, even mid-run: off stops uploading; on uploads everything recorded so far, then keeps updating. |
| D4 | Live sharing on the phone | Settings shows a **"Don't live share"** switch and the list of users with the **Live** grant (pick from a dropdown of every user). Edits go to the server and apply immediately, even mid-run. History grants are web-only. |
| D5 | Picking users | Dropdown of **every enabled user's display name** (small groups of friends). Emails are never shown to other users. |
| D6 | Phone died mid-route | The owner's live page has a **Convert to activity** button. If the phone's proper upload arrives later, it **overwrites** the converted activity in place. |
| D7 | Downloads and export | **Viewers cannot download or export anything**, live or history. No GPX download, no export button, no bulk export of shared activities. May be added later. |
| D8 | Live viewer at completion | **Live access ends when the activity finishes.** An open live page switches to "This activity has finished" until closed. The viewer can see the finished activity only if they separately have History access (D1/D2). |
| D9 | Viewers hiding shares | Not in this issue. |
| D10 | Mobile viewing of shared activities | Not in this issue (web only; see #101/#107). |

Recommendations, not objected to, treated as decided:

- **The phone does not split the GPX file.** `RunGpxLog` stays as it is (its
  atomic full rewrite is the crash-safe local record and the final upload). The
  live uploader sends **point batches** with a server-acknowledged index (§2.3).
- **Live sessions are their own tables**, never half-finished `activities`
  rows, so lists, filters, stats, export and analysis are unaffected.
- **"Don't live share" is a server-side pause flag**, not a cleared list, so
  re-enabling keeps the chosen users.
- **Viewer pages are web-only routes**, not `/api/v1`, so the phone API only
  grows by what the phone needs (shares, user directory, live upload).
- Web live view **polls** (htmx, ~15 s). No SSE/websockets.

## 1. Findings that shape the design

- `_clientRunId` is created at Start (`live_run_controller.dart`, `start()`),
  before any point. It is the natural key for the live session **and** the
  final upload's idempotency key (`client_activity_id`), which is how the two
  get linked without any new id.
- The location stream already runs in a foreground service (geolocator
  `ForegroundNotificationConfig`), so the Dart isolate keeps running with the
  screen off and periodic HTTP calls work mid-run, like the GPX flush timer.
- Every existing activity route scopes by owner via
  `get_by_id_for_user(user.id, …)` and 404s otherwise. **All of those stay
  owner-only.** Viewer access is added through new, separate read-only routes
  with one visibility helper, never by loosening the existing ones.
- `_insert_activity_with_gpx` returns the existing row unchanged for a repeated
  `client_activity_id`. D6 needs one exception: a row converted from live is
  replaced in place (§4).
- Tags are per-user. In the Shared tab, the text search matches the
  **owner's** tags on the activities the viewer can already see; nothing
  lists an owner's full tag vocabulary.
- "Cannot download" (D7) means no download/export affordance or endpoint. The
  map still needs track points in the viewer's browser, so this is a policy on
  what the server offers, not DRM. Say so in the UI help text, not as a promise.

## 2. Design

### 2.1 Data model (one Alembic migration per phase that needs it)

```
users            + live_sharing_paused bool not null default false        -- D4, phase B

user_shares      owner_id fk users · viewer_id fk users
                 · can_view_live bool · can_view_history bool
                 · created_at · updated_at
                 · PK (owner_id, viewer_id) · CHECK owner_id <> viewer_id
                 -- a row with both flags false is deleted, not kept

activity_shares  activity_id fk activities · viewer_id fk users · created_at
                 · PK (activity_id, viewer_id)

live_sessions    id UUID pk · user_id fk · client_activity_id
                 · activity_type · started_at · split_plan JSON nullable
                 · state enum(active|paused|finished|converted)
                 · latest_metrics JSON nullable · next_index int
                 · last_update_at · finished_at nullable
                 · activity_id fk activities nullable   -- set by convert or final upload
                 · UNIQUE (user_id, client_activity_id)

live_points      session_id fk · idx int · t · lat · lon · ele nullable
                 · accuracy nullable · speed nullable · segment int
                 · PK (session_id, idx)

activities       + recovered_from_live bool not null default false         -- phase D
```

Deletes follow the existing explicit-FK style (flush children before parents):
deleting an activity deletes its `activity_shares`; deleting a user deletes
their `user_shares` (both directions), `activity_shares` as viewer, live
sessions and points. A disabled user is excluded from the dropdown, can't view
anything (they can't sign in), and their own live sessions are hidden.

### 2.2 Visibility rules (one module, `app/sharing.py`)

- `can_view_history(viewer, activity)`: owner is not the viewer, and either
  `user_shares(owner, viewer).can_view_history` or an
  `activity_shares(activity, viewer)` row exists.
- `can_view_live(viewer, session)`: `user_shares(owner, viewer).can_view_live`,
  `owner.live_sharing_paused` is false, and `session.state in (active, paused)`.
- `live_finished_notice(viewer, session)`: as `can_view_live` but with state
  `finished`/`converted`. Gives **no data**, only the D8 "finished" message,
  plus a link to the activity if `can_view_history` holds for it.
- Evaluated **on every request**, never cached or captured at session start.
  That is what makes mid-run changes (D3, D4) and revocations immediate.
- Anything else is a **404** (never 403), as today.
- Admins get nothing extra.

### 2.3 Live upload protocol (`/api/v1`, API level 2)

| Method & path | Purpose |
|---|---|
| `PUT /api/v1/live/{client_activity_id}` | Create or update session metadata: `{activity_type, started_at, split_plan?}`. Idempotent. Returns `{next_index, state}`. |
| `POST /api/v1/live/{client_activity_id}/points` | `{from_index, points[], metrics?, state}` where `state` is `active`/`paused`/`finished`. Points already stored are ignored; `from_index > next_index` → **409** `{next_index}`; session converted → **410**. Returns `{next_index, state}`. |
| `DELETE /api/v1/live/{client_activity_id}` | Owner discarded the run on the phone: delete session and points. |
| `GET /api/v1/users` | Directory for the dropdown: `[{id, display_name}]`, enabled users except the caller. |
| `GET /api/v1/me/shares` | `{live_sharing_paused, shares: [{viewer_id, display_name, can_view_live, can_view_history}]}` |
| `PUT /api/v1/me/live-sharing` | `{live_sharing_paused, live_viewer_ids[]}`. Sets the **Live** column only; History flags untouched. Last write wins. |

Limits: at most 2,000 points per request, 200,000 per session; coordinates and
timestamps validated with the existing `app/validation.py` style; the live
endpoints get a per-user rate limiter (reset in `tests/conftest.py`). Unknown
request fields ignored (`extra="ignore"`). `metrics` is a small, fixed schema of
what the phone shows (distance, elapsed/moving time, current pace/speed,
current split index and its progress); unknown fields ignored.

### 2.4 Web

- **Settings → Sharing:** table of users with Live/History checkboxes, add-user
  dropdown, the "Don't live share" switch.
- **Activities page:** tabs **Mine** / **Shared with me**, both with the existing
  filters and pagination. Shared adds an Owner column and owner filter. A
  **Live now** strip at the top of each tab lists active sessions: your own on
  Mine (link to your live page), viewable ones on Shared.
- **Shared activity detail** (`/shared/activities/{id}`): the same template in
  read-only mode. No edit, tags, delete, splits re-slice that saves, GPX
  download or export. Its map feed is a web route checked by
  `can_view_history`, not `/api/v1/.../track`.
- **Owner's own detail page:** "Also share with…" (D2): add/remove users.
- **Live page** (`/live/{session_id}`): map, phone metrics, splits so far,
  "Last update N min ago" (highlighted once older than 3× the upload interval).
  Polls a fragment plus new points since the last index. Viewer outcomes:
  - finished/converted and still holding Live → page swaps to "This activity has
    finished" and clears the map; link to the activity only with History access;
  - revoked, paused, or otherwise 404 → "This live activity is no longer shared
    with you" and the map is cleared.
  - The owner's own live page also has **Convert to activity** (phase D) and
    **Delete**.
- **Stale sessions:** hidden from viewers after **12 h** with no update; purged
  after **30 days** unless converted or linked. (Defaults; adjust in review.)

### 2.5 Mobile

- `core/sync/live_upload_service.dart`, behind `ApiClient` (only
  `http_api_client.dart` knows the URLs). It holds the run's points in memory,
  the server-acknowledged index, and a timer (60 s). It also sends on pause,
  resume and stop. On 409 it rewinds to the server's `next_index`; on 410 it
  stops for that run; network errors just wait for the next tick.
- **Only active when `serverApiLevel >= ApiLevels.liveTracking` (2).** On older
  servers the feature is hidden in Settings with "needs a newer server".
- **Settings:**
  - **Live upload** (local preference, default on). Changing it mid-run
    starts/stops the uploader at once; starting mid-run begins at index 0.
  - **Live sharing**: "Don't live share" switch plus the user list (dropdown
    from `GET /users`). Saved via `PUT /me/live-sharing`. If offline, the
    latest change is kept as **one pending document** and sent **before** any
    further live points. Disabled with an explanation when Live upload is off.
- **Live run screen:** a "Live · shared with N" / "Live · not shared" / "Live
  upload off" badge. The foreground notification text says when sharing is on.
- Stop: final batch with `state: finished`, then the existing upload flow,
  unchanged. Discarding a run (`confirm_delete_run_record`) calls the delete
  endpoint (best effort, queued like other sync work).
- No change to the upload payload, `RunSummary`, or GPX `sat:` extensions.

## 3. Security checklist (tests in every phase that touches it)

- Every existing mutating or owner route (API and web) returns **404** for a
  viewer with every combination of grants. Parametrised over the route list.
- Viewer routes: 404 without a grant; immediately 404 after revoke, after the
  pause flag is set, after the owner is disabled or deleted; no data in the
  "finished" response.
- A viewer can't reach GPX download, export, bulk export, track via
  `/api/v1`, or analysis via `/api/v1`.
- Only the owner can create, change or delete shares; `PUT /me/live-sharing`
  can't touch another user's rows; sharing with yourself is rejected; unknown
  or disabled viewer ids are rejected.
- Live endpoints only accept the caller's own sessions (`user_id` scoping by
  `client_activity_id` is per-user).
- Audit log entries: grant, revoke, pause/unpause, per-activity share, convert.
- Display names only; no emails in the directory or any viewer page.
- `snyk_code_scan` on `server/` per branch.

## 4. Convert and overwrite (D6)

- Owner only, from their live page. Builds a GPX from `live_points` (segments
  kept, `sat:` split extensions from the session's `split_plan`, using the
  existing writer) and a `client_summary` from `latest_metrics`, then runs the
  normal `_insert_activity_with_gpx` path with `recovered_from_live = true`.
  The session becomes `converted` and links the activity. Later points → 410.
- Warns first if the session updated in the last 10 minutes ("the phone may
  just be out of signal").
- **Final upload for a `recovered_from_live` activity** (same
  `client_activity_id`): replace GPX blob, `client_summary`, split fields,
  timestamps and analysis **in place**; keep the id, title, notes, tags and
  `activity_shares`; clear `recovered_from_live`; delete the old blob after
  commit. Any other existing row keeps today's return-unchanged behaviour.
- A final upload for a non-converted session links the session
  (`activity_id`), sets it `finished`, and deletes its points after commit.

## 5. Phases

All phases go on **one branch, `server-130-live-tracking`, one commit per
phase**, and **one PR at the end** (decided 2026-10-01). Work stops after each
phase for the owner to test it, then code review. The server workflow in
CLAUDE.md applies to each phase (container check before sign-off).

### A — Shares and shared history

- Do: `user_shares`, `activity_shares`; `app/sharing.py`; Settings → Sharing
  (History column only in this phase); per-activity "Also share with…"; Mine /
  Shared with me tabs with filters and Owner column; read-only shared detail
  page and its map feed; delete cascades; audit events. Web-only, so no
  `openapi.json` change and no API level bump.
- Verify: §3 tests for history; filters behave the same on both tabs; a viewer
  sees no download/export/edit controls and the routes 404; container check
  with two real users.

### B — Live sessions

- Do: `live_sessions`, `live_points`, `users.live_sharing_paused`; §2.3
  endpoints; Live column and pause switch in Settings; Live now strips; live
  page with polling and the D8/revoke outcomes; final upload links and cleans
  up; stale hiding and purge. **API level 2**: bump `API_LEVEL` and
  `kAppApiLevel`, VERSIONING.md §2 row, regenerate `openapi.json`.
- Verify: protocol tests (idempotent repeat, gap → 409, chunked backfill from 0,
  limits, rate limit); §3 live tests; curl a simulated run in the container
  while a second user watches the live page; revoke mid-run.

### C — Mobile live upload

- Do: §2.5. `ApiLevels.liveTracking = 2`; `FakeApiClient` support for the new
  calls.
- Verify: unit tests for the uploader (ack index, 409 rewind, 410 stop, toggle
  off/on mid-run with backfill, pending sharing change sent before points);
  tests against a level-1 server (feature hidden, nothing sent); on a physical
  phone: real run, watched from the web, airplane mode mid-run then back,
  toggles changed mid-run.

### D — Convert to activity

- Do: §4. `activities.recovered_from_live`.
- Verify: convert then final upload replaces in place and keeps
  title/notes/tags/shares; second final upload is a no-op; points after convert
  → 410; analysis of a converted activity matches the same points uploaded as
  GPX; container check with a run whose phone "dies" (stop the simulated
  uploader) and later uploads.

### Before the PR — README refresh (requested 2026-10-01)

- Do: read through the code and every past PR to build a full picture of
  what the app and server do, then rewrite `README.md` with a clear summary
  of what the app is and how it works, plus a **full feature list** covering
  every existing feature that still makes sense, as well as this issue's
  sharing and live tracking.
- Verify: the owner reviews the README as part of the PR review.

## 6. Out of scope

Viewer download/export (D7), viewers hiding shares (D9), viewing shared
activities in the mobile app (D10), privacy zones around start/end points,
push notifications to viewers.
