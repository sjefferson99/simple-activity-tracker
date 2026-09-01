# Simple Runner — Flutter Running App: Plan & Handoff

A cross-platform (Android first, iOS later) running app using the phone's GPS to track runs and display live metrics. Modular architecture so the MVP (current speed display) ships quickly while scaling to splits, GPX logging, customizable display, history, etc.

This document is the implementation handoff. Status of each phase is tracked in [CLAUDE.md](CLAUDE.md).

---

## 1. Verified environment (checked 2026-09-01)

| Item | State |
|---|---|
| Repo `c:\git\simple-runner` | Empty (git repo, `main` branch, no commits) |
| Flutter / Dart | **Not installed** |
| Android Studio | Installed at `C:\Program Files\Android\Android Studio` (bundled JBR JDK at `...\Android Studio\jbr` — use this for Gradle) |
| Android SDK | `%LOCALAPPDATA%\Android\Sdk` — platform-tools (adb ✓), emulator ✓, platforms android-36 & android-36.1, build-tools 35.0.0 & 36.0.0 |
| SDK cmdline-tools | **Missing** — `flutter doctor` will flag it; needed for `sdkmanager`/license acceptance |
| AVDs (emulators) | **None configured** — one must be created before emulator testing |
| Java on PATH | Oracle **Java 8** shim (`C:\Program Files (x86)\Common Files\Oracle\Java\java8path`) — too old for Gradle; do NOT let builds pick it up |
| Node.js | Installed (irrelevant to Flutter, noted for completeness) |
| Test devices | Android emulator (simulated GPS routes) + physical Android phone via USB (real GPS) |

### Known Windows/setup gotchas (address during Phase 0 step 1)

- **Windows Developer Mode must be enabled** — Flutter plugins on Windows require symlink support (`start ms-settings:developers`). Build fails with "Building with plugins requires symlink support" otherwise.
- **cmdline-tools**: install via Android Studio → SDK Manager → SDK Tools → "Android SDK Command-line Tools (latest)", or `sdkmanager "cmdline-tools;latest"`. Then run `flutter doctor --android-licenses`.
- **JDK**: if Gradle picks up Java 8, set `flutter config --jdk-dir "C:\Program Files\Android\Android Studio\jbr"`.
- **Flutter install**: `winget install --id=Google.Flutter -e` or `git clone https://github.com/flutter/flutter.git -b stable C:\flutter` and add `C:\flutter\bin` to PATH. Verify with `flutter doctor -v` until the Android toolchain section is green (the Chrome/Visual Studio sections may stay red — irrelevant, we only target mobile).
- **AVD**: create one via Android Studio Device Manager (e.g. Pixel 8, android-36 image), or `avdmanager`. Emulator GPS simulation: Extended controls (⋮) → Location → import GPX/KML route → play at chosen speed.

---

## 2. Framework & packages

- **Flutter + Dart**, single codebase for Android/iOS.
- **geolocator** — GPS position stream (speed, accuracy, altitude). Its `AndroidSettings(foregroundNotificationConfig: ...)` provides the Android foreground service in Phase 1 so tracking survives screen-off.
- **flutter_riverpod** — state management + DI. Services are provided via providers so fakes swap in for tests.
- **path_provider** — app documents dir for GPX files (Phase 1).
- **gpx** (pub.dev) — GPX 1.1 read/write (Phase 1).
- **wakelock_plus** — keep screen awake during a run (Phase 1).

Use latest stable versions from pub.dev at implementation time (`flutter pub add <pkg>`); don't pin from this doc.

---

## 3. Architecture (modular, feature-first)

```
lib/
  main.dart             # ProviderScope + runApp
  app/                  # MaterialApp, theme, top-level routing
  core/
    location/           # LocationService interface + GeolocatorLocationService
                        # + FakeLocationService (scripted points, for tests/dev)
    units/              # pure conversions & formatting (see §3.1)
    files/              # GpxWriter, run-file naming/paths       (Phase 1)
  domain/
    models/             # TrackPoint, RunSession, Split, LiveMetrics
    tracking/           # TrackingController state machine        (Phase 1)
                        # MetricsEngine: pure functions            (Phase 1)
  features/
    live_run/           # run screen: metric tile grid + control buttons
    # future: settings/, history/, display_customizer/
test/                   # mirrors lib/ structure
```

Rules that keep it modular:

- **`core/units` and `domain/` are pure Dart** — no `flutter` imports (`dart:` and plain packages only). Everything there is unit-testable with synthetic data.
- **`LocationService` is an abstract interface**: `Stream<LocationSample> get stream`, `Future<bool> requestPermission()`, `start()`/`stop()`. `LocationSample` is our own model (lat, lon, elevationM, speedMps?, accuracyM, timestamp) so the app never depends on geolocator types outside `core/location/`.
- **Metric tiles are driven by a `MetricSpec` list** (id, label, value-formatter function). The static Phase 1 layout is a hard-coded list; the future customizable display just swaps in a persisted list. Build the tile grid this way from the start.
- State flows one way: LocationService stream → controller (Riverpod `Notifier`) → immutable state → widgets.

### 3.1 core/units — required functions (write unit tests)

- `kmhFromMps(double)` ; `paceSecPerKmFromMps(double)` (guard divide-by-zero → null/∞ handling)
- `formatKmh(double)` → `"12.3"` ; `formatPace(double secPerKm)` → `"4:52"` (min:sec, zero-padded seconds)
- `formatDuration(Duration)` → `"1:02:35"` / `"12:35"`
- `formatDistanceKm(double meters)` → `"5.21"`

