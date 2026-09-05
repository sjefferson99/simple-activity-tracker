# Server — production-readiness review & action plan

**Scope:** the FastAPI web app + API in `server/` and the deployment files in `deploy/`,
reviewed 2026-09-03 at the MVP milestone (W0–W4 done, PR #7 merged). Goal: a list of
concrete, independently deliverable actions that take the server from "works end-to-end
on a LAN" to "safe to run on the public internet behind a TLS-terminating reverse proxy."

**How to use this document (for the implementing agent):**

- Read [WEB-PLAN.md](WEB-PLAN.md) §5 (server design), §12–13 (decisions and working
  agreements) and the "Current status" section of [../CLAUDE.md](../CLAUDE.md) first. The
  working agreements still apply: `ruff`, `mypy --strict` and `pytest` clean, `openapi.json`
  regenerated when the API changes, Snyk code scan clean on new code, **prompt before
  installing anything on the machine or adding a dependency**, and **ask before every
  `git commit`**.
- Items are grouped into workstreams and ordered by priority within each. **P0 items are
  release blockers** — do those first, in order. P1 next. P2/P3 can be picked up in any
  order. Each item has a `Do` and a `Verify` so it can be delivered and closed on its own.
- Every item that changes behaviour gets a test. Several P0 items were **confirmed by
  running a probe against the current code** (marked "Verified during review") — the
  reproduction steps double as the regression test.
- Update the checklist in §7 and CLAUDE.md's status section as items land.

Review tooling: Snyk code scan on `server/app` is clean (0 issues). Snyk dependency
(SCA) scan **could not be run in the review environment** (the Snyk CLI couldn't find
`uv` on PATH and its pip resolver failed on an exported requirements file) — D5 below
makes dependency scanning a CI job so this doesn't depend on a workstation setup.
Locked versions at review time: fastapi 0.141.1, starlette 1.6.0, uvicorn 0.52.4,
sqlalchemy 2.0.52, python-multipart 0.0.32, jinja2 3.1.6, itsdangerous 2.2.0, pwdlib 0.3.1
(argon2-cffi 25.1.0), gpxpy 1.6.2.

---

## 1. Summary of what's already good (don't undo these)

- argon2id passwords; opaque high-entropy device tokens stored as SHA-256; signed,
  `HttpOnly`, `SameSite=Lax`, `Secure`-by-config session cookies; `sessions_invalidated_at`
  makes disable/reset take effect on the next request.
- Every activity route is scoped to the current user and 404s rather than 403s; admin
  routes 404 for non-admins; self/last-admin guards on both API and web.
- CSRF: cookie-authenticated mutations require the `X-Requested-With: htmx` header;
  bearer requests can't hit web routes.
- Upload cap enforced before parsing; blob keys are server-generated; original GPX bytes
  are stored and returned verbatim.
- Jinja autoescape on (Starlette's `Jinja2Templates` default); `tojson` used for the two
  values injected into inline scripts.
- Non-root container, `/data` the only writable path, no secrets in the image, multi-arch
  image, healthcheck, migrations at startup, `TZDateTime` refusing naive datetimes.
- Config is lazy (`get_settings()`/`get_engine()`), so tests isolate cleanly.

---

## 2. Workstream S — Security (P0 unless marked)

### S1 (P0) — `SR_SECRET_KEY` is not actually required; an empty key signs cookies

**Verified during review.** `Settings.secret_key` defaults to `None` and every caller does
`get_settings().secret_key or ""`. With the variable unset, `create_session_cookie("", uid)`
produces a cookie that `read_session_cookie("", ...)` accepts — anyone who knows (or
guesses) a user id can forge an admin session. WEB-PLAN §5.5 says "startup fails loudly if
unset"; nothing implements that. `.env.example` ships `SR_SECRET_KEY=change-me`, which
would also be accepted.

- Where: `server/app/config.py`, `server/app/cli.py` (`run`), `server/app/auth/sessions.py`,
  `server/app/web/login.py`, `server/app/web/deps.py`, `server/app/auth/current_user.py`.
- Do: make `secret_key: str` required (pydantic `Field(min_length=32)`); add a validator
  that rejects a small denylist (`change-me`, `changeme`, `secret`, `test-secret` outside
  tests, etc.); remove every `or ""`. Fail in `cli.run()` *and* on `create_app()` with a
  one-line message naming the variable and the generator command from `.env.example`.
  Update `deploy/.env.example` and `deploy/standalone-tls/.env.example` so the placeholder is
  visibly invalid (e.g. `SR_SECRET_KEY=` with the comment above it).
- Verify: unit test that `Settings()` raises without the key and with a short/denylisted
  key; test that `create_session_cookie` can no longer be called with `""` (type it as
  non-optional). `docker compose up` with the key missing exits non-zero with the message.

### S2 (P0) — No server-side validation on web-form and several API inputs

**Verified during review.** With the current code: the web `PATCH /activities/{id}` accepted
and stored a **100,000-character title** (SQLite ignores `String(200)`); `/register` (when
enabled) accepted a **1-character password and a non-email address** with HTTP 200. The
`minlength`/`type=email` attributes in the templates are the only guard. The API's Pydantic
models have no password/email/name constraints either.

- Where: `server/app/api/v1/schemas.py` (`LoginRequest`, `ChangePasswordRequest`,
  `AdminCreateUserRequest`, `AdminSetPasswordRequest`, `AdminPatchUserRequest`,
  `ActivitySummary`), `server/app/web/activities.py` (`activity_patch`),
  `server/app/web/register.py`, `server/app/web/admin.py` (`admin_create_user`,
  `admin_reset_password`), `server/app/web/settings.py`.
- Do: one module `server/app/validation.py` with the rules, used by both layers:
  - password: min 8 (match the templates), max 256 (argon2 input bound); no stripping.
  - email: lowercase + max 320 + a conservative shape check (`EmailStr` needs the
    `email-validator` package — **ask before adding it**; a regex `^[^@\s]+@[^@\s]+\.[^@\s]+$`
    is enough here).
  - display_name / device_name: stripped, 1–200 chars.
  - title ≤ 200, notes ≤ 4000 (mirror `ActivityPatchRequest`).
  - `ActivitySummary`: cap `splits` length (e.g. 2000) and the raw `summary` form field size
    (e.g. 256 KB) before `model_validate_json`; the raw string is stored verbatim as
    `client_summary`, so an unbounded one goes straight into the DB.
  - Web routes: return the form partial with an error and a 400, same pattern
    `admin_reset_password` already uses for its 8-char check.
- Verify: tests for each rejection (API: 422/400 with the standard error shape; web: 400
  + error text in the fragment); the two probes above now return 400.

### S3 (P0) — Malformed pagination cursor crashes with a 500

**Verified during review.** `GET /api/v1/activities?cursor=garbage` raises
`binascii.Error` out of `decode_cursor()`; `cursor=WzFd` (a one-element list) raises
`ValueError` on unpacking; a valid list with a non-ISO date raises `ValueError`. All
surface as 500s. The web `/` route takes the same `cursor` query parameter.

- Where: `server/app/repositories/activities.py` (`decode_cursor`),
  `server/app/api/v1/activities.py` (`list_activities`), `server/app/web/activities.py`.
- Do: wrap decode in `try/except (ValueError, TypeError, json.JSONDecodeError,
  binascii.Error)` → raise a domain `InvalidCursor`; API maps it to
  `api_error(400, "invalid_cursor", ...)`, web renders the list without a cursor (or 400).
  Consider signing the cursor with `itsdangerous` (same secret, different salt) so tampered
  cursors are rejected uniformly — optional, the try/except is sufficient.
- Verify: the four cursor values from the probe (`garbage`, `Zm9v`,
  `WyJub3QtYS1kYXRlIiwieCJd`, `WzFd`) all return 400 on the API and 200/400 on `/`.

### S4 (P0) — Web logout does not invalidate the session server-side

`POST /logout` only deletes the browser cookie. The signed cookie remains valid for its
full 30-day `max_age` (`sessions.py`), so a copied cookie survives logout. There's also no
idle timeout and no per-session revocation ("sign out other browsers").

- Where: `server/app/auth/sessions.py`, `server/app/web/login.py`, `server/app/web/deps.py`,
  `server/app/auth/current_user.py`, new migration.
- Do (recommended): add a `web_sessions` table (`id`, `user_id`, `created_at`,
  `last_seen_at`, `revoked_at`, `user_agent` trimmed). The cookie payload becomes
  `(session_id, issued_at)` and is still signed. `get_web_user`/`get_current_user` look up
  the row, reject `revoked_at`, enforce an absolute lifetime (30 d) and an idle timeout
  (e.g. 14 d, bump `last_seen_at` at most once per hour to avoid a write per request).
  Logout revokes the row. Keep `sessions_invalidated_at` as the "everything" switch.
  Password change re-mints the current session (existing behaviour) and revokes the rest.
  Add a "Sessions" list with revoke to `/settings` (mirrors `/devices`).
- Cheaper alternative if the table is judged too much for now: logout bumps
  `sessions_invalidated_at` (logs the user out everywhere) — acceptable for a
  single-household instance, document the trade-off.
- Verify: test that a cookie captured before logout is rejected after; idle-timeout test
  with a monkeypatched clock; existing "change password keeps this session" test still
  passes.

### S5 (P0) — No security response headers, no CSP

Neither the app nor `deploy/standalone-tls/nginx.conf` sets HSTS, `Content-Security-Policy`,
`X-Content-Type-Options`, `X-Frame-Options`/`frame-ancestors`, `Referrer-Policy` or
`Permissions-Policy`. The pages have inline `<script>` blocks (`base.html`,
`activity_detail.html`) and load map tiles from `tile.openstreetmap.org`.

- Where: `server/app/main.py` (new middleware), `server/app/templates/base.html`,
  `server/app/templates/activity_detail.html`, `deploy/standalone-tls/nginx.conf`.
- Do: a small pure-ASGI/Starlette middleware in the app (so any reverse proxy gets them,
  not just the bundled nginx):
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains` **only when**
    `settings.secure_cookies` is true (i.e. the deployment is TLS) — never on plain-http LAN.
  - `Content-Security-Policy`: `default-src 'self'; img-src 'self' data:
    https://tile.openstreetmap.org; script-src 'self' 'nonce-<per-request>'; style-src 'self'
    'unsafe-inline'` (Leaflet sets inline styles on elements; keep `unsafe-inline` for
    styles only) `; connect-src 'self'; frame-ancestors 'none'; base-uri 'self';
    form-action 'self'`. Generate the nonce in the middleware, expose it to templates via
    `request.state.csp_nonce`, put `nonce="{{ ... }}"` on the inline scripts, and set
    `htmx.config.inlineScriptNonce` to it. Set `htmx.config.allowEval = false` (nothing uses
    `hx-on`/eval-style attributes).
  - `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
    `Permissions-Policy: geolocation=(), camera=(), microphone=()`,
    `Cross-Origin-Opener-Policy: same-origin`.
  - `Cache-Control: no-store` on every authenticated HTML page and every `/api/v1`
    response; leave `/static` cacheable (see D1).
- Verify: a test asserting each header on `/login`, `/` (signed in) and an API route, and
  HSTS absent when `SR_SECURE_COOKIES=false`; manual: browser console shows no CSP
  violations on the activity detail page (map + chart both render).

### S6 (P1) — Login timing leaks account existence; limiter has no memory bound; registration unthrottled

- `login()` (API and web) returns immediately for an unknown or disabled email but runs
  argon2 for a known one — a measurable timing difference that undoes the generic
  "invalid credentials" message.
- `InMemoryRateLimiter._events` is a `defaultdict(deque)` that never deletes keys — every
  distinct IP/email ever seen stays in memory for the process lifetime.
- `/register` (when enabled) has no rate limit; neither does `PUT /api/v1/me/password` or
  the web password change (credential-stuffing the "current password" field).
- Do: in `app/auth/passwords.py` add a module-level dummy hash computed once at import and
  a `verify_or_burn(plain, hashed | None)` used by both login paths; prune empty deques in
  `allow()` and cap the map size (evict oldest key when > N, e.g. 10k); apply a limiter
  (separate instance, e.g. 5/min per IP) to register and both password-change routes.
- Verify: tests for 429 on register and password change; a limiter test that keys are
  evicted; keep the existing login-limit reset in `conftest.py` for any new instance.

### S7 (P1) — Public API docs and version disclosure

`/api/docs` and `/api/openapi.json` are unauthenticated, and `/healthz` returns the exact
app version to anyone. Fine for a LAN, undesirable on the internet.

- Do: `SR_ENABLE_API_DOCS: bool = False` (docs on only when true; the committed
  `openapi.json` remains the contract and the export script still works because it calls
  `app.openapi()` directly). Keep `/healthz` but drop `version` unless the request is
  authenticated, or move version to `/api/v1/me`-adjacent output. Document both in
  WEB-PLAN §5.5.
- Verify: tests for 404 on `/api/docs` by default and 200 with the flag; the openapi
  drift-check in `server.yml` still passes.

### S8 (P2) — Cookie hardening details

- Use the `__Host-` prefix for the session cookie when `secure_cookies` is true
  (requires `Path=/`, no `Domain`, `Secure` — all already true), and make
  `logout()`'s `delete_cookie` pass the same `secure`/`samesite`/`httponly` flags as
  `set_session_cookie` (some browsers ignore a deletion whose attributes don't match).
- Verify: cookie name/flags asserted in the login test for both settings values.

---

## 3. Workstream R — Reliability & data safety (P1)

### R1 — Blob writes aren't atomic and deletes happen before the DB commit

`LocalFileBlobStore.put()` does a plain `write_bytes` (no temp+rename, no fsync): a crash
mid-write leaves a truncated blob that a committed row points at. `delete_activity`,
the web delete and `delete_user` unlink the blob *inside* the request, before
`db_session` commits — if the commit then fails, the row survives with no file. An
upload whose DB flush fails after `put()` leaves an orphan file.

- Where: `server/app/storage/blob_store.py`, `server/app/api/v1/activities.py`,
  `server/app/web/activities.py`, `server/app/api/v1/admin.py`, `server/app/web/admin.py`.
- Do: `put()` writes to `<path>.tmp`, `fsync`, `os.replace`; on upload, wrap so a DB
  failure after `put()` deletes the blob. For deletes, collect blob keys and remove them
  **after** commit — simplest is to have the route call `session.commit()` explicitly then
  delete, or return a Starlette `BackgroundTask`. Add a `simple-activity-tracker-server gc` CLI that
  lists/removes blobs with no row (and rows with no blob → mark analysis failed and log).
- Verify: test that a failing flush after `put()` leaves no file; test that a delete
  whose commit is forced to fail leaves the blob in place; `gc` test with a planted orphan.

### R2 — SQLite `busy_timeout` unset; a write on every authenticated request

`_enable_sqlite_pragmas` sets WAL and foreign keys but not `busy_timeout`, so any two
concurrent writers (phone upload + browser action) can fail with "database is locked".
`get_current_user` also updates `DeviceToken.last_used_at` on **every** bearer request,
turning every read into a write transaction.

- Do: `PRAGMA busy_timeout=5000` in `_enable_sqlite_pragmas`; only touch `last_used_at`
  when it is null or older than ~60 s. Consider `PRAGMA synchronous=NORMAL` (safe with WAL)
  and document it.
- Verify: a test that a second request within 60 s doesn't change `last_used_at`; a
  two-thread write test against a tmp DB no longer raises `OperationalError`.

### R3 — Concurrent first upload of the same `client_activity_id` returns 500

Idempotency is a read-then-insert; two simultaneous retries (the phone's timeout-then-
retry path) can both miss the read and the second insert hits
`uq_activities_user_client_activity_id` → `IntegrityError` → 500, and the blob from the
loser is orphaned (see R1).

- Do: catch `IntegrityError` around the flush, roll back to a savepoint
  (`session.begin_nested()`), re-fetch the existing row, delete the loser's blob, return
  200 with the existing activity.
- Verify: test that inserts the row between the read and the flush (monkeypatch the
  repository) and asserts 200 + one blob on disk.

### R4 — No backup/restore procedure

`deploy/standalone-tls/backups/` exists and is gitignored but nothing writes to it. The
data is one SQLite file (in WAL mode — copying the `.db` alone can miss the WAL) plus the
`gpx/` tree.

- Do: `simple-activity-tracker-server backup <dir>` using `sqlite3` `VACUUM INTO` (or the
  connection backup API) for the DB and a copy of `data/gpx` (or `tar`), timestamped;
  `restore` documented as "stop, replace, start". Add a cron/`docker compose run --rm app
  simple-activity-tracker-server backup /data/backups` example and a retention note to
  `deploy/standalone-tls/README.md`. Run a backup automatically before `migrate` when
  `SR_BACKUP_BEFORE_MIGRATE=true` (default true) — ties into D6.
- Verify: CLI test that a backup of a populated tmp DB restores to an identical row count
  and byte-identical blobs.

### R5 — No logging or audit trail

There is no `logging` configuration anywhere in `app/`; uvicorn's access log is the only
output, and behind a proxy it needs `--proxy-headers` (already set) to show real IPs.
Admin actions, logins, token revocations and deletions leave no record. The admin
password reset sends the new password in the `HX-Prompt` request **header**, which is more
likely than a form body to end up in proxy/access logs.

- Do: `logging.config.dictConfig` in `cli.run()` (JSON or key=value lines to stdout,
  level from `SR_LOG_LEVEL`); an `audit` logger with events `login.success`,
  `login.failure` (no password, email only), `token.revoked`, `session.revoked`,
  `user.created/disabled/enabled/promoted/demoted/deleted/password_reset`,
  `activity.deleted`, each with actor id, target id and client IP. Never log tokens,
  cookies or passwords. Change the reset-password UI to a small inline form
  (`hx-post` with a `new_password` field) instead of `hx-prompt`. Confirm nginx's
  `log_format` doesn't log request headers (default `combined` doesn't).
- Verify: caplog-based tests for two or three audit events; the reset-password web test
  updated to the form field.

### R6 — Error-response consistency and a version-string edge case

- `RequestValidationError` (422) still uses FastAPI's default `{"detail": [...]}` shape,
  not the `{"error": {...}}` contract; unhandled exceptions return Starlette's plain-text
  500 to API clients and browsers alike; `HTTPException(404)` from `get_web_admin` /
  `_require_registration_open` renders a JSON body in the browser.
- `_VERSION` in `main.py` only guards `PackageNotFoundError`; a half-installed package
  (seen during this review after an interrupted `uv sync`) makes
  `importlib.metadata.version()` return `None` and FastAPI's constructor asserts. Use
  `or "0.0.0-dev"`.
- Do: handlers for `RequestValidationError` and `Exception` that pick JSON vs. the
  `not_found.html`/an `error.html` template based on the path prefix (`/api/`) or
  `Accept`; log the 500 with a correlation id and return it in the body/header.
- Verify: tests for the 422 shape, an API 500 shape (raise inside a test-only route),
  and the browser 404 page for `/admin/users` as a non-admin.

### R7 — Template robustness and UTC display

- `activity_detail.html` reads `activity.client_summary.avg_speed_mps` (and the list
  partial reads `distance_meters`/`moving_seconds`) directly; a summary missing the key
  raises `UndefinedError` → 500. `ActivitySummary` allows `avg_speed_mps` to be omitted.
- All times are rendered with `strftime` on UTC datetimes — a 07:15 run shows as 06:15
  in UK summer time.
- Do: use `client_summary.get('avg_speed_mps')` (or `| default(none)`) everywhere the
  raw JSON is read; render times as `<time datetime="...ISO...">` and format client-side
  with a tiny script (nonce'd, see S5) in the viewer's zone, or store a per-user timezone.
  Downloaded filename already uses the date only.
- Verify: test uploading a summary without `avg_speed_mps` and rendering the page;
  test that rendered `<time>` elements carry ISO timestamps.

### R8 — Track endpoint re-parses the GPX on every map load; XML hardening

`GET /activities/{id}/track` reads and parses the full GPX from disk for every page view.
`gpxpy` uses the stdlib XML parser (Python 3.12's expat has billion-laughs protection;
external entities aren't resolved), and the 20 MB cap bounds the work, but a 20 MB
upload still costs seconds of CPU per view.

- Do: cache the downsampled track (default `max_points`) in the analysis result (or a
  sibling JSON column) at upload/reanalyze time and serve that; fall back to parsing for
  a non-default `max_points`. Add a cheap pre-parse reject of any input containing
  `<!DOCTYPE` or `<!ENTITY` (GPX never needs them).
- Verify: existing track test plus one asserting the cached path is used (no blob read);
  a test that a DOCTYPE'd file is rejected with 400.

### R9 — Duplicate business logic between API and web layers

Delete cascades, admin guards and user creation exist twice (`api/v1/*.py` and
`web/*.py`), which is how S2's validation gap and R1's ordering issue crept in on one
side. Extract `app/services/{activities,users,auth}.py` (plain functions taking a
`Session`) and have both routers call them. Do this **after** S2/R1 so the tests written
for those items guard the refactor.

---

## 4. Workstream D — Deployment behind a reverse proxy (P1/P2)

### D1 (P1) — nginx hardening in `deploy/standalone-tls/nginx.conf`

Add: `server_tokens off;`, `http2 on;`, `ssl_session_cache shared:SSL:10m;`,
`ssl_session_timeout 1d;`, `ssl_prefer_server_ciphers off;` with a modern cipher list,
`proxy_read_timeout 60s; proxy_send_timeout 60s; client_body_timeout 60s;`,
`proxy_set_header X-Forwarded-Host $host;`, a `limit_req_zone` (e.g. 10 r/m per IP,
`burst=5`) applied to `/login`, `/register`, `/api/v1/auth/login`, `gzip on` for
text/JSON, and long `expires`/`Cache-Control: public, max-age=31536000, immutable` for
`/static/` (pair with versioned asset URLs — a `?v=<sha>` query from a template global is
enough). Do **not** duplicate the app's security headers here (S5 sets them) except
HSTS, which is harmless twice. Add `access_log` with a format that includes
`$request_time` and the upstream status.

- Verify: `docker compose up` + `curl -I https://…/` shows the headers; `nginx -t` in CI
  (a container.yml step that runs `nginx -t` against the file); login limiter returns 429
  after the burst.

### D2 (P1) — Compose hardening and update discipline

`deploy/standalone-tls/docker-compose.yml` runs `…:latest` and `nginx:alpine` (both
mutable), no healthchecks on `proxy`, no log rotation, no capability drops.

- Do: pin `app` to an immutable tag (`sha-<commit>` today; semver once D4 lands) and
  `nginx` to `nginx:1.27-alpine` (or a digest); add `read_only: true` + `tmpfs: [/tmp]`
  to `app` (it writes only under `/data`), `cap_drop: [ALL]`, `security_opt:
  [no-new-privileges:true]`, `logging: {driver: json-file, options: {max-size: 10m,
  max-file: "3"}}` on both, a `healthcheck` on `proxy` (`wget -qO- http://127.0.0.1/` expecting
  301), `depends_on: app: {condition: service_healthy}`, and modest `mem_limit`s. Document
  the update procedure (`pull`, `up -d`, check `/healthz`, rollback = previous tag) in the
  README.
- Verify: `docker compose config` valid; `docker compose up -d` healthy on both services;
  `docker exec app touch /x` fails (read-only).

### D3 (P1) — Secrets handling

`SR_ADMIN_PASSWORD` stays in the container environment for the instance's whole life,
readable by anyone with `docker inspect`. `SR_SECRET_KEY` likewise lives only in `.env`.

- Do: support `SR_SECRET_KEY_FILE` / `SR_ADMIN_PASSWORD_FILE` (Docker secrets or
  bind-mounted files, read once at startup — pydantic-settings' `secrets_dir` covers this);
  after bootstrap, if `users` is non-empty and the admin password var is still set, log a
  one-line warning suggesting removal. README: rotate `SR_SECRET_KEY` = "everyone signs in
  again", nothing else breaks.
- Verify: settings test reading from a secrets dir; bootstrap warning test via caplog.

### D4 (P2) — Versioning and image provenance

- Tag releases: `container.yml` pushes `vX.Y.Z` + `vX.Y` on `v*` tags; bump
  `pyproject.toml` version in the same commit (`/healthz` and the OpenAPI title already
  read it). Add OCI labels (`org.opencontainers.image.source/revision/version`) via
  `docker/metadata-action`. Pin the base image by digest (`python:3.12-slim@sha256:…`) and
  let Dependabot bump it (D5). Add `RUN apt-get update && apt-get upgrade -y && rm -rf
  /var/lib/apt/lists/*` in the final stage, or move to a distroless-style base — pick one
  and note it in the Dockerfile.
- Verify: `docker inspect` shows the labels; a tag push produces the semver tags.

### D5 (P1) — Supply-chain checks in CI

Nothing scans dependencies or the image, and actions are pinned by major tag only.

- Do: `.github/dependabot.yml` for `pip` (uv lockfile — Dependabot supports `uv` as of
  2025; if not available for this repo, use `astral-sh/setup-uv` + `uv lock --upgrade` on
  a weekly workflow), `github-actions`, `docker` (server/Dockerfile and both compose
  files), and `pub` (mobile). Pin every `uses:` to a commit SHA with a version comment.
  In `server.yml`: `uv export --no-dev --format requirements-txt | uv run --with pip-audit
  pip-audit -r /dev/stdin --strict` (or the Snyk CLI with a token secret — **ask which**).
  In `container.yml`: `aquasecurity/trivy-action` on the loaded amd64 image, `severity:
  HIGH,CRITICAL`, `ignore-unfixed: true`, `exit-code: 1`. Run `snyk_container_scan` locally
  once and record the baseline in CLAUDE.md as WEB-PLAN §8 W0 intended.
- Verify: workflows green on a PR; a deliberately old pin (in a throwaway branch) fails
  the audit step.

### D6 (P2) — Migration safety

`run` migrates on every start with no backup and no way to opt out.

- Do: `SR_AUTO_MIGRATE: bool = True`; when true, run R4's backup first (skippable with
  `SR_BACKUP_BEFORE_MIGRATE=false`); when false, refuse to start if the DB isn't at head
  and print the `migrate` command. Document a "test the upgrade on a copy" recipe.
- Verify: CLI test with a DB one revision behind for both settings.

### D7 (P2) — External reverse proxy contract

The README's "Using a different reverse proxy" section should state exactly what the app
requires so Traefik/Caddy users don't guess: forward `Host`, `X-Forwarded-Proto`,
`X-Forwarded-For`; set `SR_TRUSTED_PROXIES` to the proxy's *exact* subnet (the
`172.16.0.0/12` default trusts every Docker network on the host); body size ≥
`SR_MAX_GPX_BYTES`; websocket not needed; and that the app never redirects http→https
itself. Add a Caddyfile snippet as a second worked example (no new service in the repo).

### D8 (P2) — `generate-cert.sh` writes `key.pem` with permissions the proxy container can't read

**Verified during R4/D6 testing (2026-09-05)** against a real Linux Docker host (not Windows/
Docker Desktop): `generate-cert.sh` writes `certs/key.pem` at mode `600` (owner-only, whichever
uid ran the script). The `proxy` container's nginx process runs as its own `nginx` user, distinct
from the host uid that generated the cert — on a real Linux host (unlike Windows/Docker Desktop's
more permissive file-sharing layer, which had been masking this) nginx fails outright at startup:
`cannot load certificate key "/etc/nginx/certs/key.pem": ... Permission denied`, and the `proxy`
container restart-loops.

- Where: `deploy/standalone-tls/generate-cert.sh`.
- Do: either `chmod 644 certs/key.pem` after generating it (private key readable by anyone who
  can already read the compose files / access the host, which is the same trust level as the
  rest of `deploy/standalone-tls/`), or have the script itself set that permission on write
  instead of leaving OpenSSL's default. Document in README "Setup" that a manually-provided
  cert/key pair (bring-your-own instead of `generate-cert.sh`) needs the same treatment.
- Verify: fresh `docker compose up -d` on a real Linux host (not just Windows/Docker Desktop,
  which didn't reproduce this) with a newly-generated cert brings `proxy` up healthy on the
  first try, no restart loop.

---

## 5. Workstream T — Tests and code quality (P2/P3)

- T1: add tests for everything above that lacks one, plus: 429 on API and web login
  (there is no rate-limit test today), `GET /` and detail page with a failed analysis,
  register flow when enabled (happy path + duplicate), cursor tampering, and the
  `db_session` rollback path (a route that raises after a write leaves no row).
- T2: `pytest-cov` with `--cov=app --cov-fail-under=85` in `server.yml` (**ask before
  adding the dev dependency**); publish the number in the PR description.
- T3: ruff — enable `S` (bandit), `SIM`, `N`, `RUF`, `PTH` rule sets, fix or `noqa` with a
  reason; remove the unused `token_hashes_equal` or use it in `get_by_hash` callers.
- T4: housekeeping — ~~fix `generate-cert.sh`'s comment that points at a non-existent
  `../traefik/docker-compose.yml`~~ (done alongside D8, #27); delete the stray empty
  `android/` directory at the repo root (a gitignored leftover from the W0 move — confirm
  it's empty first); add a `LICENSE` and a short `SECURITY.md` (how to report, supported
  versions = `main`).
- T5: `openapi.json` — after S2/S7 changes regenerate it (`uv run python -m
  app.openapi_export > openapi.json`) and make sure the mobile DTO tests still pass
  against the committed fixtures (`mobile/test/fixtures/*.json`).

---

## 6. Suggested delivery order

1. S1 → S3 → S2 (each is a small PR with tests; S2 is the largest).
2. S5 + D1 together (headers need both sides verified in a browser).
3. S4 (session table + migration) — its own PR.
4. R1 + R3 (blob/DB ordering) — one PR; R2 alongside or separately.
5. R5 (logging/audit) then R6/R7 (error and template robustness).
6. D2, D3, D5 (deployment + CI supply chain) — can run in parallel with 4–5.
7. S6, S7, S8, R4, R8, D4, D6, D7, T-items as capacity allows; R9 last.

Each PR: `ruff check . && ruff format --check . && mypy app && pytest`, regenerate
`openapi.json` if the API changed, Snyk code scan on changed files, update CLAUDE.md
status, then **propose the commit and wait**.

---

## 7. "Production behind a reverse proxy" acceptance checklist

- [x] Startup refuses a missing/weak `SR_SECRET_KEY` (S1) — #8
- [x] All user-supplied strings validated server-side on both API and web (S2) — #10
- [x] No 5xx reachable from crafted query/body input in the test suite (S3; R6, R7) — #9, #16
- [x] Logout and idle timeout actually end a web session (S4) — #12
- [x] CSP + HSTS + nosniff + frame-ancestors + no-store present; map and chart still render (S5) — #11
- [x] Login/register/password routes rate-limited and timing-neutral (S6) — #28
- [x] API docs off by default (S7) — #30
- [x] Blob writes atomic, deletes after commit, `gc` command exists (R1) — #13
- [x] `busy_timeout` set; no per-request writes on read paths (R2) — #14
- [x] Backup + restore documented and tested; pre-migration backup (R4, D6) — #26
- [x] Structured logs + audit events; no secrets in logs (R5) — #15
- [x] Error-response consistency, template robustness (R6, R7) — #16
- [x] nginx hardened (D1) — #11; compose pinned/read-only/cap-dropped/health-checked (D2) — #17
- [x] Secrets via files supported; admin password removable after bootstrap (D3) — #18
- [x] Dependabot + dependency audit + image scan in CI; actions SHA-pinned (D5) — #19
- [x] Verified end-to-end on a Linux Docker host (2026-09-05, R4/D6 testing) with a real phone upload over `https://` (user-confirmed) — this was still outstanding at W4 sign-off
- [x] `generate-cert.sh`'s key.pem readable by the proxy container on a real Linux host (D8) — #27
