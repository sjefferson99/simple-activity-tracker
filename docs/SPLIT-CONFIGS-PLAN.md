# Saved split configs plan — issue #126

Status: **approved 2026-09-22. Not started.**

Scope, from [issue #126](https://github.com/sjefferson99/simple-activity-tracker/issues/126):

1. A **named, reusable split configuration** ("save a set of splits config"),
   stored server-side and owned by the account.
2. **API endpoints to sync configs to mobile**, and the ability to **pick a saved
   config** on the mobile app instead of building one from scratch every time.
3. A **web editor page** to build/adjust configs.
4. The ability to **save a config from mobile** (newly entered or an edit of an
   existing one) and **sync it back to the server**.

## 0. Decisions (made with the owner on 2026-09-22 — do not re-open)

| # | Decision | Choice |
|---|----------|--------|
| O1 | Ownership | **Per-user.** Configs belong to the logged-in account, same as activities/devices/sessions. No shared/global library. |
| O2 | Sync direction | **Full two-way.** Web and mobile can both create/edit/delete configs via the API; whichever side changes something pushes it to the server. |
| O3 | Mobile caching | **No local library cache.** The "choose a saved config" list is fetched live from the server every time the picker opens (like the activity list already does). Only the *currently selected/active* plan (today's `SplitPlanController` state) stays cached on-device, for offline running — unchanged from today. |
| O4 | Save entry point on mobile | **Splits screen only.** No "save this run's plan" prompt on the run-finished screen — out of scope here, could be a follow-up issue. |
| O5 | Selection binding | **Copy on select, no live link.** Picking a saved config copies its contents into the local current plan (`SplitPlanController`), exactly like editing any other field on the Splits screen. Editing afterward does **not** silently update the saved config it came from — nothing remembers "this plan came from config X" across app restarts or after further edits. Saving back requires an explicit action (§5.4). |
| O6 | Name uniqueness | **Unique per user, case-sensitive, overwrite with confirmation.** Saving under a name that already exists on that account asks "Replace existing config 'X'?" instead of silently creating a duplicate or erroring. |
| O7 | Mobile delete | **Load + save only on mobile.** Delete/rename of a saved config is web-editor-only in this issue — the mobile Splits-screen addition is limited to §5.3 (load) and §5.4 (save-as), no delete/rename affordance. |
| O8 | Config count limit | **Unbounded**, same as activities — no cap on the number of saved configs per user. |
| O9 | Web nav gating | **Ordinary authenticated page, no admin/allowlist gating** — same reachability as `/devices`/`/settings`, not gated like `/register`. |

Recommendation, not objected to, treated as decided:

- A saved config stores **exactly the same shape as `SplitPlan`/`SplitPlanData`**
  that already round-trips through GPX extensions and mobile's local JSON
  persistence (§1) — no new wire format to invent, and the server's existing
  `SplitPlanOut`/`SplitPlanData` parsing/validation code is reused, not
  duplicated.

## 1. Findings that shape the design

- **The shape already exists three times and must not become a fourth,
  different one.** Mobile's `SplitPlan.toJson()`
  (`mobile/lib/domain/tracking/split_plan.dart`), the server's
  `SplitPlanData` (`server/app/analysis/gpx_parser.py`, parsed from GPX) and
  `SplitPlanOut` (`server/app/api/v1/schemas.py`, the read-side API shape
  already returned on `ActivityOut.split_plan`) all describe the same five
  fields: `split_type`/`split_value` (the rolling base — mirrors mobile's
  `SplitPreference`), `rolling_target_mps`, `custom_splits` (list of
  `(size, target|null)` pairs), `targets_as`. A saved config is **that same
  shape plus a name and an id** — nothing else needs designing. Reuse
  `SplitPlanOut` directly as the config's plan field on the API, and mirror
  its exact JSON in a new mobile `SplitConfig` model that wraps the existing
  `SplitPlan`.
- **Mobile's `SplitPlan` already has `toJson`/`fromJson`** (used today for
  secure-storage persistence). A `SplitConfig` (id, name, plan) can serialize
  by delegating to `SplitPlan.toJson()`/`fromJson()` for the plan portion —
  no duplication of the field-by-field logic.
- **The server's `SplitPlanOut` pydantic model has no validation beyond
  types** (it's a read/response model, built from trusted server-computed
  `SplitPlanData`). A **write** path (create/update a saved config from
  either web or mobile) is new: it needs the same validation `SplitPlan`
  enforces client-side (positive sizes/targets, `customSplits` capped at
  `maxCustomSplits` = 50, at least one of rolling/custom, `split_value > 0`)
  re-implemented server-side, since the server can never trust a client not
  to send garbage. Write this once as a shared pydantic model
  (`SplitPlanIn` or similar, `app/api/v1/schemas.py`) used by both the new
  endpoints and — do **not** change `ActivityOut`/upload parsing, which stay
  exactly as they are; this is a new, separate write path, not a
  modification of the existing GPX-derived one.
- **No existing table is a good template for "named, editable, user-owned,
  small JSON blob"** — `Tag` is the closest (user-scoped, unique name per
  user — see `app/models/tag.py`/`app/models/tag.py`'s uniqueness
  constraint) and is the right model to copy the per-user-unique-name
  pattern from, rather than `Activity` (which has no uniqueness on
  anything user-facing).
