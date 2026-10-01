# Simple Activity Tracker

A self-hosted activity tracker for running, walking and cycling. A **Flutter phone app**
(Android, with iOS from the same codebase) records your activity with live GPS metrics,
split targets and spoken cues, and syncs it to **your own server**: a FastAPI web app
with maps, charts, analysis, search, import/export and sharing, deployed as one Docker
image. Nothing goes to a third-party service; the server is yours, and it can be a
Raspberry Pi on your home network.

## How it works

1. **Plan your pacing.** Before you start, set how your activity is split (every km,
   every mile, every few minutes, or a custom list of variable-length splits for
   intervals or a race plan) and give any split a target pace or speed. Plans can be
   built on the web and loaded on the phone.
2. **Record, and stay on pace.** Pick Run, Walk or Cycle and press Start. The app reads
   GPS fixes, filters out noisy ones (indoor drift, stale or jumping fixes), and shows
   live distance, speed or pace, time and splits. Each split is judged against its
   target as you go: the screen shows on target, too fast or too slow, and beeps and
   spoken cues announce each split's target and tell you to speed up or ease off, so you
   don't have to look at the phone. Every fix is written to a GPX file on the phone as
   you go, so a crash never loses the track.
3. **Follow along live (optional).** With live upload on, the route also goes to your
   server about once a minute. People you've chosen on the same server can watch it on
   a live map, and if the phone dies, what was uploaded can still be saved.
4. **Sync when finished.** When you stop, the activity joins an upload queue that
   retries with backoff until it reaches your server. Nothing is lost offline.
5. **Analyse on the server.** The server stores the original GPX, runs its own
   analysis (distance, moving time, smoothed speed and elevation, splits against your
   targets, best efforts) and shows it all in the web app, alongside the phone's own
   numbers. Re-slice the splits at any size afterwards.
6. **Find any activity.** Search everything you've recorded or imported by text (title,
   notes, tags), distance range and activity type, or by **place**: drop a pin on a map
   and find every activity that started, finished, or did either or both near it. Sort,
   page through and export exactly the results you filtered to.
7. **Share if you want.** Choose who can watch you live and who can see your history,
   per person or per activity. Viewers get read-only access, and you can change or
   revoke it at any time.

The phone and server are updated independently and stay compatible either way round:
the app checks the server's API level and only uses what that server supports (see
[docs/VERSIONING.md](docs/VERSIONING.md)).

## Features

### Phone app

- **Three activity types:** run, walk and cycle, each with its own GPS plausibility
  filters and display (pace for running and walking, speed for cycling).
- **Live metrics** on one screen that scales to the device: current speed or pace (tap
  to switch), average, distance, time and moving time, max speed, elevation gain, split
  pace or speed, distance or time remaining in the split, and the last split.
- **Units:** km or miles, with speed (km/h, mph) and pace (min/km, min/mi) following
  the split unit.
- **Splits:** every kilometre, every mile, or every N minutes, or a **custom plan** of
  variable-length splits (intervals, a race plan). An expandable list on the run screen
  shows every finished split.
- **Split targets:** a target pace or speed for every split or per custom split, with an
  on-target / too fast / too slow verdict on screen.
- **Audio cues:** beeps on a new split and on verdict changes, and spoken announcements
  of each split's target and pace corrections. Other audio (music, podcasts) pauses
  while a cue plays.
- **Saved split configs:** load a split plan saved on the server, or save the current
  one to it, so plans are shared between the phone and the web editor.
- **Pause and resume:** paused time is excluded, and the GPX gets a new track segment.
- **GPX logging:** crash-safe and written continuously; on Android it's also copied to
  the Downloads folder when you finish.
- **Server sync:** sign in once (self-signed certificates are trusted on first use by
  fingerprint), and finished activities upload automatically with retry and backoff.
  Settings shows the queue, with retry and clear options.
- **Live upload and sharing:** live upload is on by default and can be turned off to
  save mobile data. Choose who can watch you live, or tap "Don't live share". The run
  screen shows how many people can currently watch (it can't tell whether anyone has
  the live page open). Changes apply immediately, even mid-run, and wait on the phone
  if you're offline.
- **Activity history:** browse your activities from the server, with the server's
  analysis, splits and targets. Reopen a run recorded on this phone, even offline.
- **Version check:** Settings shows the app and server versions and warns if either is
  too old for the other.

### Web app

- **Activity list:** paginated, sortable by date or distance, with **Mine** and
  **Shared with me** tabs.
