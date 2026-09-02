# Simple Runner

Cross-platform (Android-first, iOS later) running app in **Flutter**: live GPS metrics (speed, pace, splits), GPX track logging, eventually a customizable live display.

**Read [PLAN.md](PLAN.md) before doing any work** — it holds the phased plan, the verified machine environment, Windows-specific setup gotchas, and per-phase acceptance criteria.

## Current status

- **Phase 0 (MVP: live GPS speed on Android) — DONE (2026-09-02).** Verified on the Pixel8_API36 emulator (stationary fix correctly showed 0.0 km/h) and on a physical Samsung S10 over USB (real walking speed tracked correctly). `flutter analyze` and `flutter test` clean (13 tests), Snyk code scan clean.
- **Phase 1 (metrics, splits, controls, GPX logging) — DONE (2026-09-02).** MetricsEngine (elapsed/distance/speed/splits with interpolated crossing times), TrackingController state machine (idle/tracking/paused/finished), MetricSpec-driven tile grid, km/h ⇄ min/km toggle, RunGpxLog (crash-safe atomic-rename flush, pause → new `<trkseg>`). Verified on a physical Samsung S10: pause/resume correctly produced 2 track segments in the written GPX file, 34 real GPS points logged. `flutter analyze` and `flutter test` clean, Snyk clean. (Test count has since grown to 29 with the review's regression tests.)
- **Phase 1 code review — DONE (2026-09-02), all findings fixed.** Worth knowing what was wrong, since some of it is easy to reintroduce: concurrent `RunGpxLog.flush()` calls shared one hardcoded `.tmp` path and could truncate the end of a run (flushes are now chained); run filenames were minute-resolution so two runs in a minute overwrote each other (now seconds + collision suffix); a throwing final flush stranded the wakelock with the screen forced on (now released in a `finally`); split average speed could be `Infinity` on a zero-duration split; the current-speed window pruned to a single point whenever fixes arrived >3s apart, blanking the speed readout under weak GPS (now always keeps the last two); and `LiveRunAcquiring` had no Stop control despite already holding the wakelock (now has Cancel). 29 tests, analyze and Snyk clean.
- **Debug banner hidden (2026-09-02)** via `debugShowCheckedModeBanner: false`. Note this only hides the ribbon — device builds are still debug-compiled Dart, so performance is not representative of release.
- **iOS groundwork — WRITTEN BUT UNVERIFIED (2026-09-02).** `ios/Runner/Info.plist` now has `NSLocationWhenInUseUsageDescription`, `NSLocationAlwaysAndWhenInUseUsageDescription`, and `UIBackgroundModes: location`; `GeolocatorLocationService` branches to `AppleSettings` (fitness activity type, background updates) instead of forcing `AndroidSettings` everywhere. **None of this has been compiled or run** — it was written on Windows, where the iOS build can't be tested. First `flutter run` on a Mac is the real check (expect to need `pod install`).
- **Phase 2 and beyond — NOT STARTED** (see PLAN.md §6).
- Update this section as work progresses (phase started/done, deviations from PLAN.md).

### Toolchain notes learned during Phase 0 (beyond PLAN.md §1)

- Flutter has no `winget` package — installed via `git clone -b stable` to `C:\git\flutter` (added to user PATH), not `C:\flutter`.
- `sdkmanager` requires `JAVA_HOME` pointed at the Android Studio JBR (`C:\Program Files\Android\Android Studio\jbr`) or it fails with "Java version 17 or higher is required" (it was picking up the stale Java 8 on PATH).
- The Gradle-driven NDK auto-download can silently produce a **corrupt/incomplete install** (missing `source.properties` and several top-level dirs) if interrupted — if a build fails with "did not install NDK ... into ...\Sdk", delete `%LOCALAPPDATA%\Android\Sdk\ndk\<version>\` entirely and let it redownload rather than trying to repair it.
- Orphaned `flutter run` processes (e.g. left attached to a device after switching targets) are worth cleaning up, but they are **not** the usual cause of `build\` lock errors — see the Gradle daemon note under Phase 1 for the real fix.
- A physical phone can drop to adb "offline" over USB; `adb kill-server && adb start-server` alone doesn't always fix it — a cable reseat usually does.

### Toolchain notes learned during Phase 1

- **`geolocator`'s `ForegroundNotificationConfig.enableWakeLock: true` requires the `android.permission.WAKE_LOCK` manifest permission.** Without it, the whole geolocator event channel throws a `SecurityException` and silently delivers zero location samples (no crash, no error surfaced to the app — just "stuck acquiring GPS forever"). We don't need it: `wakelock_plus` already keeps the screen on during tracking, so `enableWakeLock` is left at its default `false` rather than adding the permission for a redundant lock. If GPS acquisition mysteriously stops working after touching `AndroidSettings`/`ForegroundNotificationConfig`, check `adb logcat` for `EventChannel...geolocator_updates_android` — that's where this exception surfaces, not anywhere Dart-side.
- **Recurring `AccessDeniedException` / "Unable to delete directory" under `build\app\intermediates\...`** (seen in `extractReleaseNativeSymbolTables`, `mergeDebugNativeLibs`, `mergeDebugAssets`, `merged_native_libs\...\arm64-v8a`). It affects **both debug and release** builds — an earlier note here blamed release mode and AV scanning; that was wrong. **The holder is the Gradle daemon itself**: the failing paths are empty directories, and once `./gradlew --stop` runs, `Remove-Item -Recurse -Force` on `build\` succeeds immediately and the next build is clean. Clearing individual directories without stopping the daemon just moves the failure to the next directory. **Fix: `cd android && ./gradlew --stop`, delete `build\`, rebuild.** (`flutter clean` is not enough on its own — it hits the same locks.) This recipe has since been applied successfully more than once, so treat it as the first thing to try, not a guess.
- **`flutter install` does not rebuild.** It deploys whatever APK is already sitting in `build\app\outputs\`, so after a code change it will happily install the *previous* binary and the change appears not to have worked. Run `flutter build apk --debug` first, or just use `flutter run`. (This bit us on the debug-banner change — the fix looked broken until a screenshot showed the old APK had been installed.)
- **Verify device-visible changes with a screenshot** (`adb exec-out screencap -p > file.png`, then read the image) rather than assuming a successful install means the change is live.

## Quick facts (details in PLAN.md §1)

- Windows 11, PowerShell. Android SDK at `%LOCALAPPDATA%\Android\Sdk`; Android Studio at `C:\Program Files\Android\Android Studio` (use its `jbr` as the Gradle JDK — the Java 8 on PATH is too old).
- Set up during Phase 0 and still in place: cmdline-tools installed, SDK licences accepted, Windows Developer Mode enabled (needed for Flutter plugin symlinks), and one AVD named `Pixel8_API36`.
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