- **The web app's mutation contract is strict and already documented**:
  every mutating route requires `X-Requested-With: htmx` (checked
  server-side), forms must use `hx-post`/`hx-patch`/`hx-delete` — never a
  bare `<form method="post">` — and 4xx/error fragments need
  `htmx.config.responseHandling` to actually swap in (already global in
  `base.html`). The new editor page follows this exactly, same as
  `activity_detail.html`'s title/notes edit or `devices.html`'s revoke
  button — no new CSRF mechanism needed.
- **The web app talks to repositories directly, never to its own JSON API
  internally** (established rule, see CLAUDE.md's W2 notes). The new web
  editor page is its own route handler under `app/web/`, using the same
  repository/service layer the new `/api/v1/split-configs` routes use — not
  a client of the JSON API.
- **Mobile's `ApiClient`/`HttpApiClient` is the only file allowed to know
  URLs/wire format** (`core/api/http_api_client.dart`) — new sync calls
  (`listSplitConfigs`, `saveSplitConfig`, `deleteSplitConfig`) are added
  there and to the `ApiClient` interface, with DTOs in `core/api/dto/`
  following the existing `RunDto`/`ActivityDto` pattern, not ad-hoc parsing
  in the UI layer.
- **A device-token bearer request and a web session-cookie request already
  share the same `CurrentUser` dependency** on every existing
  `/api/v1/activities/*` route — the new `/api/v1/split-configs/*` routes
  use the same dependency, so both mobile (bearer) and a browser hitting the
  API directly (session cookie) work identically; no new auth path.
- **The activity list's pagination pattern (cursor-based) is overkill
  here.** A user will realistically have a handful to a few dozen named
  configs (bounded further by being manually curated), not thousands like
  activities. The list endpoint returns the full list, unpaginated, sorted
  by name — simpler on both ends, and mirrors how `/api/v1/me/devices` and
  `/devices` already return an unpaginated full list for a similarly small,
  user-curated collection.
- **Deleting a saved config must not touch any activity.** `Activity.split_plan`
  is a **snapshot** copied at upload time (see `app/models/activity.py`'s
  comment: "Set once at upload/import time, never backfilled or touched by
  reanalysis") — there is no foreign key from an activity to a saved config,
  and this plan does not add one. Deleting or editing a saved config never
  changes any past activity's recorded plan.

## 2. Data model

### 2.1 New table `split_configs` (migration, new `app/models/split_config.py`)

```python
class SplitConfig(Base):
    __tablename__ = "split_configs"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_split_configs_user_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Same JSON shape as Activity.split_plan / SplitPlanOut — split_type,
    # split_value, rolling_target_mps, custom_splits, targets_as.
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
```

Name max length matches `Tag.name`'s convention (200, validated server-side
same as activity title — see `app/validation.py`). `plan` is validated at the
API boundary (§2.2), not by a DB constraint — consistent with how
`Activity.client_summary`/`split_plan` are already untyped JSON columns
trusted only because the boundary validated them first.

### 2.2 Server-side plan validation (`app/api/v1/schemas.py` or a new
`app/split_configs/validation.py`)