- **Search and filters:** text (title, notes, tags), distance range, activity type,
  owner (shared tab), and a **location filter**: drop a pin on a map and match
  activities that start, finish, or do either or both within a radius.
- **Activity detail:** map of the route with split markers, a pace/speed and elevation
  chart (time, km or mile axis) with hover linked to the map, the server's analysis,
  best 1 km / 5 km / 10 km efforts, and a splits table you can re-slice at any size or
  reset to the plan you ran with, including target verdicts.
- **Organise:** edit title, notes and device name; add and remove tags; delete one or
  many activities.
- **Get activities in:** upload a GPX from any device, import a backup .zip from another
  server, or import a whole **Strava export** (GPX, TCX and FIT files). Imports show
  their progress.
- **Get activities out:** download any activity's original GPX, or export all, selected
  or filtered activities as a .zip that another server can import.
- **Split configs editor:** build and save the split plans the phone can load.
- **Sharing:** choose who can watch you **live** and who can see your **history**, share
  a single finished activity with extra people, or pause live sharing in one switch.
  Viewers see read-only pages with no edit, download or export.
- **Live page:** a map and the phone's own stats that update every 15 seconds, splits so
  far, and how long ago the last update arrived. It switches to "finished" when the
  activity ends. The owner can **convert** a session the phone never finished uploading
  into a normal activity; if the phone's upload arrives later, it replaces that activity
  and keeps any title, notes, tags and sharing.
- **Account:** change your password, see and sign out browser sessions, and revoke phone
  devices.
- **Administration:** admins create users, reset passwords, disable, promote and delete
  accounts. Registration is closed unless you open it.

### Server and operations

- **One Docker image** for amd64 and arm64, published to GHCR on every merge, plus an
  nginx sidecar that terminates HTTPS with a self-signed certificate.
- **Storage:** SQLite plus the original GPX files on disk; migrations run automatically
  on start.
- **API:** a versioned JSON API (`/api/v1`) used by the phone, with OpenAPI docs that
  can be turned on.
- **Security:** signed, server-side revocable sessions and device tokens (no JWTs),
  CSRF protection, a strict CSP and security headers, rate-limited login, input
  validation on every field, secrets read from files, and an audit log of
  security-relevant actions. Anything not yours or shared with you is a 404.
- **Maintenance CLI:** backup (database plus GPX files), re-run analysis after an
  analyzer upgrade, and find orphaned files.

## Documentation

- [docs/how-it-works.pdf](docs/how-it-works.pdf): how the app is built and how each
  live metric is calculated, written for readers with no mobile or GPS background.
  Source at [docs/how-it-works.html](docs/how-it-works.html).
- [docs/deploy-guide.md](docs/deploy-guide.md): building the app from source and
  installing it on your own iPhone or Android phone, written for non-developers.
- [deploy/standalone-tls/README.md](deploy/standalone-tls/README.md): running your own
  server.
- [docs/VERSIONING.md](docs/VERSIONING.md): release versions, API levels, and how the app
  and server stay compatible.
- Design plans: [docs/PLAN.md](docs/PLAN.md) (mobile app),
  [docs/WEB-PLAN.md](docs/WEB-PLAN.md) (web app, API and sync),
  [docs/LIVE-TRACKING-PLAN.md](docs/LIVE-TRACKING-PLAN.md) (live tracking and sharing),
  [docs/GPS-METRICS-PLAN.md](docs/GPS-METRICS-PLAN.md) (GPS filtering), and the other
  feature plans in [docs/](docs/).
- [docs/SERVER-PRODUCTION-PLAN.md](docs/SERVER-PRODUCTION-PLAN.md) and
  [docs/MOBILE-QUALITY-PLAN.md](docs/MOBILE-QUALITY-PLAN.md): the hardening reviews
  behind the server's production setup and the app's code quality.
- [CLAUDE.md](CLAUDE.md): working notes for anyone (human or otherwise) developing the
  codebase: architecture rules, conventions, commands and setup gotchas.

## Installing the mobile app on your phone

