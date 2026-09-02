# Simple Runner

Cross-platform (Android-first, iOS later) running app in **Flutter**: live GPS metrics (speed, pace, splits), GPX track logging, eventually a customizable live display.

**Read [PLAN.md](PLAN.md) before doing any work** — it holds the phased plan, the verified machine environment, Windows-specific setup gotchas, and per-phase acceptance criteria.

## Current status

- **Phase 0 (MVP: live GPS speed on Android) — DONE (2026-09-02).** Verified on the Pixel8_API36 emulator (stationary fix correctly showed 0.0 km/h) and on a physical Samsung S10 over USB (real walking speed tracked correctly). `flutter analyze` and `flutter test` clean (13 tests), Snyk code scan clean.
- **Phase 1 (metrics, splits, controls, GPX logging) — DONE (2026-09-02).** MetricsEngine (elapsed/distance/speed/splits with interpolated crossing times), TrackingController state machine (idle/tracking/paused/finished), MetricSpec-driven tile grid, km/h ⇄ min/km toggle, RunGpxLog (crash-safe atomic-rename flush, pause → new `<trkseg>`). Verified on a physical Samsung S10: pause/resume correctly produced 2 track segments in the written GPX file, 34 real GPS points logged. `flutter analyze` and `flutter test` clean (26 tests), Snyk clean.
- **Phase 2 and beyond — NOT STARTED** (see PLAN.md §6).
- Update this section as work progresses (phase started/done, deviations from PLAN.md).

### Toolchain notes learned during Phase 0 (beyond PLAN.md §1)

- Flutter has no `winget` package — installed via `git clone -b stable` to `C:\git\flutter` (added to user PATH), not `C:\flutter`.
- `sdkmanager` requires `JAVA_HOME` pointed at the Android Studio JBR (`C:\Program Files\Android\Android Studio\jbr`) or it fails with "Java version 17 or higher is required" (it was picking up the stale Java 8 on PATH).
- The Gradle-driven NDK auto-download can silently produce a **corrupt/incomplete install** (missing `source.properties` and several top-level dirs) if interrupted — if a build fails with "did not install NDK ... into ...\Sdk", delete `%LOCALAPPDATA%\Android\Sdk\ndk\<version>\` entirely and let it redownload rather than trying to repair it.
- Switching `flutter run` target device (e.g. emulator x86_64 → phone arm64) can leave stale locked artifacts under `build\app\...\x86_64\` — if Gradle errors with `AccessDeniedException` or "Unable to delete directory" under `build\`, a previous `flutter run` process is usually still attached to the old device and holding files open. Find and stop it (check for orphaned `dart`/`dartvm`/`java` processes older than the current session) before `flutter clean`.
- A physical phone can drop to adb "offline" over USB; `adb kill-server && adb start-server` alone doesn't always fix it — a cable reseat usually does.

### Toolchain notes learned during Phase 1

- **`geolocator`'s `ForegroundNotificationConfig.enableWakeLock: true` requires the `android.permission.WAKE_LOCK` manifest permission.** Without it, the whole geolocator event channel throws a `SecurityException` and silently delivers zero location samples (no crash, no error surfaced to the app — just "stuck acquiring GPS forever"). We don't need it: `wakelock_plus` already keeps the screen on during tracking, so `enableWakeLock` is left at its default `false` rather than adding the permission for a redundant lock. If GPS acquisition mysteriously stops working after touching `AndroidSettings`/`ForegroundNotificationConfig`, check `adb logcat` for `EventChannel...geolocator_updates_android` — that's where this exception surfaces, not anywhere Dart-side.
- **This machine has a recurring `AccessDeniedException`/"Unable to delete directory" issue on `--release` Android builds specifically in `extractReleaseNativeSymbolTables`** (and occasionally other `build\app\intermediates\...\<abi>\` paths) — something (likely AV) transiently locks a freshly-written per-ABI directory. Each retry gets further (clears one ABI's lock, hits the next), suggesting it's not a real Gradle/project bug. **Workaround: use `flutter run -d <device>` (debug mode, no `--release`) for day-to-day device testing** — debug builds skip R8/symbol-table extraction entirely and haven't hit this. Save `--release` builds for verifying release-config specifics only, and expect to need a manual `Remove-Item -Recurse -Force` retry loop on the specific locked path if you do use it.

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
