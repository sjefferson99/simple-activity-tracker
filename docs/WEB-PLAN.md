# Simple Runner — Web app & sync: Plan & Handoff

Adds a self-hostable **web app + API** that the mobile app uploads finished runs to
(GPX file + the phone's post-run stats), stores them in a database, computes richer
post-run analysis, and shows everything in a browser. The mobile app gets
**sign-in, an offline-tolerant upload queue, and a "server insights" section** on the
run summary.

This is the implementation handoff for that work. It follows the same conventions as
[PLAN.md](PLAN.md) (the mobile plan): phases with acceptance criteria, status tracked in
[CLAUDE.md](../CLAUDE.md). Read PLAN.md §3 and §7 first — the architecture rules and
working agreements there still apply to every line of Dart touched here.

**Status: REVIEWED and approved for build (2026-09-02). Nothing below is built yet.**
The review decisions are recorded in §12; §13 holds the working agreements specific to
this work (notably: prompt before installing anything on the machine).

---

## 1. Decisions at a glance

| Decision | Choice | Why (short) — details in §3 |
|---|---|---|
| Repo shape | Monorepo: Flutter app **moves to `mobile/`**, server in `server/`, plus `deploy/`, `.github/`, `docs/` at the root | Standard shape once there are two apps; it's one mechanical `git mv` commit now, and it only gets more expensive later. Done first, in isolation (W0 step 0). |
| Server language / framework | **Python 3.12 + FastAPI** | OpenAPI generated from the code, not hand-maintained; Python owns the analysis maths (`gpxpy`, later numpy/pandas); small image; one language for API *and* UI. |
| Web UI | **Server-rendered Jinja2 + htmx**, with Leaflet (map) and uPlot (charts) **vendored** into `static/` | No Node build step in the container, works on an offline LAN (except map tiles), and the pages call the same JSON API for map/chart data so the API stays the single source of truth. |
| Database | **SQLite** via **SQLAlchemy 2.0** (sync) + **Alembic** migrations, behind a repository layer | Swap to Postgres by changing `SR_DATABASE_URL` and running the same migrations. Sync sessions keep SQLite simple and are fine at this scale. |
| GPX storage | Files on disk under `/data/gpx/…` behind a `BlobStore` interface | Keeps the DB small and backups trivial (one volume). An S3-style store is a second implementation later. |
| Auth | Email + password. **Web UI: session cookie. Mobile: long-lived named device token** (Bearer) minted by login, revocable from the web UI | Standard, no third party, per-device revocation. OIDC / pairing-code login are additive later. |
| Registration | **Closed by default**; first user bootstrapped from env vars; admins add everyone else from the web UI; `SR_ALLOW_REGISTRATION=true` opens self-signup | It's a personal self-hosted server; the operator decides who gets in. |
| Upload idempotency | Phone generates `client_run_id` (UUID v4) at run start; `POST /runs` is idempotent on `(user, client_run_id)` | A retried upload after a timeout can never create a duplicate run. |
| Analysis | Computed **synchronously at upload** by a versioned `Analyzer`, result stored as JSON with `analysis_version` | Simple now; the version column plus a `status` field on the API make async workers and re-analysis a non-breaking change. |
| Containers | Multi-stage Dockerfile, non-root, `/data` volume; **GHCR** image built for `linux/amd64` + `linux/arm64` (QEMU) | **amd64 behind Traefik is the primary deployment**; arm64 keeps Raspberry Pi 4/5 (64-bit OS) working for the homelab/open-source audience. |
| User management | Admin-only pages + API: create, reset password, disable/enable, promote, delete. Self-service: change password, manage devices | Closed registration needs *some* way to add people; keeping it in the same UI avoids a CLI-only admin path. |
| CI | GitHub Actions: Flutter analyze/test; server lint/type/test + OpenAPI drift check; container **built on every PR, pushed to GHCR on every merge to `main`** | Day-to-day development runs locally in Docker; anyone can `docker pull` the latest merged state from GHCR. |
| Raw GPX | Stored **byte-for-byte as uploaded**, downloadable from the run page | GPX 1.1 has no standard for embedding analysis, so the file stays pristine for other apps; all derived data lives in the DB. |
| Mobile local persistence | File-backed `RunStore` (one JSON sidecar per run next to its GPX) behind an interface | Same crash-safe write-temp-then-rename pattern the app already uses; no new DB dependency; sqflite/drift can replace it later without touching callers. |

---

## 2. Verified environment (checked 2026-09-02, Windows desktop)

| Item | State |
|---|---|
| Python | 3.12.10 on PATH (Microsoft Store build). Works, but prefer `uv`-managed interpreters (below) to avoid Store-Python path oddities. |
| `uv` | **Not installed** — install with `winget install --id=astral-sh.uv -e` (or `pip install uv`). Then `uv python install 3.12`. |
| Docker | Docker Desktop 29.7 (linux/x86_64 engine), **buildx v0.36 present** — multi-arch builds work locally with `docker buildx build --platform linux/amd64,linux/arm64`. |
| GitHub CLI | `gh` 2.96, logged in as `sjefferson99`; remote is `github.com/sjefferson99/simple-runner`. GHCR image will be `ghcr.io/sjefferson99/simple-runner-server`. |
| Node | 25.0 — **not needed** by this plan (the UI has no build step). |
| Existing CI | None (`.github/` does not exist). |
| Mac | Also available (see CLAUDE.md) — Docker there is optional; nothing here needs it. |

---

## 3. Design rationale (the "why" behind §1)

**Why not "all Flutter"?** Flutter web could render the UI, but it would mean a ~1 GB
Flutter SDK build stage in the image (painfully slow under arm64 QEMU), and a Dart
server has a thin ecosystem for the analysis we actually want (GPX parsing, elevation,
resampling, later stats). The API-first design means a Flutter web client *could* be
added later without server changes — nothing here precludes it.

**Why not a JS SPA?** It doubles the toolchain (Node build + Python runtime), needs
CORS/CSRF care across origins, and buys nothing at MVP size. htmx gives enough
interactivity (partial page swaps) and the dynamic bits (map, charts) are plain JS
calling the JSON API.

**Why a repository layer over SQLAlchemy?** SQLAlchemy already abstracts the engine, but
routes talking to ORM sessions directly make a future storage swap (or a caching
layer, or unit tests without a DB) invasive. A thin `RunRepository` /
`UserRepository` / `DeviceTokenRepository` protocol keeps route code storage-agnostic.
Don't over-build it: one SQLAlchemy implementation, no generic base class.

**Why store the phone's numbers *and* the server's?** The phone filters GPS fixes by
accuracy (see CLAUDE.md, outlier filtering), but GPX 1.1 carries no accuracy, so the
server can't reproduce that exactly and its distance will differ slightly. The phone's
summary is the run's **headline** numbers (what the runner saw); the server analysis
adds what the phone doesn't compute (elevation, best efforts, pace series). Both are
stored, both are labelled in the UI. Adding accuracy as a GPX `<extensions>` field is a
later improvement that would let the server converge on the phone's filtering.

**Why a device token rather than a JWT?** Tokens are opaque random strings, stored
hashed (SHA-256) server-side, looked up per request. That gives instant revocation and
a "devices" page for free. JWTs would only remove one indexed lookup.

---

## 4. Target repository layout

```
simple-runner/
  mobile/                                        # Flutter app (moved from the root in W0 step 0)
    lib/, test/, android/, ios/, pubspec.yaml, pubspec.lock, analysis_options.yaml
  docs/                                          # PLAN.md, WEB-PLAN.md (this), guides
  server/                                        # Python web app + API
    pyproject.toml                               # uv-managed; deps + tool config (ruff, mypy, pytest)
    uv.lock
    Dockerfile
    openapi.json                                 # exported spec, committed; CI fails if stale
    alembic.ini
    alembic/                                     # migrations
    app/
      main.py                                    # create_app(): routers, static, templates, lifespan
      config.py                                  # pydantic-settings, all SR_* env vars
      db.py                                      # engine/session factory from SR_DATABASE_URL
      models/                                    # SQLAlchemy ORM models
      repositories/                              # protocols + sqlalchemy implementations
      storage/                                   # BlobStore protocol + LocalFileBlobStore
      auth/                                      # password hashing, device tokens, session cookie, CurrentUser dependency
      analysis/                                  # Track model, GPX parser, Analyzer protocol, v1 analyzer
      api/v1/                                    # FastAPI routers: auth, me, runs; pydantic schemas
      web/                                       # Jinja2 page routes (login, runs, run detail, devices, settings)
      templates/
      static/                                    # vendored htmx, leaflet, uplot (+ their licences), app.css/js
      cli.py                                     # `simple-runner-server` entrypoint: migrate → bootstrap admin → uvicorn
    tests/
      conftest.py                                # app + tmp SQLite + tmp blob dir + client fixtures
      fixtures/sample_run.gpx                    # synthetic run with known answers
      ...
  deploy/
    docker-compose.yml                           # plain: app on :8000, ./data volume — local dev and the CI smoke test
    .env.example
    traefik/docker-compose.yml                   # PRIMARY target (amd64): app + Traefik labels, TLS via ACME, no published app port
    traefik/README.md                            # what to fill in (domain, email, network name)
    raspberry-pi.md                              # secondary/homelab: 64-bit OS, pull arm64 image, Caddy variant
  .github/workflows/
    flutter.yml
    server.yml
    container.yml
  .gitignore                                     # Flutter entries re-rooted under mobile/; add server/.venv, __pycache__, .pytest_cache, .mypy_cache, .ruff_cache, /data/, deploy/data/
```

The restructure (W0 step 0) is: `git mv` of `lib test android ios pubspec.yaml pubspec.lock
analysis_options.yaml` into `mobile/` (the untracked `build/`, `.dart_tool/`, `*.iml` just
get deleted and regenerate), then update every path that mentions them: `.gitignore`
(`/build/` → `/mobile/build/` etc.), CLAUDE.md commands (`cd mobile` first), PLAN.md §3
tree, `docs/deploy-guide.md` (one extra `cd mobile` after unzipping), README. Verify with
`cd mobile && flutter pub get && flutter analyze && flutter test` and one `flutter run` on
the emulator before touching anything else. Ask before committing, as always.

---

## 5. Server design

### 5.1 Data model (Alembic migration 0001)

```
users            id UUID pk · email unique (lowercased) · password_hash · display_name
                 · is_admin bool · disabled_at nullable
                 · sessions_invalidated_at            -- bumped on password change / disable; older cookies die
                 · created_at
device_tokens    id UUID pk · user_id fk · name · token_hash unique (sha256 of secret)
                 · created_at · last_used_at · revoked_at nullable
runs             id UUID pk · user_id fk · client_run_id UUID · started_at (UTC) · ended_at (UTC)
                 · title nullable · notes nullable
                 · client_summary JSON              -- phone's numbers, stored verbatim (schema §5.3)
                 · gpx_blob_key · gpx_sha256 · gpx_bytes
                 · source_platform · source_app_version
                 · created_at · updated_at
                 · UNIQUE (user_id, client_run_id)
                 · INDEX (user_id, started_at DESC)
run_analyses     run_id pk/fk · analysis_version int · status enum(pending|done|failed)
                 · result JSON nullable · error nullable · computed_at
```

Timestamps are stored as UTC ISO-8601 strings in SQLite (SQLAlchemy `DateTime(timezone=True)`;
add a small `TZDateTime` type decorator so naive values can never sneak in — SQLite
silently accepts them otherwise).

### 5.2 API surface (`/api/v1`, OpenAPI at `/api/openapi.json`, docs at `/api/docs`)

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /healthz` | none | `{status, version, db: "ok"}` — used by Docker HEALTHCHECK and the CI smoke test |
| `POST /api/v1/auth/login` | none | `{email, password, device_name}` → `{token, device: {...}, user: {...}}`. Token shown **once**. Rate-limited (in-memory, per IP + per email; 10/min is plenty). |
| `POST /api/v1/auth/logout` | bearer | Revokes the presenting token |
| `GET /api/v1/me` | any | Current user |
| `GET /api/v1/me/devices` · `DELETE /api/v1/me/devices/{id}` | any | List / revoke device tokens |
| `GET /api/v1/runs?limit=&cursor=` | any | Newest-first, cursor-paginated (`started_at,id` keyset). List items carry the headline summary only. |
| `POST /api/v1/runs` | any | **multipart/form-data**: `summary` (JSON part, schema §5.3) + `gpx` (file). Idempotent: existing `(user, client_run_id)` → `200` with the existing run, else `201`. Validates: size ≤ `SR_MAX_GPX_BYTES` (default 20 MB), parses as GPX with ≥1 trackpoint, `summary.client_run_id` present. Stores blob → row → runs analyzer → returns full run. |
| `GET /api/v1/runs/{id}` | any | Run + `client_summary` + `analysis` (status + result) |
| `PATCH /api/v1/runs/{id}` | any | `{title?, notes?}` — the only client-editable fields for now |
| `DELETE /api/v1/runs/{id}` | any | Deletes row, analysis and blob |
| `GET /api/v1/runs/{id}/gpx` | any | The **original bytes exactly as uploaded** (never re-serialised), `application/gpx+xml`, `Content-Disposition: attachment; filename=<started_at>.gpx`. This is what the web UI's Download button hits. |
| `GET /api/v1/runs/{id}/analysis` | any | Analysis only. Returns `{status: "pending"}` with `202` if not done — always `done` in MVP, but clients must handle `pending` so async analysis later is non-breaking. |
| `GET /api/v1/runs/{id}/track?max_points=` | any | Downsampled `{segments: [[{lat, lon, ele, t}], …]}` for the map; default 2000 points, uniform stride |

| `PUT /api/v1/me/password` | any | `{current_password, new_password}`; bumps `sessions_invalidated_at` and revokes every device token except the presenting one |
| `GET /api/v1/admin/users` | admin | List users with run counts, last activity, disabled/admin flags |
| `POST /api/v1/admin/users` | admin | `{email, display_name, password, is_admin}` — create a user (the admin hands the password over out of band; the user changes it in Settings) |
| `PATCH /api/v1/admin/users/{id}` | admin | `{display_name?, is_admin?, disabled?}`. Disabling revokes all device tokens and invalidates sessions. Cannot demote or disable **yourself**, and cannot remove the last enabled admin. |
| `POST /api/v1/admin/users/{id}/password` | admin | Set a new password for the user (reset). Same session/token invalidation as above. |
| `DELETE /api/v1/admin/users/{id}` | admin | Deletes the user **and all their runs, analyses and GPX blobs**. Same self/last-admin guards. |

"any" = bearer token **or** web session cookie; one `CurrentUser` dependency resolves
both and rejects disabled users on every request. "admin" = `CurrentUser` with
`is_admin` (a non-admin gets `404`, so the admin routes are invisible). All run routes
are scoped to the current user (a run belonging to someone else is a `404`, never a
`403`, to avoid leaking IDs). Errors use one JSON shape:
`{"error": {"code": "…", "message": "…"}}`.

**There are no JWTs anywhere.** Web sessions are signed cookies carrying
`(user_id, issued_at)`; phone logins are opaque device tokens looked up by hash. Both are
invalidated by the user's `sessions_invalidated_at` / a token's `revoked_at`, which is
what makes "disable user" and "reset password" take effect immediately.

### 5.3 `RunSummary` schema (the phone's numbers — mirrors `LiveMetrics`)

```json
{
  "client_run_id": "uuid",
  "started_at": "2026-09-02T07:15:03Z",
  "ended_at":   "2026-09-02T07:47:19Z",
  "moving_seconds": 1889.4,
  "distance_meters": 5012.3,
  "avg_speed_mps": 2.65,
  "splits": [{"index": 1, "duration_seconds": 301.2, "avg_speed_mps": 3.32}],
  "source": {"platform": "android", "app_version": "1.0.0+1"}
}
```

Pydantic model with `extra="forbid"` and value bounds (non-negative, finite). `started_at`
and `ended_at` are not currently in `LiveMetrics` — the mobile side records them in the
controller (§6.3).

### 5.4 Analysis pipeline (`app/analysis/`)

- `track.py` — pure dataclasses `Track → Segment → Point(lat, lon, ele, time)`. Nothing
  outside `analysis/` imports `gpxpy` (same discipline as `LocationSample` vs geolocator in
  the app).
- `gpx_parser.py` — `gpxpy` → `Track`. Wrap parsing in a size cap and a try/except that
  maps to a `400`. (`gpxpy` uses the stdlib XML parser; the size cap is the DoS guard.)
- `analyzer.py` — `class Analyzer(Protocol): version: int; def analyze(self, track: Track) -> AnalysisResult`.
- `v1.py` — **`ANALYSIS_VERSION = 1`**, computes:
  - distance (haversine, with a per-step implied-speed sanity filter: drop a step implying
    > 12.5 m/s, documented as v1 behaviour), elapsed (wall clock) and moving time (steps
    with speed ≥ 0.5 m/s), average moving speed
  - elevation gain / loss / min / max (with 3-point smoothing on `ele` before summing —
    raw GPS elevation is noisy and inflates gain badly)
  - 1 km splits with `duration_seconds`, `avg_speed_mps`, `elevation_delta_m`
  - best efforts: fastest 1 km, 5 km, 10 km windows (only those ≤ total distance)
  - `series`: ≤ 300 evenly spaced samples of `{t_s, dist_m, speed_mps, ele_m}` for charts
  - `bounds` (bbox), `point_count`, `segment_count`
- Re-analysis is a CLI command (`simple-runner-server reanalyze [--all|--run ID]`) that
  reruns the current analyzer where `analysis_version < current` — the extensibility hook
  for algorithm changes.

### 5.5 Configuration (`pydantic-settings`, prefix `SR_`)

| Var | Default | Notes |
|---|---|---|
| `SR_DATABASE_URL` | `sqlite:////data/simple_runner.db` | Any SQLAlchemy URL. SQLite gets `PRAGMA journal_mode=WAL` and `foreign_keys=ON` on connect. |
| `SR_DATA_DIR` | `/data` | Blob root (`/data/gpx/<user_id>/<run_id>.gpx`) |
| `SR_SECRET_KEY` | **required** | Signs session cookies. Startup fails loudly if unset. |
| `SR_ADMIN_EMAIL` / `SR_ADMIN_PASSWORD` | unset | If set and `users` is empty, create this admin at startup (bootstrap). |
| `SR_ALLOW_REGISTRATION` | `false` | Enables `/register` page + `POST /api/v1/auth/register` |
| `SR_MAX_GPX_BYTES` | `20971520` | Upload cap |
| `SR_SECURE_COOKIES` | `true` | Set `false` only for plain-http LAN testing |
| `SR_TRUSTED_PROXIES` | `""` | Comma-separated IPs/CIDRs allowed to set `X-Forwarded-For` / `X-Forwarded-Proto`. Passed to uvicorn's `--forwarded-allow-ips`. **Must be set when behind Traefik/Caddy** (the Docker network range, e.g. `172.16.0.0/12`), or the app sees every request as `http` from the proxy's IP — `Secure` cookies then never get set and the login rate limit keys on one address. |
| `SR_LOG_LEVEL` | `info` | |

### 5.6 Security baseline

- Passwords: argon2id via `pwdlib[argon2]`. Device tokens: 32 random bytes, base64url,
  stored as SHA-256; compared with `hmac.compare_digest`.
- Session cookie: signed (`itsdangerous`), `HttpOnly`, `SameSite=Lax`, `Secure` per config.
  Every state-changing **web** request (htmx form posts) must carry an `X-Requested-With: htmx`
  header (set globally via `hx-headers` on `<body>`); the server rejects cookie-authenticated
  mutations without it. Bearer requests are exempt (no cookie, no CSRF).
- Login rate limit; generic "invalid credentials" message; no user enumeration on register.
- Uploads: size cap before reading the body, GPX parse errors → `400`, blob keys are
  server-generated (never from the filename).
- Container runs as non-root; only `/data` is writable; no secrets baked into the image.
- **TLS is out of scope for the container** — terminate HTTPS at a reverse proxy. The
  primary deployment is **amd64 + Traefik** (`deploy/traefik/` has a working compose with
  router/TLS labels); `deploy/raspberry-pi.md` shows the same with Caddy as the lighter
  homelab option. The container only ever listens on plain `:8000` and trusts forwarded
  headers from `SR_TRUSTED_PROXIES` only.
- **User administration** lives in the web UI (§8 W2, `/admin/users`) and the `admin`
  API routes (§5.2): create, reset password, disable/enable, promote/demote, delete. The
  first admin comes from the env bootstrap; there is no way to become admin except being
  promoted by one. Guards: an admin can't disable, demote or delete themself, and the last
  enabled admin can't be removed — so the instance can never lock everyone out.
- Snyk: `snyk_code_scan` on the new Python and Dart, `snyk_container_scan` on the built
  image; fix and rescan until clean (global policy).

---

## 6. Mobile app changes

### 6.1 New packages

`http` (client), `flutter_secure_storage` (token + server URL), `connectivity_plus`
(retry trigger), `uuid` (client_run_id), `package_info_plus` (app version for
`summary.source`). Latest stable of each via `flutter pub add`.

### 6.2 New modules (feature-first, per PLAN.md §3)

```
lib/
  core/api/
    api_client.dart              # abstract ApiClient: login/logout/me/uploadRun/getAnalysis; typed ApiException hierarchy
    http_api_client.dart         # implementation over package:http; the ONLY file that knows URLs/JSON wire format
    dto/                         # RunSummaryDto, RunDto, AnalysisDto, DeviceDto — fromJson/toJson, tested against fixtures
  core/sync/
    run_store.dart               # abstract RunStore: save/load/list RunRecord, updateSyncStatus
    file_run_store.dart          # JSON sidecar per run: <docs>/runs/run_<stamp>.json (atomic temp+rename)
    sync_service.dart            # queue + retry policy; exposes Stream<SyncStatus> per run
    connectivity.dart            # thin wrapper over connectivity_plus behind an interface (fakeable)
  core/auth/
    auth_service.dart            # holds credentials (secure storage), server URL, signed-in state
  domain/models/
    run_record.dart              # pure Dart: RunRecord(clientRunId, startedAt, endedAt, gpxPath, summary, syncStatus)
    run_summary.dart             # pure Dart: built from LiveMetrics + timestamps; toJson matches §5.3 exactly
    sync_status.dart             # sealed: pending | uploading | uploaded(serverRunId) | failed(error, attempts, retryable)
  features/settings/
    settings_screen.dart         # server URL, sign in/out (email, password, device name), sync queue summary + "Retry now"
  features/live_run/
    (summary view)               # adds: sync status line, "Insights" section fed by analysis, opens settings if signed out
```

Rules: `domain/` stays pure Dart. `core/api` is the only place that knows the wire
format. Widgets never call `ApiClient` directly — they go through Riverpod providers
over `SyncService` and `AuthService`.

### 6.3 Behaviour

- **At `start()`**: generate `clientRunId`, record `startedAt` (UTC). At `stop()`: record
  `endedAt`, build `RunSummary` from `LiveMetrics`, write the `RunRecord` sidecar
  (`syncStatus: pending`) **before** the state switches to Finished, then hand it to
  `SyncService`. This mirrors the existing "export after the state switch" pattern — a
  slow or failed upload must never delay the summary screen.
- **SyncService**: single-flight worker over the `pending`/`failed(retryable)` records,
  oldest first. Triggers: run finished, app resumed (`WidgetsBindingObserver`), connectivity
  regained, user taps Retry. In-session backoff between automatic attempts:
  30 s → 1 m → 2 m → 5 m → 10 m (cap). Per-record attempt count persisted.
- **Error classes**: network / timeout / 5xx / 429 → retryable. `401` → mark signed-out,
  keep the queue intact, summary shows "Sign in to upload". Other 4xx → `failed(retryable: false)`
  with the server's message; shown in Settings for manual retry after the user fixes whatever
  is wrong (e.g. server rejected the file). Idempotency on `client_run_id` means a timed-out
  upload that actually landed just returns `200` next time — no duplicate handling on the phone.
- **After upload**: fetch analysis; if `done`, cache `result` on the `RunRecord` and render the
  Insights section (elevation gain/loss, best 1 km / 5 km, server distance & moving time
  labelled "server"). If `pending`, show "Analysis pending" — not retried in MVP.
- **Not signed in / no server URL**: everything works exactly as today; runs queue with
  `pending` and a one-line hint links to Settings.
- **Cleartext HTTP**: a Pi on the LAN will almost certainly be `http://` at first. Android
  blocks cleartext by default → add `android:usesCleartextTraffic="true"` for MVP and
  show an "unencrypted connection" warning in Settings when the URL is `http://`.
  iOS: `NSAppTransportSecurity → NSAllowsLocalNetworking = true` covers LAN addresses.
  The production expectation is a reverse proxy with a real certificate in front of the
  container (§5.6); the phone then just gets an `https://` URL and the warning goes away.
- **Deletion is device-scoped**: deleting a run in the web UI removes it from the server
  only; the phone keeps its GPX and sidecar. There is no delete on the phone in MVP. A
  later "delete everywhere" option would need a tombstone/sync-down endpoint — not now.
- Background upload (`workmanager`) is **not** MVP; the foreground triggers above are enough.

---

## 7. Containers & CI

### 7.1 Dockerfile (`server/Dockerfile`)

- Stage 1 `python:3.12-slim` + `uv` (copied from the `ghcr.io/astral-sh/uv` image, pinned):
  `uv sync --frozen --no-dev --no-install-project`, then copy source and `uv sync --frozen --no-dev`.
- Stage 2 `python:3.12-slim`: create user `app` (uid 1000), copy `/app` from stage 1,
  `ENV PATH=/app/.venv/bin:$PATH`, `VOLUME /data`, `EXPOSE 8000`,
  `HEALTHCHECK` via a one-line `python -c "urllib.request.urlopen('http://127.0.0.1:8000/healthz')"`
  (slim has no curl), `CMD ["simple-runner-server", "run"]` → `alembic upgrade head` →
  admin bootstrap → uvicorn with `--proxy-headers --forwarded-allow-ips=$SR_TRUSTED_PROXIES`
  (so scheme/client IP are right behind Traefik, and ignored from anyone else).
- Keep dependencies to packages with **aarch64 manylinux wheels** (fastapi, uvicorn,
  sqlalchemy, pydantic, argon2-cffi, gpxpy all qualify) so the arm64 build under QEMU
  never compiles C — otherwise the PR build takes 30+ minutes.
- `deploy/docker-compose.yml`: one service, `./data:/data`, `8000:8000`, `env_file: .env`
  (`.env.example` committed with `SR_SECRET_KEY=change-me` and the admin vars).

### 7.2 Workflows

- **`flutter.yml`** — on PR and push to `main` touching `mobile/**`: `subosito/flutter-action`
  pinned to the repo's Flutter (3.47.x, `channel: stable`), then in `working-directory: mobile`:
  `flutter pub get`, `flutter analyze`, `flutter test`.
- **`server.yml`** — on PR and push touching `server/**`: `astral-sh/setup-uv`, `uv sync`,
  `ruff check` + `ruff format --check`, `mypy app`, `pytest`, then
  `uv run python -m app.openapi_export | diff - openapi.json` (fails if the committed spec is stale).
- **`container.yml`** — on PR touching `server/**` or `deploy/**`: `docker/setup-qemu-action`,
  `docker/setup-buildx-action`, `docker/build-push-action` with
  `platforms: linux/amd64,linux/arm64`, `push: false`, GHA cache. Then run the amd64 image and
  hit `/healthz` as a smoke test. **On every push to `main` (i.e. each merged PR)**: same build
  with `push: true`, tags `latest` + `sha-<short>`, so a Pi can `docker compose pull` the
  newest merged state. `permissions: packages: write`. Image:
  `ghcr.io/sjefferson99/simple-runner-server`. (Semver tags on `v*` can be added later;
  not needed for MVP.)

---

## 8. Phases

Each phase ends with: analyze/tests clean for whatever it touched, Snyk clean on new code,
CLAUDE.md "Current status" updated, and **a commit proposal — ask before committing** (CLAUDE.md rule).

### W0 — Restructure, server skeleton, container, CI (no product features)

0. **Restructure** the Flutter app into `mobile/` as described under §4, verify analyze/test/run, propose it as its own commit before any server files exist.
1. Install `uv` (prompt first — §13); `server/pyproject.toml` (deps per §5.5/§7.1, plus `ruff`, `mypy --strict` on `app/`, `pytest`); `uv.lock`.
2. `create_app()` with `/healthz`, `config.py`, `db.py` (engine from URL, SQLite pragmas), Alembic wired with an empty baseline, `cli.py` with a `run` command.
3. Dockerfile + compose + `.env.example`; `docker compose up` serves `/healthz` from an empty `/data`.
4. Three workflows (§7.2). Open a throwaway PR to prove the container job builds **both** architectures and the smoke test passes; then merge.
5. `.gitignore` additions; `README.md` gains a "Server" section pointing here.

**Acceptance:** CI green on a PR with all three workflows; `docker buildx build --platform linux/amd64,linux/arm64` succeeds locally; `snyk_container_scan` on the amd64 image clean, or only base-image findings with no fix available (record them in CLAUDE.md).

### W1 — Data, auth, runs API, analysis

1. Migration 0001 (§5.1); ORM models; repositories (protocols + SQLAlchemy impls); `LocalFileBlobStore`.
2. Auth module (§5.6): hashing, device tokens, session cookie codec with `issued_at` vs `sessions_invalidated_at` check, `CurrentUser` / `CurrentAdmin` dependencies (bearer **or** cookie; disabled users rejected), login rate limiter, admin bootstrap, the `admin/users` routes with their self/last-admin guards.
3. `analysis/`: `Track`, parser, `Analyzer` protocol, v1 (§5.4) with unit tests against `fixtures/sample_run.gpx`. Generate the fixture with a small script committed under `tests/fixtures/`: 3 km at a constant 5:00 min/km with ±3 m jitter, a 90 s gap between two segments, a gentle 20 m climb — so expected distance, moving time, splits and elevation gain are known to within tight tolerances.
4. Routers per §5.2 with Pydantic schemas; multipart upload; idempotency; scoping; error shape.
5. `app/openapi_export.py`; commit `openapi.json`.
6. Tests (httpx `TestClient`, tmp SQLite, tmp blob dir): login/logout/revoke; upload → 201, re-upload same `client_run_id` → 200 same id; other user's run → 404; oversize → 413; junk GPX → 400; PATCH/DELETE; pagination cursor; analysis present after upload.

**Acceptance:** all tests green; `mypy --strict` clean; `openapi.json` committed and CI drift check passing; a manual `curl` walkthrough against `docker compose up` recorded in the PR description.

### W2 — Web UI

1. Base layout (dark theme to match the app), htmx + vendored assets with pinned versions and licence files.
2. Pages: `/login`, `/logout`, `/` (run list, newest first, empty state with sign-in-from-phone instructions), `/runs/{id}` (headline stats from the phone's summary; server analysis card; Leaflet map fed by `/track`; splits table; uPlot elevation + pace chart fed by `analysis.series`; edit title/notes via PATCH; download GPX; delete with confirm), `/devices` (list/revoke), `/settings` (change password), `/register` when enabled, and for admins **`/admin/users`** (table of users; create form; per-row disable/enable, promote/demote, reset password, delete with a confirm that spells out the run count being removed). Admin links only render for admins; the routes themselves return `404` to everyone else.
3. CSRF header rule enforced (§5.6); cookie flags per config.
4. Tests: page routes render for a signed-in user, redirect when signed out, mutation without the htmx header → 403; admin pages `404` for non-admins; self-demote / last-admin guards; disabling a user kills their existing session cookie and device token on the very next request.

**Acceptance:** upload a real GPX from the phone (copy from `Downloads/SimpleRunner/`) via `curl`, open it in the browser: map draws the route, splits match the phone's, elevation chart renders. Works on a Pi over plain http on the LAN.

### W3 — Mobile sync

1. Packages per §6.1; `RunSummary`, `RunRecord`, `SyncStatus` (pure Dart, tested; `RunSummary.toJson` round-trips against a JSON fixture copied from `server/openapi.json` examples).
2. `ApiClient` + `HttpApiClient` + DTOs; `FakeApiClient` for tests.
3. `FileRunStore`, `SyncService` with the retry policy (§6.3), tested with `FakeApiClient` + fake connectivity + fake clock.
4. `AuthService` + Settings screen; Android cleartext + iOS ATS entries.
5. `LiveRunController` changes (client id, timestamps, sidecar before Finished, enqueue); summary screen sync line + Insights section.
6. Wire `WidgetsBindingObserver` resume and connectivity triggers.

**Acceptance:** `flutter analyze`/`flutter test` clean. On the physical Samsung: (a) finish a run with Wi-Fi on → appears in the web UI within seconds, Insights show on the phone; (b) airplane mode → run finishes normally, shows "Queued"; re-enable → uploads without user action; (c) revoke the device in the web UI → next upload shows "Sign in to upload", queue intact, sign in again → uploads; (d) kill the app mid-upload → no duplicate on the server.

### W4 — Deployment guides (amd64 + Traefik primary, Raspberry Pi secondary)

1. `deploy/traefik/docker-compose.yml` + README: Traefik v3 with the Docker provider, ACME (Let's Encrypt) resolver, `websecure` entrypoint, HTTP→HTTPS redirect; the app service with `traefik.http.routers.simple-runner.rule=Host(...)`, `tls.certresolver`, `services...loadbalancer.server.port=8000`, **no published port**, `SR_TRUSTED_PROXIES` set to the compose network, `SR_SECURE_COOKIES=true`. Include the case where Traefik already exists on the host (external network, no second Traefik).
2. `deploy/raspberry-pi.md`: 64-bit OS requirement, install Docker, `docker compose pull && up -d` (pulls the arm64 image automatically), bootstrap admin env, back up `/data`, Caddy variant for TLS with a LAN or DuckDNS-style hostname.
3. Verify the Traefik compose end-to-end on the amd64 target: HTTPS reachable, `Secure` cookie set, phone uploads over `https://` with no cleartext warning. Verify on a Pi only if one is to hand.

---

## 9. Testing strategy (summary)

| Layer | How |
|---|---|
| Server analysis | Pure unit tests on `Track` inputs; fixture GPX with known answers; property checks (distance ≥ 0, splits sum ≈ distance, gain ≥ 0). |
| Server API | `TestClient` against tmp SQLite + tmp blob dir per test; auth matrix; idempotency; scoping; limits. |
| Server UI | Route render/redirect tests; CSRF rule. No browser automation for MVP. |
| OpenAPI | Drift check in CI; the committed spec is the mobile side's contract. |
| Mobile | Pure Dart tests for models and `SyncService` (fake API, fake connectivity, fake clock); DTO tests against JSON fixtures; the existing 29 tests stay green. |
| Container | Multi-arch build + `/healthz` smoke in CI; Snyk container scan locally. |
| End-to-end | Manual, scripted in the §8 acceptance lists, on the physical phone. |

---

## 10. Extension points (deliberately cheap to change later)

- **Database**: `SR_DATABASE_URL` + Alembic + repositories → Postgres is config + `psycopg` in the deps.
- **Blob store**: second `BlobStore` implementation (S3/MinIO) selected by config.
- **Analysis**: bump `ANALYSIS_VERSION`, run `reanalyze`; async workers slot behind the existing `status` field.
- **Auth**: OIDC or QR pairing-code login are additional routes minting the same device tokens.
- **API**: `/api/v1` prefix; additive fields only within v1.
- **Mobile**: `RunStore` → sqflite when run history arrives; `ApiClient` → generated client if the API grows large; `SyncService` → `workmanager` for background upload.
- **Web UI**: a Flutter web or SPA client can replace the Jinja pages without any API change.

---

## 11. Out of scope for MVP

Social/sharing, multi-user run visibility, HR/cadence, GPX `<extensions>` (accuracy), map
tiles offline, push notifications, background upload, password reset by **email** (admins
reset passwords by hand instead), user self-deletion, per-user storage quotas, HTTPS inside
the container, Postgres actually being exercised.

---

## 12. Review decisions (2026-09-02)

| # | Question | Decision |
|---|---|---|
| 1 | Repo layout | **Move the Flutter app to `mobile/`** now (W0 step 0). Owner's steer was "whatever is logical; restructure if it's not a lot of work and is best practice" — it is both. |
| 2 | Registration | **Closed by default**, first admin bootstrapped from `SR_ADMIN_EMAIL`/`SR_ADMIN_PASSWORD`. |
| 3 | Mobile sign-in | **Email + password** in the app, minting a named device token. Pairing code later if wanted. |
| 4 | Cleartext HTTP | **Allowed with an in-app warning.** Production expectation: a certificated reverse proxy in front of the container. |
| 5 | Container publishing | **Build on every PR (no push); push to GHCR on every merge to `main`.** Development happens locally in Docker; GHCR mirrors merged `main` for anyone to pull. |
| 6 | Headline numbers | **Phone summary is the headline; server analysis is labelled extra.** Raw GPX is downloadable from the web UI, byte-for-byte as uploaded (no standard exists for embedding analysis in GPX, so we don't try). |
| 7 | Deletion | **Scoped to the device you're on** — server delete never touches the phone. "Delete everywhere" is a later option. |
| 8 | Fixture data | **Synthetic GPX only.** The owner can supply a short real walk GPX later if a real-world fixture becomes useful. |
| 9 | Deployment target | **amd64 host behind Traefik is the primary target** and gets the worked compose example. Raspberry Pi (arm64, Caddy) stays supported with a brief guide for the homelab/open-source audience. |
| 10 | User management | **In the web UI, admin-only** (create, reset password, disable, promote, delete) plus self-service password change and device revocation. No email-based flows. No JWTs — signed session cookies and opaque device tokens, both revocable server-side. |

---

## 13. Working agreements specific to this work

- Everything in PLAN.md §7 and CLAUDE.md still applies: analyze/tests clean, Snyk clean on
  new code, **ask before every commit**, stay on `main` unless told otherwise (PRs are
  used for CI verification; branch for those and say so).
- **Prompt before installing anything on the machine**, every time (`uv`, Docker
  components, a Flutter package that needs native setup, anything via `winget`/`pip`
  outside a venv). The owner has approved installs in principle but wants to see each one.
- **Keep installs contained.** Python dependencies live in `server/.venv` managed by `uv`
  — never `pip install` into the global/Store Python. The only machine-wide additions this
  plan needs are `uv` itself and nothing else; Docker and `gh` are already present.
- Server work is verified locally with `docker compose up` in `deploy/` before a PR is
  opened; CI is the second check, not the first.
- Keep this document current: when a step's reality differs from the plan (a package that
  didn't work, a design change), edit the relevant section here and record the "why" in
  CLAUDE.md's status, the way PLAN.md's phases were tracked.
