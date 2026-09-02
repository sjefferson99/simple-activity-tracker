# Simple Runner

A cross-platform running app in Flutter: live GPS speed and pace, distance, kilometre splits, and GPX track logging — Android and iOS from one codebase.

## Documentation

- [docs/how-simple-runner-works.pdf](docs/how-simple-runner-works.pdf) — how the app is built and how each live metric is calculated, written for readers with no mobile or GPS background. Source at [docs/how-simple-runner-works.html](docs/how-simple-runner-works.html).
- [docs/deploy-guide.md](docs/deploy-guide.md) — step-by-step instructions for building this app from source and installing it on your own iPhone or Android phone, written for non-developers.
- [docs/PLAN.md](docs/PLAN.md) — the phased implementation plan, verified machine setup, and per-phase acceptance criteria.
- [CLAUDE.md](CLAUDE.md) — current build status and toolchain notes for anyone (human or otherwise) working on the codebase.

## Commands

```
flutter pub get
flutter analyze
flutter test
flutter run
```

See [CLAUDE.md](CLAUDE.md) for the full command reference and per-platform setup gotchas.