A `validate_split_plan_payload()` function mirroring mobile's
`SplitPlan.fromJson` validation rules exactly (§1): `split_value > 0`,
`customSplits` length `<= 50`, every size `> 0`, every target `> 0` or null,
at least sane defaults when fields are omitted. Reject with 422 (the
existing `{"error": {"code","message"}}` contract) rather than silently
coercing — a malformed config must never save partially.

### 2.3 Repository (`app/repositories/split_configs.py`, protocol + SQLAlchemy
impl, same split as every other repository in `app/repositories/`)

- `list_for_user(user_id) -> list[SplitConfig]` (sorted by name)
- `get(user_id, config_id) -> SplitConfig | None`
- `get_by_name(user_id, name) -> SplitConfig | None` (for the overwrite-
  confirmation flow, §3.2/§4)
- `create(user_id, name, plan) -> SplitConfig`
- `update(config, name, plan) -> SplitConfig`
- `delete(config) -> None`

## 3. Server API (`app/api/v1/split_configs.py`, new router, `prefix="/api/v1/split-configs"`)

All routes behind `CurrentUser` (bearer or session cookie — same dependency
every other `/api/v1` route already uses).

| Method | Path | Body | Response | Notes |
|---|---|---|---|---|
| GET | `/api/v1/split-configs` | — | `{"configs": [SplitConfigOut, ...]}` | Full list, sorted by name (§1 — no pagination). |
| GET | `/api/v1/split-configs/{id}` | — | `SplitConfigOut` | 404 if not found/not owned. |
| POST | `/api/v1/split-configs` | `{"name": str, "plan": SplitPlanIn}` | `201 SplitConfigOut` | `409` with `{"error": {"code": "name_conflict", ...}}` if the name already exists for this user **and** the request didn't opt into overwrite (see next row) — the client (mobile or web) then re-asks the user and retries with the flag. |
| POST | `/api/v1/split-configs` (with `"overwrite": true`) | same + `"overwrite": true` | `200 SplitConfigOut` | Same endpoint; overwrites the existing same-named config in place (keeps its id, bumps `updated_at`) instead of erroring. Keeping this as one endpoint (not a separate PUT-by-name) avoids a lookup-by-name race between "check if it exists" and "create". |
| PATCH | `/api/v1/split-configs/{id}` | `{"name"?: str, "plan"?: SplitPlanIn}` | `200 SplitConfigOut` | Renaming to a name that collides with another existing config is a `409` the same way. |
| DELETE | `/api/v1/split-configs/{id}` | — | `204` | Hard delete — no soft-delete/undo, matching how activities/devices are already deleted outright elsewhere in this app. |

`SplitConfigOut`: `{id, name, plan: SplitPlanOut, created_at, updated_at}` —
reuses the existing `SplitPlanOut` pydantic model unchanged for the `plan`
field (§1). `SplitPlanIn`: same five fields as `SplitPlanOut`, as a request
model with the validation from §2.2 (pydantic `Field` constraints plus a
model validator for the cross-field custom-vs-rolling rule).

Rate limiting: reuse the existing `account_action_rate_limiter` (S6, 5/min
per IP) on the mutating routes (POST/PATCH/DELETE) — this is the same class
of "signed-in user changes account state" action already covered by it for
password/registration; no new limiter needed. GET routes are unlimited, same
as `/api/v1/activities`.

