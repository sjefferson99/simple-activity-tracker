# Simple Runner

A cross-platform running app in Flutter: live GPS speed and pace, distance, kilometre splits, and GPX track logging — Android and iOS from one codebase. The mobile app lives in [mobile/](mobile/); a self-hosted web app and API for syncing runs is being added (see docs/WEB-PLAN.md) in `server/`.

## Documentation

- [docs/how-simple-runner-works.pdf](docs/how-simple-runner-works.pdf) — how the app is built and how each live metric is calculated, written for readers with no mobile or GPS background. Source at [docs/how-simple-runner-works.html](docs/how-simple-runner-works.html).
- [docs/deploy-guide.md](docs/deploy-guide.md) — step-by-step instructions for building this app from source and installing it on your own iPhone or Android phone, written for non-developers.
- [docs/PLAN.md](docs/PLAN.md) — the phased implementation plan for the mobile app, verified machine setup, and per-phase acceptance criteria.
- [docs/WEB-PLAN.md](docs/WEB-PLAN.md) — the plan for the web app, API and phone-to-server sync.
- [CLAUDE.md](CLAUDE.md) — current build status and toolchain notes for anyone (human or otherwise) working on the codebase.

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

Local development, from `server/` (managed with [uv](https://docs.astral.sh/uv/)):

```
uv sync
uv run ruff check .
uv run mypy app
uv run pytest
```

Or run the whole thing in Docker — from `deploy/`, copy `.env.example` to `.env`, fill in
`SR_SECRET_KEY`, then:

```
docker compose up --build
```

`/healthz` should report `{"status": "ok", ...}` on `http://localhost:8000/healthz`.
