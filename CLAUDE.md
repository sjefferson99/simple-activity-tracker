# Simple Runner

Cross-platform (Android-first, iOS later) running app in **Flutter**: live GPS metrics (speed, pace, splits), GPX track logging, eventually a customizable live display.

**Read [PLAN.md](PLAN.md) before doing any work** — it holds the phased plan, the verified machine environment, Windows-specific setup gotchas, and per-phase acceptance criteria.

## Current status

- **Phase 0 (MVP: live GPS speed on Android) — DONE (2026-09-02).** Verified on the Pixel8_API36 emulator (stationary fix correctly showed 0.0 km/h) and on a physical Samsung S10 over USB (real walking speed tracked correctly). `flutter analyze` and `flutter test` clean (13 tests), Snyk code scan clean.
- **Phase 1 (metrics, splits, controls, GPX logging) — NOT STARTED.**
- Update this section as work progresses (phase started/done, deviations from PLAN.md).

### Toolchain notes learned during Phase 0 (beyond PLAN.md §1)

- Flutter has no `winget` package — installed via `git clone -b stable` to `C:\git\flutter` (added to user PATH), not `C:\flutter`.
- `sdkmanager` requires `JAVA_HOME` pointed at the Android Studio JBR (`C:\Program Files\Android\Android Studio\jbr`) or it fails with "Java version 17 or higher is required" (it was picking up the stale Java 8 on PATH).
- The Gradle-driven NDK auto-download can silently produce a **corrupt/incomplete install** (missing `source.properties` and several top-level dirs) if interrupted — if a build fails with "did not install NDK ... into ...\Sdk", delete `%LOCALAPPDATA%\Android\Sdk\ndk\<version>\` entirely and let it redownload rather than trying to repair it.
- Switching `flutter run` target device (e.g. emulator x86_64 → phone arm64) can leave stale locked artifacts under `build\app\...\x86_64\` — if Gradle errors with `AccessDeniedException` or "Unable to delete directory" under `build\`, a previous `flutter run` process is usually still attached to the old device and holding files open. Find and stop it (check for orphaned `dart`/`dartvm`/`java` processes older than the current session) before `flutter clean`.
- A physical phone can drop to adb "offline" over USB; `adb kill-server && adb start-server` alone doesn't always fix it — a cable reseat usually does.

## Quick facts (details in PLAN.md §1)

- Windows 11, PowerShell. Android SDK at `%LOCALAPPDATA%\Android\Sdk`; Android Studio at `C:\Program Files\Android\Android Studio` (use its `jbr` as the Gradle JDK — the Java 8 on PATH is too old).
- No AVDs exist yet; cmdline-tools not installed; Windows Developer Mode needed for Flutter plugin symlinks.
- Test on emulator (simulated GPX routes) for iteration, physical Android phone over USB for real GPS truth.

## Commands

```powershell
flutter doctor -v        # toolchain health (only Android section must be green)
flutter pub get
flutter analyze          # must be clean before finishing any task
flutter test             # must pass before finishing any task
flutter run              # runs on the connected device/emulator
```

## Architecture rules (from PLAN.md §3 — follow strictly)

- Feature-first layout: `lib/app`, `lib/core/{location,units,files}`, `lib/domain/{models,tracking}`, `lib/features/live_run`.
- `core/units` and `domain/` are **pure Dart** — no `flutter` imports; unit-test everything there.
- The app touches GPS only through the `LocationService` interface (`core/location`) and our own `LocationSample` model — geolocator types never leak out of `core/location/`.
- Metric tiles are driven by a `MetricSpec` list even while the layout is static — this is what makes the future customizable display cheap.
- State: Riverpod, one-way flow (service stream → Notifier → immutable state → widgets).

## Conventions

- Units displayed: km/h and min/km. All conversions/formatting via `core/units`, nowhere else.
- Speeds are stored internally in m/s (as GPS provides); convert only at display time.
- Commit at meaningful milestones; stay on `main` unless told otherwise.