`openapi.json` gains this router — regenerate and commit per the existing
workflow (CLAUDE.md's "Server dev/test workflow", step 2).

## 4. Web editor (`app/web/split_configs.py`, `app/templates/split_configs.html` list + `split_config_edit.html` (or a fragment) for the editor)

- New nav entry (wherever `/devices`/`/settings` links already live in
  `base.html`) → `/split-configs`: a list of the user's saved configs (name,
  a one-line summary — "Rolling, every 1 km @ 5:00 /km" or "Custom, 6
  splits" — reusing the same summary-line logic already used for the mobile
  home-screen row, ported to Python or kept as a small shared description
  rather than re-derived ad hoc) with Edit/Delete (`hx-delete` +
  confirm, mirrors `devices.html`'s revoke button) and a "New config"
  button.
- Editor page/fragment: name field, then the **same sections as mobile's
  Splits screen** (§5.5 of docs/SPLIT-TARGETS-PLAN.md) reimplemented as
  server-rendered HTML + htmx — split type (km/mi/min), display units,
  targets-as (pace/speed), rolling vs custom, and for custom a row per split
  (size, target, delete) with add/apply-to-all. This is the single largest
  piece of new UI in this plan; treat it as its own work item (§6, item 3)
  and expect it to take real iteration, same as the mobile Splits screen did
  in #99.
- Saving: `hx-post`/`hx-patch` to the API-equivalent web routes (the web
  layer talks to the repository directly per the existing rule in §1, not
  to `/api/v1/split-configs` internally) with the same name-collision
  409-then-confirm flow as mobile (§3), rendered as an inline "Replace
  existing config?" confirmation instead of a native dialog.
- Validation errors render inline next to the offending field (same pattern
  as every other web form — `app/validation.py` + the existing
  4xx-fragment-swap CSP/htmx setup), not a bare error banner.
- No separate "picker" UI needed on the web side — the web app has no
  concept of "the current run's plan" to select into (it doesn't record
  runs), so the list page **is** the whole web-side feature.

## 5. Mobile

### 5.1 API layer

- New DTOs (`core/api/dto/split_config_dto.dart`): `SplitConfigDto` wrapping
  the existing plan JSON shape (delegates to `SplitPlan.toJson`/`fromJson`
  for the `plan` field, per §1).
- `ApiClient` interface (`core/api/api_client.dart`) gains:
  `Future<List<SplitConfigDto>> listSplitConfigs()`,
  `Future<SplitConfigDto> saveSplitConfig(String name, SplitPlan plan, {bool overwrite = false})`,
  `Future<void> deleteSplitConfig(String id)`.
- `HttpApiClient` implements them against §3's routes, mapping a 409 to a
  new `ApiNameConflictException` (extends the existing `ApiException`
  hierarchy in `core/api/api_exception.dart` or wherever it lives) so the UI
  can distinguish "needs a confirm-overwrite retry" from a generic
  rejection, same idea as the existing retryable/permanent split.

### 5.2 No new persisted state, no new controller responsibility

`SplitPlanController` (today's single "current plan" state) is **unchanged**
— it still holds exactly one `SplitPlan`, persisted locally, used for the
next run. Saved configs are **not** cached or persisted locally at all (O3)
— every open of the picker (§5.3) is a fresh `listSplitConfigs()` call, with
a loading/error state on the picker itself (same pattern as any other
network-backed screen — e.g. the activity list from #101).

### 5.3 "Load from saved" — Splits screen addition

New section on `SplitsScreen` (or a screen pushed from it — a simple
`ListView` of names + summary lines is enough, no need for a separate
Riverpod controller beyond a one-shot `FutureProvider`/`AsyncNotifier` that
re-fetches on open) offering:

- **Load**: tap a saved config → confirms if the current plan has unsaved-
  feeling differences is *not* needed (there's no "unsaved" concept — the
  current plan is always already persisted, per O5) → calls
  `splitPlanControllerProvider.notifier.select(config.plan)`, i.e. a plain
  local copy, same as any other field edit on this screen.
- Handle "signed out" / "no server configured" (the app already has this
  concept via `AuthStateController`, used by `RunSyncSection`) by disabling
  or hiding this section with an explanatory line, rather than showing an
  empty list or a raw network error.

### 5.4 "Save as..." — Splits screen addition

A button (e.g. in the app bar or bottom of the screen) that prompts for a
name (pre-filled with the currently-loaded config's name if §5.3 tracked
one **for this prompt only** — see O5, this is not persisted state, just a
convenience default for the text field) and calls `saveSplitConfig`:

- On success: confirmation snackbar/toast.
- On `ApiNameConflictException`: an inline confirm dialog ("A config named
  'X' already exists. Replace it?") → retry with `overwrite: true`.
- On any other failure (offline, auth failure, server error): surfaced the
  same way `RunSyncSection`/`SettingsScreen` already surface API errors
  (inline message, not a crash) — reuse existing error-formatting helpers
  rather than inventing new copy.
- Signed-out state: button disabled/hidden with an explanatory line, same
  as §5.3.

### 5.5 Out of scope for mobile in this issue

- Deleting/renaming a saved config from the phone (O7) — only the web editor
  manages the list beyond save/select.
- Offering "save this run's plan" from the run-finished screen (O4).
- Any live link between "plan in use" and "the saved config it came from"
  (O5).

## 6. Work items, in order (branch-per-item per CLAUDE.md's server workflow
for server pieces; mobile as its own branch/PR after the server pieces are
merged and pulled, since mobile depends on the live API)

1. **Server: data model + validation.** `SplitConfig` model, migration,
   repository, `SplitPlanIn`/`validate_split_plan_payload`. Tests: model
   round-trip, repository CRUD, validation edge cases (mirrors mobile's
   `SplitPlan.fromJson` test cases — negative/zero sizes, >50 custom
   splits, both rolling and custom present, neither present).
2. **Server: API routes.** `/api/v1/split-configs` (list/get/create-or-
   overwrite/patch/delete), rate limiting, `CurrentUser` auth, `openapi.json`
   regenerated. Tests: CRUD, per-user isolation (user A can't see/edit/
   delete user B's configs), name-collision 409 and overwrite flow,
   auth-required 401, validation-rejection 422. Snyk scan on `server/`.
   Local integration test in the real `deploy/standalone-tls` container per
   the documented server workflow before asking for sign-off.
3. **Server: web editor.** List page, create/edit form (the big one — treat
   as multiple commits: list+delete, then create, then edit, then the
   custom-splits row editor), following the existing web CSRF/htmx/
   validation conventions. Tests: route rendering, CSRF 403 without the
   htmx header, per-user isolation, name-collision confirm flow, admin/non-
   admin irrelevant here (not an admin feature) but the usual redirect-to-
   login-when-signed-out check. Manually verified in the real dev-stack
   container (a config created via curl in step 2 renders correctly; a
   config created in the web UI round-trips).
4. **Mobile: API layer.** DTOs, `ApiClient`/`HttpApiClient` methods,
   `ApiNameConflictException`. Tests: DTO round-trip, `HttpApiClient` against
   `MockClient` fixtures for list/save/save-conflict/delete.
5. **Mobile: Splits screen UI.** "Load from saved" list + "Save as..." flow,
   signed-out handling. Tests: widget/controller tests for load (calls
   `select()` with the right plan), save success, save-conflict-then-
   overwrite, error states.
6. **Docs**: this file's status line; CLAUDE.md status entry; note in
   docs/SPLIT-TARGETS-PLAN.md's "out of scope" section (§8, that plan's
   §8.4-ish "targets in a future library" carve-out is effectively #126) that
   it's now covered here.

## 7. Verification before sign-off

- Server: full check suite (`ruff`/`ruff format --check`/`mypy app`/
  `pytest`) clean, `openapi.json` diff reviewed, Snyk clean. Real-container
  verification per CLAUDE.md's documented workflow: create/list/rename/
  delete a config via `curl` (bearer token, mirroring how mobile will call
  it) against the real `deploy/standalone-tls` stack; confirm per-user
  isolation with two real accounts.
- Web: create/edit/delete a config through the actual browser UI against the
  real dev-stack container; confirm the name-collision confirm dialog; a
  malformed field shows an inline error, not a 500.
- Mobile: 100 % of the new mobile tests plus `flutter analyze` clean, Snyk
  clean. On-device (S23) per the project's habit for any UI change: create a
  config on web, load it on the phone's Splits screen and confirm it matches
  exactly (including a custom plan's per-split targets); edit it on the
  phone and save-as under the same name, confirm the overwrite prompt and
  that the change round-trips back to the web list; try with the phone
  offline (airplane mode) and confirm the picker/save UI degrade to a clear
  message rather than a crash or infinite spinner.

## 8. Open questions

None outstanding — resolved as O1–O9 in §0.