**Android:** download the latest `.apk` from the
[Releases page](https://github.com/sjefferson99/simple-activity-tracker/releases)
and sideload it — no computer or toolchain needed. See
[docs/deploy-guide.md](docs/deploy-guide.md#installing-on-android) for
step-by-step instructions, including how to allow installing from outside
the Play Store.

**iPhone:** needs building from source on a Mac (an Apple restriction, not
this app's choice) — see
[docs/deploy-guide.md](docs/deploy-guide.md#installing-on-iphone-needs-a-mac).

## Commands

Mobile app (from `mobile/`):

```
flutter pub get
flutter analyze
flutter test
flutter run
```

See [CLAUDE.md](CLAUDE.md) for the full command reference and per-platform setup gotchas.

## Server

A self-hosted web app and API (Python/FastAPI, SQLite, htmx) that the mobile app syncs
activities to. See [docs/WEB-PLAN.md](docs/WEB-PLAN.md) for the design.

### Deployment

To run your own instance, see [deploy/standalone-tls/README.md](deploy/standalone-tls/README.md)
— an app container plus an nginx sidecar that terminates HTTPS with a self-signed
certificate. No domain or external reverse proxy required; works unchanged on amd64 or
arm64 (e.g. a Raspberry Pi), and doubles as a template if you'd rather front it with a
different reverse proxy (Traefik, Caddy, etc.) for production certificate management.

```
cd deploy/standalone-tls
cp .env.example .env            # fill in SR_SECRET_KEY, SR_ADMIN_EMAIL, SR_ADMIN_PASSWORD
./generate-cert.sh <your-LAN-IP-or-hostname>
docker compose up -d
```

### Development

Local development, from `server/` (managed with [uv](https://docs.astral.sh/uv/)):

```
uv sync
uv run ruff check .
uv run mypy app
uv run pytest
```

Or run the app alone in Docker without TLS — from `deploy/`, copy `.env.example` to
`.env`, fill in `SR_SECRET_KEY`, then:

```
docker compose up --build
```

`/healthz` should report `{"status": "ok", ...}` on `http://localhost:8000/healthz`. This
plain compose file is for local iteration and the CI smoke test, not for deploying
somewhere reachable — see Deployment above for that.

### Cutting a release

One `vX.Y.Z` tag is the release for the whole repo — server and mobile app together,
even on a version bump that only touched one of them. Pushing (or publishing, from the
GitHub UI) a `v*.*.*` tag triggers both `container.yml` and `mobile-release.yml`:

- **Server** (`container.yml`): every merge to `main` already publishes
  `ghcr.io/sjefferson99/simple-activity-tracker-server` as `:latest` and an immutable
  `sha-<short-commit>` tag — this is enough for normal use (see "Updating and rolling
  back" in [deploy/standalone-tls/README.md](deploy/standalone-tls/README.md)). A
  versioned release additionally tags the image `vX.Y.Z` and `vX.Y`, for a stable name
  that doesn't shift when `main` moves. Every image — `:latest`, `sha-*`, and semver
  alike — is stamped with OCI labels (`org.opencontainers.image.source/revision/version`)
  via [docker/metadata-action](https://github.com/docker/metadata-action), so `docker
  inspect` on any pulled image shows exactly which commit and version it came from.
  `:latest` only ever tracks `main`, not a release tag — a `v*.*.*` push produces
  `vX.Y.Z`/`vX.Y` alongside whatever `sha-<short-commit>` matches that same commit,
  without moving `:latest`.
- **Mobile** (`mobile-release.yml`): builds a release APK (`flutter build apk --release`)
  signed with a dedicated release keystore (`ANDROID_KEYSTORE_BASE64` and friends —
  repo secrets, not committed; see `mobile/android/app/build.gradle.kts`) and attaches
  it to the GitHub Release for that same tag, ready to sideload per
  [docs/deploy-guide.md](docs/deploy-guide.md#installing-on-android). It never touches
  the release's title or body, so write those by hand. **Every release uses the same
  keystore** — this matters because Android refuses to install an APK "over" an
  existing install signed with a different key (fails with a bare "App not installed").
  Outside this workflow (e.g. `flutter run --release` on a dev machine), the release
  build type falls back to the Flutter debug keystore, same as before this existed —
  fine for on-device development, but never sideload a locally-built release APK
  alongside a release-tag one on the same phone; uninstall one first if you need to
  switch, since their signatures won't match either.

To cut a release:

```
# bump version in server/pyproject.toml first if the server changed, commit it, then
# either:
git tag vX.Y.Z
git push origin vX.Y.Z
# ...or create the tag from the GitHub UI: Releases → Draft a new release → type a new
# tag "vX.Y.Z" targeting main → write release notes → Publish. Either way, publishing
# the tag is what triggers both workflows above.
```

The mobile build takes a few minutes, so the APK asset typically appears on the release
a little after the release itself goes live — not a sign anything failed.