---

## 4. Phase 0 — MVP: prove GPS speed on Android

**Goal:** the app runs on an Android device and displays live GPS speed. Smallest slice through the real architecture — no throwaway code.

**Steps:**

1. **Toolchain** — install Flutter, fix the gotchas in §1 (Developer Mode, cmdline-tools, licenses, JDK, create one AVD). Done when `flutter doctor` shows Android toolchain + connected device green.
2. **Scaffold** — `flutter create --org dev.sjefferson --project-name simple_runner --platforms android,ios .` in the repo root (org/app id is changeable later, before any store release). Add `.gitignore` entries flutter create provides; delete the demo counter test.
3. **Dependencies** — `flutter pub add geolocator flutter_riverpod`.
4. **Android manifest** — add `ACCESS_FINE_LOCATION` and `ACCESS_COARSE_LOCATION` to `android/app/src/main/AndroidManifest.xml`.
5. **core/location** — `LocationSample` model; `LocationService` interface; `GeolocatorLocationService` using `Geolocator.getPositionStream(locationSettings: AndroidSettings(accuracy: LocationAccuracy.bestForNavigation, distanceFilter: 0, intervalDuration: 1s))`, mapping `Position` → `LocationSample`. Permission flow: `checkPermission` → `requestPermission`, surface denied/deniedForever/serviceDisabled as typed states, not exceptions.
6. **core/units** — `kmhFromMps` + `formatKmh` (+ tests).
7. **Speed logic** — current speed = `sample.speedMps` when the fix provides it (Android usually does); fallback = haversine distance / Δt over the last two samples when `speedMps` is null. Keep this in a small pure function so Phase 1's MetricsEngine absorbs it.
8. **features/live_run** — single screen: very large speed readout in km/h, status line beneath it (`Acquiring GPS…` / `Accuracy: ±8 m` / permission-denied message with a "open settings" action via `Geolocator.openAppSettings()`), one Start/Stop button toggling the stream. Riverpod `Notifier` holds `{idle, acquiring, active(speedKmh, accuracyM), denied, serviceOff}`.
9. **app/ + main.dart** — dark theme (outdoor readability), portrait-locked is fine for now.

**Acceptance criteria:**

- `flutter analyze` — zero issues; `flutter test` — passing (units tests at minimum).
- On emulator: play a GPX/KML route in Extended controls → Location; the speed readout changes plausibly.
- On the phone (`flutter run` over USB): walking outside shows a believable walking speed (~4–6 km/h).
- Snyk code scan on the new code passes clean (per user's global instructions: scan, fix, rescan until clean).

---

## 5. Phase 1 — Run session: metrics, splits, controls, GPX logging

1. **TrackingController** (`domain/tracking`) — state machine `idle → tracking ⇄ paused → finished`. Buttons: **Start**; **Pause/Resume**; **Stop** guarded by long-press or confirm dialog. Paused segments excluded from elapsed time and distance; points arriving while paused are discarded.
2. **MetricsEngine** (pure Dart, heavily unit-tested) — input: accepted `TrackPoint`s + pause intervals; output `LiveMetrics`: elapsed, distance (haversine over accuracy-filtered points — drop fixes with accuracy worse than ~25 m), current speed (smoothed over last ~3 s), overall average speed, completed 1-km **splits** (each with time + avg speed) and the in-progress split. Design the split boundary interpolation (a point rarely lands exactly on 1.000 km — interpolate crossing time between the straddling points).
3. **Units toggle** — one app-wide setting flips every speed/pace tile between **km/h** and **min/km**.
4. **Live display (static for now)** — tile grid from a hard-coded `MetricSpec` list: current speed/pace, avg speed/pace, elapsed, distance, current split pace, last split time. `wakelock_plus` on while tracking.
5. **GPX logging** (`core/files/GpxWriter`) — during tracking, append points to `<appDocuments>/runs/run_YYYY-MM-DD_HHmm.gpx` **incrementally** (flush every N points / few seconds; crash mid-run must not lose the track — simplest robust approach: rewrite-to-temp-then-rename, or append `<trkpt>` lines and repair the footer on finalize). Finalize valid GPX 1.1 on Stop using the `gpx` package. Pauses become separate `<trkseg>` segments.
6. **Background reliability** — geolocator `foregroundNotificationConfig` so tracking continues with screen off; add `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_LOCATION` manifest permissions.
7. **Verification** — MetricsEngine unit tests with synthetic runs of known distance/speed (constant-speed run → exact splits; GPS jitter samples → distance not inflated); emulator route playback sanity-checks splits; real outdoor run confirms metrics and the GPX file opens in gpx.studio; Snyk scan clean.

---

## 6. Future phases (architecture supports; do not build yet)

Customizable live display (persist MetricSpec list), run history + summary screen, auto-pause, audio cues, map view, iOS build & store setup, HR sensors, share/export.

---

## 7. Working agreements

- `flutter analyze` and `flutter test` must be clean before any phase is called done.
- Pure-Dart layers (`core/units`, `domain/`) never import Flutter.
- Snyk code scan on newly written first-party code; fix and rescan until clean (user's global policy).
- Commit at meaningful milestones with clear messages; stay on `main` unless asked otherwise.
