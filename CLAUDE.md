# Simple Activity Tracker

Cross-platform (Android-first, iOS later) activity tracker: a **Flutter** app in `mobile/` (live GPS metrics, splits and targets, GPX logging, audio cues) and a **FastAPI** server in `server/` (web UI, `/api/v1` for phone sync, GPX analysis), deployed as a Docker image.

Repo: [github.com/sjefferson99/simple-activity-tracker](https://github.com/sjefferson99/simple-activity-tracker) (formerly `simple-runner`; the old URL redirects). Server image: `ghcr.io/sjefferson99/simple-activity-tracker-server` (the old `simple-runner-server` package is unused).

**This file is general context for any branch.** Don't record work status, progress or per-issue history here. That belongs in the relevant `docs/` plan, the PR and the issue.

## Docs: read the relevant one before starting

- [docs/PLAN.md](docs/PLAN.md): the mobile app's phased plan, verified machine environment, Windows setup gotchas, acceptance criteria. **Read before any work.**
- [docs/WEB-PLAN.md](docs/WEB-PLAN.md): web app, API and phone-to-server sync. Decisions (§12) and working agreements (§13, including: **prompt before installing anything on the machine**).
- [docs/VERSIONING.md](docs/VERSIONING.md): release version, API levels, app ↔ server compatibility. **Read before changing anything the app sends to or reads from the server** (see Conventions below).
- [docs/SERVER-PRODUCTION-PLAN.md](docs/SERVER-PRODUCTION-PLAN.md) and [docs/MOBILE-QUALITY-PLAN.md](docs/MOBILE-QUALITY-PLAN.md): hardening plans; each item has a `Do`/`Verify`.
- [docs/GPS-METRICS-PLAN.md](docs/GPS-METRICS-PLAN.md): **read before touching `MetricsEngine`** (noise gating, distance crediting, replay methodology).
- Feature plans (`docs/*-PLAN.md`) for splits, split targets, audio cues, activity history, etc.
- [docs/how-it-works.pdf](docs/how-it-works.pdf): non-technical walkthrough (source: `docs/how-it-works.html`). Regenerate the PDF after editing the HTML:
  ```
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu --no-pdf-header-footer --print-to-pdf-no-header --print-to-pdf="docs/how-it-works.pdf" "file://$(pwd)/docs/how-it-works.html"
  ```

## Quick facts (details in docs/PLAN.md §1)

- Windows 11, PowerShell; a Mac is also set up for iOS (Homebrew Flutter/CocoaPods, full Xcode) and Android.
- Android SDK at `%LOCALAPPDATA%\Android\Sdk`; Android Studio at `C:\Program Files\Android\Android Studio` (use its `jbr` as the Gradle JDK; the Java 8 on PATH is too old). `adb` is at `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe` (not on PATH).
- One AVD, `Pixel8_API36`. Test on the emulator for iteration, a physical phone over USB for real GPS truth.
- A Linux Docker host for prod-like deployment checks is reachable over SSH (see memory).

## Commands

Mobile, from `mobile/`:

```powershell
flutter doctor -v        # toolchain health (only Android section must be green)
flutter pub get
flutter analyze          # must be clean before finishing any task
flutter test             # must pass before finishing any task
flutter run              # runs on the connected device/emulator
```

Server, from `server/` (use the full `uv.exe` path from Bash, see gotchas):

```
uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest
uv run python -m app.openapi_export > openapi.json   # after any API change; diff it
```

Release version for the current checkout: `scripts/release-version.sh`.

## Architecture rules (from docs/PLAN.md §3, follow strictly)

- Feature-first layout under `mobile/lib/`: `app`, `core/{location,units,files,api,sync,version,…}`, `domain/{models,tracking}`, `features/…`.
- `core/units`, `core/version/api_compat.dart` and `domain/` are **pure Dart**: no `flutter` imports; unit-test everything there.
- The app touches GPS only through the `LocationService` interface (`core/location`) and our own `LocationSample` model. geolocator types never leak out of `core/location/`.
- Only `core/api/http_api_client.dart` knows URLs and the wire format; everything else talks to `ApiClient`.
- Metric tiles are driven by a `MetricSpec` list, which is what makes the future customizable display cheap.
- State: Riverpod, one-way flow (service stream → Notifier → immutable state → widgets). Never let a user-input error become an `AsyncNotifier`'s `AsyncError` when a form is built from that provider; it unmounts the form. Rethrow and show the error inline.

## Conventions

- Units displayed: km/h and min/km (mi variants follow the split unit). All conversions/formatting via `core/units`, nowhere else.
- Speeds are stored internally in m/s (as GPS provides); convert only at display time.
- **Always ask before `git commit`, `git push`, opening a PR, or merging a PR.** Each of these four is its own approval, every time, not a package deal. Summarize what would happen and wait for an explicit go-ahead before each one, even at a milestone, even if the same action was approved earlier in the session, even right after finishing a fix the user asked for. **A go-ahead covers only the specific unit of work it was given for**: "commit this" doesn't extend to a later bugfix, and "commit, PR and merge" once doesn't carry to the next PR. If a request is ambiguous about scope, ask. Merging defaults to **the user does it**; only merge yourself when the current request says so in words.
- Stay on `main` unless told otherwise (server work always gets a branch, see below).
- **Any PR for work driven by a GitHub issue must include a closing keyword** (`Closes #<n>`) on its own line near the top of the PR body, so merging auto-closes the issue. Applies whenever the request references an issue or the branch name encodes one (`server-126-...`, `mobile-99-...`).
- **NO SUB AGENTS EVER, unless specifically asked for in that request.** This includes the `code-review` skill's default multi-agent mode. A plain "run a code review" is NOT a request for sub agents; do the review directly. Only use the Agent tool or multi-agent review when the user explicitly asks (e.g. "ultrareview", "use sub agents").
- **App ↔ server compatibility: build defensively, every time** ([docs/VERSIONING.md](docs/VERSIONING.md)). Phone and server are updated independently, so a newer app must work against an older server and vice versa. The non-negotiables:
  - **Mobile never sends the server something it might not know.** Upload fields go through `buildUploadSummaryJson()` (`core/api/upload_payload.dart`), shaped by the server's API level. Never send `RunSummary.toJson()` directly. A new request field or endpoint is gated on `serverApiLevel >= N` (constants in `ApiLevels`). Level 0 = any server ≤ v1.2.4, and must keep working.
  - **Mobile reads responses tolerantly.** Any field newer than level 0 is optional with a default (never a throwing cast); unknown enum values don't crash; a 404 from an endpoint older servers lack means "unsupported", not an error. Free-form maps (`analysis.result`) are read only via `core/api/tolerant_json.dart`.
  - **Two contracts live outside openapi.json, so the CI guard can't see them.** (1) `analysis.result`: every field an app reads is listed in `contract/analysis-result/app-reads.json`. Only add entries, never rename or retype one; released apps hard-cast some of them. (2) GPX `sat:` extensions: never change an existing value format; new meaning gets a new extension name. Goldens live in `contract/gpx/`.
  - **Server stays additive and tolerant.** Request models use `extra="ignore"`, never `forbid`. Never remove or rename a field or endpoint, make an optional field required, or narrow accepted values.
  - **Any change to `server/openapi.json` paths/components bumps `API_LEVEL`** (server) **and `kAppApiLevel`** (app, kept equal by a test), adds a row to VERSIONING.md §2, and, if the upload payload changed, regenerates `contract/upload-summary/api-level-N.json`. CI fails a PR that doesn't. A breaking change also needs `MIN_APP_API_LEVEL` bumped (CI-enforced); prefer not breaking.
  - **Release versions are display-only.** Never compare them in code. `pubspec.yaml` (`0.0.0`) and `pyproject.toml` versions are placeholders; the `vX.Y.Z` tag is the only source.
  - **Test against the previous level too**, not only the current server (FakeApiClient's `getServerInfoHandler` / `ServerInfoDto.legacy`).

## Server dev/test workflow (use every time we work on `server/`)

Applies to any server change of more than trivial size. One plan item (or tightly related group) = one branch = one PR.

1. **Branch per item/group.** `git checkout main && git checkout -b server-<short-name>`. Never commit server work straight to `main`.
2. **Implement with tests.** Every behavior change gets a test. Run the full check suite (Commands above). Regenerate and diff `openapi.json` if the API surface or request schema changed: new/changed constraints are expected drift, anything else isn't. Run `snyk_code_scan` on `server/` and fix any new finding (ignore the known low-severity "hardcoded password" hits in `tests/` fixtures and the `env_prefix` false positive in `app/config.py`).
3. **Local integration test before asking for a commit**, in a *real* container (unit tests don't exercise startup, container networking or the nginx/TLS layer):
   - For a batch of branches verified together, merge them into a throwaway local `integration-<name>-local-test` branch (never pushed; delete afterwards) and run the full check suite on it.
   - Build the image tagged **exactly** `ghcr.io/sjefferson99/simple-activity-tracker-server:latest` (`docker build --build-arg APP_VERSION=$(scripts/release-version.sh) -t ghcr.io/sjefferson99/simple-activity-tracker-server:latest server/`) so `deploy/standalone-tls/docker-compose.yml` picks it up unchanged. That's the dev host's real stack (persistent `.env`, cert, `./data`). Only shadow `:latest` like this immediately before merging.
   - `cd deploy/standalone-tls && docker compose up -d`; confirm clean logs (`docker logs standalone-tls-app-1`, no tracebacks), `(healthy)`, and `curl -sk https://127.0.0.1/healthz`.
   - Exercise the changed behavior with `curl` (bearer via `/api/v1/auth/login`; web login needs a cookie jar + `X-Requested-With: htmx` on POSTs). `deploy/standalone-tls/.env` on this dev machine is not sensitive; read admin credentials from it rather than asking. Clean up any test data you create in a real account.
4. **Hand off to the user and STOP.** Report what was verified (each probe, pass/fail, test counts, Snyk) and ask the user to confirm in the running stack. Don't commit, push or open a PR before that sign-off. A bug report or "yes, fix it that way" approves the *design* of a fix, not its commit/push/PR/merge.
5. **On confirmation: commit, push, open the PR, stop again.** PR body = summary + test plan (automated checks and what was verified in the container), with the issue-closing keyword. Don't merge unless the current request says so.
6. **After merge:** confirm CI green, confirm the `Container` workflow pushed to GHCR, `docker pull` the image, restart the dev stack on it, confirm healthy, and `git checkout main && git pull`.

### Multi-step features

- **Prefer one branch with sequential commits over stacked PRs** when later steps can't be tested without earlier ones. Structure the PR description as step 1 / step 2 / … so each step can still be signed off.
- If steps really are independently useful, give each its own PR **targeted at `main`**, never at another PR's branch: GitHub auto-deletes a merged head branch and **silently closes any PR based on it** (it can't be reopened). Rebase each downstream branch onto `main` after each merge.
- A review fix that spans open branches goes on **one** branch (the earliest affected) and flows downstream by rebase, never re-applied by hand (that creates real conflicts).
- Before merging, check `gh pr view <N> --json mergeable,mergeStateStatus` is `MERGEABLE`/`CLEAN`. CI green is not the same as merge-clean. A bare "merge commit cannot be cleanly created" needs that query (or `git merge-tree`) to diagnose, not a retry.

## Gotchas worth knowing (general, any branch)

### Windows, shells, tooling

- Flutter lives at `C:\git\flutter` (git clone; no winget package). Neither Flutter nor `uv` is on the Bash tool's PATH: use PowerShell, or full paths (`C:\git\flutter\bin\flutter.bat`, `%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_*\uv.exe`).
- **Scripted file edits must be encoding-safe.** Python's `read_text()`/`write_text()` default to cp1252 on Windows and will corrupt UTF-8 characters (`—`, `§`, `·`). Pass `encoding="utf-8"` (or edit bytes), or use the Edit tool. Many repo files are CRLF; `sed` patterns must allow for `\r`.
- **Git Bash rewrites POSIX-looking arguments into Windows paths**, including the container side of `-v host:/data` and `docker exec … /data`. Prefix with `MSYS_NO_PATHCONV=1`. `openssl -subj "/CN=…"` needs a `//CN=` escape instead (`generate-cert.sh` handles it). Windows Python can't see Git Bash's `/tmp`; use `$(cygpath -m "$TMP")`.
- Git Bash synthesizes the executable bit, so a new script can look executable locally but be committed as 100644. Use `git update-index --chmod=+x`.
- `sdkmanager` needs `JAVA_HOME` at the Android Studio JBR. An interrupted NDK auto-download can leave a corrupt install: delete `%LOCALAPPDATA%\Android\Sdk\ndk\<version>\` and let it redownload.
- `git mv` of a directory can fail with "Permission denied" while a gitignored build cache inside holds a handle. Move items individually.

### Mobile build and device

- **`AccessDeniedException` / "Unable to delete directory" under `mobile\build\…`** is the Gradle daemon holding locks (debug and release alike). Fix: `cd mobile\android && ./gradlew --stop` (with `JAVA_HOME` set to the JBR), delete `mobile\build\`, rebuild. `flutter clean` alone isn't enough.
- **`flutter install` doesn't rebuild**, and neither does a bare `adb install` of the output APK. A failed `flutter build` leaves the *previous* APK in place, so check the build succeeded before installing. Verify device-visible changes with a screenshot (`adb exec-out screencap -p > file.png`).
- A phone dropping to adb "offline": `adb kill-server && adb start-server`, or reseat the cable.
- **geolocator:** `ForegroundNotificationConfig.enableWakeLock: true` needs the `WAKE_LOCK` permission, or the location channel silently delivers nothing (see `adb logcat` for `geolocator_updates_android`). We keep it `false`; `wakelock_plus` handles the screen. **`geolocator_android` drops every `Position.has*` flag** (always false on Android), so `sampleFromPosition()` derives them from `accuracy > 0` / `speed > 0`. Don't "fix" that back.
- Plugins pinning an old or unresolvable `compileSdk` (e.g. `media_store_plus` at 33, `flutter_secure_storage` at the sub-versioned 37) are forced to the app's own compileSdk via `pinCompileSdkToApp()` in `mobile/android/build.gradle.kts`. It must run in `afterEvaluate`, not `plugins.withId`. `media_store_plus` is unmaintained and flagged by Flutter's Kotlin Gradle Plugin (KGP) deprecation; if a Flutter upgrade breaks it, patch, fork, or replace it with a MediaStore platform channel.
- Phone ↔ desktop LAN failures: check which Wi-Fi the phone is actually on (a silent reconnect to an isolated guest SSID looks exactly like a firewall block). Docker Desktop logs show every client as `127.0.0.1`/`172.x`; use `netstat -ano | findstr :<port>` on the host for real remote IPs.
- `dart:io`'s client doesn't follow redirects on non-GET requests, so an `http://` URL behind an https-redirecting proxy returns the redirect's HTML. `HttpApiClient` maps 3xx to a clear "try https://" error. Self-signed certs use trust-on-first-use pinning (`CertTrustStore`).

### Server

- **Process-level singletons** (`get_settings()`/`get_engine()` `lru_cache`s, rate limiters) must be reset in `tests/conftest.py`, or state leaks between tests in misleading ways. Any new module-level singleton needs the same treatment. Settings must stay lazy, not built at import time.
- `TestClient` talks plain http, so its cookie jar silently drops `Secure` cookies; tests set `SR_SECURE_COOKIES=false`. It also re-raises unhandled exceptions unless built with `raise_server_exceptions=False`.
- CSRF relies on `hx-headers`, which only applies to htmx-issued requests. Every mutating control must use `hx-post`/`hx-patch`/`hx-delete`, never a bare `<form method="post">`.
- SQLAlchemy doesn't order deletes of FK-linked rows with no `relationship()`: `session.flush()` after deleting the child, before the parent. After a caught `IntegrityError` inside `begin_nested()`, call `session.rollback()` before reusing the session.
- A FastAPI `BackgroundTask` runs while the response is sent, **before** the `db_session` dependency's post-yield commit. Commit explicitly before side effects that depend on it (e.g. deleting a blob).
- Alembic's `fileConfig()` must keep `disable_existing_loggers=False`, or every app logger (including the audit log) is silently disabled in production.
- **`SR_ADMIN_PASSWORD` only applies on the very first bootstrap.** Editing it later doesn't change the existing admin's password.
- `/data` and `/backups` bind mounts on a fresh **Linux** host are created root-owned. The container runs as uid 1000: `sudo chown -R 1000:1000 data backups`. `generate-cert.sh` makes `key.pem` world-readable, since nginx runs as a different user.
- A deployment's own trimmed copy of the compose file doesn't pick up new `app` volumes automatically (e.g. `./backups:/backups`, needed because the app runs `read_only`).
- The database filename changed with the project rename (`simple_runner.db` → `simple_activity_tracker.db`). An older deployment must rename its file, or the app silently starts with an empty database.
- Multi-platform `docker buildx build` needs `docker buildx create --driver docker-container --use` locally (CI's setup action does this).
- The GHCR package defaulted to private when created; flipping visibility needs the web UI (`gh`'s default token lacks `read:packages`/`write:packages`).
