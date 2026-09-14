# Simple Activity Tracker

A cross-platform running app in Flutter: live GPS speed and pace, distance, kilometre splits, and GPX track logging — Android and iOS from one codebase. The mobile app lives in [mobile/](mobile/); a self-hosted web app and API for syncing runs is being added (see docs/WEB-PLAN.md) in `server/`.

## Documentation

- [docs/how-it-works.pdf](docs/how-it-works.pdf) — how the app is built and how each live metric is calculated, written for readers with no mobile or GPS background. Source at [docs/how-it-works.html](docs/how-it-works.html).
- [docs/deploy-guide.md](docs/deploy-guide.md) — step-by-step instructions for building this app from source and installing it on your own iPhone or Android phone, written for non-developers.
- [docs/PLAN.md](docs/PLAN.md) — the phased implementation plan for the mobile app, verified machine setup, and per-phase acceptance criteria.
- [docs/WEB-PLAN.md](docs/WEB-PLAN.md) — the plan for the web app, API and phone-to-server sync.
- [docs/SERVER-PRODUCTION-PLAN.md](docs/SERVER-PRODUCTION-PLAN.md) — review findings and the action plan to run the server in production behind a reverse proxy.
- [docs/MOBILE-QUALITY-PLAN.md](docs/MOBILE-QUALITY-PLAN.md) — review findings and the action plan to bring the mobile app to internal-testing code quality.
- [CLAUDE.md](CLAUDE.md) — current build status and toolchain notes for anyone (human or otherwise) working on the codebase.

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
runs to. See [docs/WEB-PLAN.md](docs/WEB-PLAN.md) for the design and phased plan.

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
- **Mobile** (`mobile-release.yml`): builds a release APK (`flutter build apk --release`,
  debug-signed — see `mobile/android/app/build.gradle.kts`) and attaches it to the
  GitHub Release for that same tag, ready to sideload per
  [docs/deploy-guide.md](docs/deploy-guide.md#installing-on-android). It never touches
  the release's title or body, so write those by hand.

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
