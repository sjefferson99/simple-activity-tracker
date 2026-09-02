# Simple Runner

Cross-platform (Android-first, iOS later) running app in **Flutter**: live GPS metrics (speed, pace, splits), GPX track logging, eventually a customizable live display.

**Read [docs/PLAN.md](docs/PLAN.md) before doing any work** — it holds the phased plan, the verified machine environment, Windows-specific setup gotchas, and per-phase acceptance criteria.

For a non-technical walkthrough of the architecture and how the live metrics are calculated (polling rate, outlier filtering, split interpolation), see [docs/how-simple-runner-works.pdf](docs/how-simple-runner-works.pdf) — source at [docs/how-simple-runner-works.html](docs/how-simple-runner-works.html). Regenerate the PDF after editing the HTML with:
```
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu --no-pdf-header-footer --print-to-pdf-no-header --print-to-pdf="docs/how-simple-runner-works.pdf" "file://$(pwd)/docs/how-simple-runner-works.html"
```

## Current status

- **Phase 0 (MVP: live GPS speed on Android) — DONE (2026-09-02).** Verified on the Pixel8_API36 emulator (stationary fix correctly showed 0.0 km/h) and on a physical Samsung S10 over USB (real walking speed tracked correctly). `flutter analyze` and `flutter test` clean (13 tests), Snyk code scan clean.
- **Phase 1 (metrics, splits, controls, GPX logging) — DONE (2026-09-02).** MetricsEngine (elapsed/distance/speed/splits with interpolated crossing times), TrackingController state machine (idle/tracking/paused/finished), MetricSpec-driven tile grid, km/h ⇄ min/km toggle, RunGpxLog (crash-safe atomic-rename flush, pause → new `<trkseg>`). Verified on a physical Samsung S10: pause/resume correctly produced 2 track segments in the written GPX file, 34 real GPS points logged. `flutter analyze` and `flutter test` clean, Snyk clean. (Test count has since grown to 29 with the review's regression tests.)
- **Phase 1 code review — DONE (2026-09-02), all findings fixed.** Worth knowing what was wrong, since some of it is easy to reintroduce: concurrent `RunGpxLog.flush()` calls shared one hardcoded `.tmp` path and could truncate the end of a run (flushes are now chained); run filenames were minute-resolution so two runs in a minute overwrote each other (now seconds + collision suffix); a throwing final flush stranded the wakelock with the screen forced on (now released in a `finally`); split average speed could be `Infinity` on a zero-duration split; the current-speed window pruned to a single point whenever fixes arrived >3s apart, blanking the speed readout under weak GPS (now always keeps the last two); and `LiveRunAcquiring` had no Stop control despite already holding the wakelock (now has Cancel). 29 tests, analyze and Snyk clean.
- **Debug banner hidden (2026-09-02)** via `debugShowCheckedModeBanner: false`. Note this only hides the ribbon — device builds are still debug-compiled Dart, so performance is not representative of release.
- **iOS groundwork — VERIFIED on iOS Simulator (2026-09-02).** `ios/Runner/Info.plist` has `NSLocationWhenInUseUsageDescription`, `NSLocationAlwaysAndWhenInUseUsageDescription`, and `UIBackgroundModes: location`; `GeolocatorLocationService` branches to `AppleSettings` (fitness activity type, background updates) instead of forcing `AndroidSettings` everywhere. First Mac build (`flutter build ios --debug --simulator`) succeeded cleanly, including `pod install` — no fixes needed. Ran on an "iPhone 17" simulator (iOS 26.5): app launched, correctly showed the native location-permission dialog with the Info.plist description text, and after granting reached the same idle "Press Start to begin tracking" screen as Android. **Still not tested on a physical iPhone** — that's this week, per plan.
- **Mac dev environment set up (2026-09-02).** Flutter 3.47.2 and CocoaPods installed via Homebrew (`brew install --cask flutter`, `brew install cocoapods`) — both land on PATH automatically via the existing `brew shellenv` eval in `~/.zprofile`, no manual PATH edits needed. Xcode installed from the App Store (Command Line Tools alone is not enough — `flutter doctor` reports "Xcode installation is incomplete" until the full app is installed and `sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer` + `sudo xcodebuild -runFirstLaunch` are run). iOS simulator runtimes are a separate ~8.5GB download on top of Xcode itself (`xcodebuild -downloadPlatform iOS`) — Xcode being "installed" doesn't mean a runtime is ready to boot. Android Studio also installed via Homebrew (`brew install --cask android-studio`) to get a second, independent Android toolchain on the same Mac; its SDK Manager did **not** install `cmdline-tools` by default even though it can build and run apps — `flutter doctor` needs it explicitly ticked on the SDK Tools tab (cmdline-tools missing shows as "Unable to locate Android SDK" style errors even with an otherwise-working SDK). Both toolchains coexist fine on one machine: this Mac can now build/run iOS (simulator only so far) and Android (verified against a physical Samsung SM-G975F over USB) independently of the Windows desktop.
- **GPS outlier filtering + duplicate-fix bug — FIXED (2026-09-02).** Found by running the iOS Simulator's built-in "City Run" location scenario, which starts from a stale fix and so injects a ~65km teleport between the first two fixes. Three distinct bugs, all worth knowing since the reasoning is easy to get wrong:
  - **No outlier rejection at all.** `MetricsEngine` only filtered on accuracy and non-positive duration, so one teleport permanently poisoned cumulative distance/average speed (showed 60.57km and 4101 km/h after 53s). Current speed self-heals because it is windowed; distance and `_movingElapsed` have no windowing or decay, so they never recover. It also manufactured ~65 phantom splits, the last of which got a sub-millisecond interpolated duration — that was the "Last split 0:00" symptom, not a formatting bug.
  - **Rejecting a point must not pin the anchor.** The first fix kept `_lastAccepted` on the pre-jump point, so every subsequent *good* fix near the teleport's landing spot also looked impossible and was rejected too — a real run lost ~77s of clean data before the implied speed against the stale anchor decayed under the threshold. Two consecutive rejects that agree with each other now re-anchor. Re-anchoring credits **no** distance or elapsed time (the path between is unknowable, so it is a discontinuity like pause/resume), clears `_recentPoints` (or the speed tile reads the teleport's implied speed for seconds afterwards), and requires ≥2m of motion between the pair — a GPS stuck repeating one wrong position implies 0 m/s, which "agrees" trivially and would otherwise hand the anchor to the bad location.
  - **Speed alone is not a sufficient test.** A long enough gap makes any teleport look slow (65km in an hour is ~18 m/s), so there is also an absolute 20km per-segment cap and a 30s TTL on the re-anchor candidate. The cap has to stay generous: a legitimately sparse stretch of fixes (tunnel, backgrounded app) can cover kilometres between fixes, and an earlier 1km cap broke the multi-split test.
  - **Every GPS fix was logged twice.** `LiveRunController.start()` never tore down the previous run before allocating a new one, and `LocationService.stream` opens a *fresh* platform stream per access rather than sharing one — so a re-entrant `start()` (double-tapped Start, or `startNewRun()` without a `stop()`) stacked a second listener and double-counted every fix into both the metrics engine and the GPX file (442 trackpoints for 221 fixes). It also leaked the flush timer and dropped the previous `RunGpxLog` unfinalized. `start()` now calls `_disposeRun()` first.
- **Phase 2 and beyond — NOT STARTED** (see docs/PLAN.md §6).
- Update this section as work progresses (phase started/done, deviations from docs/PLAN.md).

### Toolchain notes learned during Phase 0 (beyond docs/PLAN.md §1)

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

## Quick facts (details in docs/PLAN.md §1)

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

## Architecture rules (from docs/PLAN.md §3 — follow strictly)

- Feature-first layout: `lib/app`, `lib/core/{location,units,files}`, `lib/domain/{models,tracking}`, `lib/features/live_run`.
- `core/units` and `domain/` are **pure Dart** — no `flutter` imports; unit-test everything there.
- The app touches GPS only through the `LocationService` interface (`core/location`) and our own `LocationSample` model — geolocator types never leak out of `core/location/`.
- Metric tiles are driven by a `MetricSpec` list even while the layout is static — this is what makes the future customizable display cheap.
- State: Riverpod, one-way flow (service stream → Notifier → immutable state → widgets).

## Conventions

- Units displayed: km/h and min/km. All conversions/formatting via `core/units`, nowhere else.
- Speeds are stored internally in m/s (as GPS provides); convert only at display time.
- Commit at meaningful milestones; stay on `main` unless told otherwise.
