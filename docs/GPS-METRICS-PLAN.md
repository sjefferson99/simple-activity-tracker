# GPS metrics fix plan (issues #49 / #52)

Handoff plan for the `mobile-fix-weak-gps-and-wifi-hang` branch. Written 2026-09-07
after a long on-device session that fixed two things, broke one, and reverted it.
Read the whole thing before touching `MetricsEngine`; the "what went wrong" section is
the most valuable part.

Branch state at handoff (commit `0a31137`):

- **Working, verified on the S10, keep:** `forceLocationManager: true` +
  20s acquiring timeout (`LiveRunAcquiring(timedOut:)`) for the Wi-Fi-off hang;
  `hasAccuracy` plumbed `LocationSample → TrackPoint → MetricsEngine`.
- **Unverified / suspect:** everything in `MetricsEngine` around the noise floor
  (lowered 3m → 1.2m) and the `_recentPoints` / `_expireRecentPointsIfStale` changes.
- **Symptom still open:** on a real outdoor walk/jog, the big speed readout is
  correct but *every* metric tile (Avg, Time, Distance, Split pace, Last split) stays
  at `0` / `--`. **This also reproduces on `main`.**

## 1. Diagnosis

### 1.1 The tiles and the readout are fed by two different pipelines

`features/live_run/live_run_screen.dart`:

- The large speed readout (`_SpeedReadout`, ~line 214) shows `LiveRunActive.speedMps`,
  which `LiveRunController._onSample` sets from `sample.speedMps ?? _fallbackSpeed(point)`
  — i.e. the **GPS chip's reported speed** (`Position.speed`, Doppler-derived on
  Android GPS_PROVIDER), falling back to raw haversine between consecutive *unfiltered*
  fixes. `MetricsEngine` is not involved.
- Every tile in `_MetricGrid` calls `spec.valueOf(metrics, null, useKmh)` — note the
  literal `null` for `currentSpeedMps`. All five running-mode tiles derive from
  `LiveMetrics` fields that only change inside `MetricsEngine._acceptSegment`
  (`elapsed` = `_movingElapsed`, `distanceMeters`, `avgSpeedMps`, split fields).
- Consequence: `LiveMetrics.currentSpeedMps` and the whole `_recentPoints` /
  `_pruneRecentPoints` / `_expireRecentPointsIfStale` machinery in `MetricsEngine`
  is **never displayed**. The "current speed fix" made on this branch changed a
  dead value. The reason the readout became trustworthy on this branch is almost
  certainly `forceLocationManager: true` exposing raw GNSS Doppler speed instead of
  the fused provider's position-derived speed.

So "readout correct, tiles all zero" means exactly one thing: **`MetricsEngine.addPoint`
is rejecting (or noise-flooring) essentially every fix**, and nothing on screen tells
you which gate is doing it.

### 1.2 The noise floor is a speed threshold in disguise, and it is set to ~11 km/h

`_noiseFloorMeters` gates on *per-segment distance*. At the requested 1 Hz fix rate:

| floor | equivalent minimum speed |
|------:|-------------------------:|
| 3.0 m (`main`, from #48) | 3.0 m/s = **10.8 km/h** — rejects all walking and easy jogging |
| 1.2 m (this branch)      | 1.2 m/s = 4.3 km/h — still rejects a stroll |

Real capture (`2026-09-06 (2).gpx`, walk/jog, 110 fixes @ ~1 s, mean 1.72 m/s):
108 of 109 segments were under 3 m. Simulating the engine over that file credits
**3.2 m** at a 3 m floor and ~180 m of the true ~186 m at 1.2 m. **`main` has been
unable to track walking pace since #48 merged** — #48 was verified while running,
which clears 3 m/s.

Worse, the floor's meaning changes with fix interval: during the 7.8 s gaps seen at
the start of the indoor captures, a 3 m floor is 0.38 m/s. Per-segment distance is
simply not a coherent "is the user stationary" signal.

Confirming observation from the user on `main` (2026-09-07): on a walk the tiles
populated exactly once — Time 0:03 with a matching Distance/Avg — then never changed
while the speed readout kept updating. That is precisely this mechanism: the fix
cadence is ~7.8 s right after acquiring in every capture, so the first segment after
Start spans several seconds and clears 3 m; once the cadence settles to 1 s, every
walking-pace segment is under 3 m and is floored forever. (It also argues against the
25 m accuracy filter being the cause on `main` — that would have rejected the first
segment too.)

### 1.3 Why this branch *also* showed zeros on the last two tests (probable)

Not proven — the GPX has no accuracy column (see 1.5) — but the two candidates are:

- `_maxAcceptableAccuracyMeters = 25`. With `forceLocationManager: true` the app now
  uses GPS_PROVIDER only; indoors that reports honest, poor accuracy (often 30–100 m),
  whereas the fused provider reports optimistic Wi-Fi-assisted accuracy (10–15 m).
  Both of the last two tests were short and at least partly indoors. If accuracy was
  > 25 m the engine drops every fix before any other gate, while the readout (chip
  speed, unfiltered) keeps working. Consistent with what was seen.
- The 1.2 m floor still rejecting a slow indoor walk (see table above).

Either way the fix is the same: instrument, then stop gating on the wrong quantities.

### 1.4 The "Time" tile is moving time, which makes gating look like breakage

`_elapsedSpec` shows `metrics.elapsed` = `_movingElapsed`, which only advances when a
segment is *accepted*. Standing still, walking under the floor, or hitting the
accuracy filter all freeze the clock at 0:00. Every mainstream tracker shows
wall-clock elapsed (minus explicit pauses) as "Time" and keeps moving time internal
for pace. This is a product decision, but as-is the tile actively misleads during
exactly the conditions the filters are designed for.

### 1.5 The captures can't show the gating inputs

`RunGpxLog` writes lat/lon/ele/time only. Three sessions of GPX analysis could never
see `accuracyMeters`, `hasAccuracy`, chip `speedMps`, or `hasSpeed` — the values that
decide whether a fix is accepted. Any further tuning without these is guesswork.

### 1.6 #52 (indoor drift-then-snap-back) — what the data actually shows

Both indoor captures (`2026-09-06.gpx`, `(1).gpx`) show multipath *position* drifting
steadily 1–4 m/s in one direction for 5–10 s, then snapping back 10–18 m in one fix.
The snap-back is rejected by the plausibility filter; the ramp before it is
geometrically indistinguishable from real walking — a "straightness" filter (net
displacement ÷ path length over 25 s) caught it but also rejected a real
out-and-back walk, and was reverted (full write-up in issue #52 and in the comment
above `_noiseFloorMeters`).

The missing discriminator is not geometric. During those indoor captures the phone was
stationary, so the GNSS chip's Doppler speed would have been ~0 the whole time while
the *position* drifted. During a real out-and-back walk, chip speed stays ~1.7 m/s
including through the turnaround. The user's own observation — "current speed is now
great" (chip speed) while position-derived metrics were garbage — is that signal.

## 2. Plan

Work in this order. Each step is independently shippable and testable; do not start
step 3 until step 1's instrumentation has produced captures from both an indoor
stationary session **and** an outdoor out-and-back walk.

### Step 1 — Instrument the GPX so captures are diagnosable

**Do**

- Add `speedMps` (nullable) to `TrackPoint` (from `LocationSample.speedMps`), and
  also plumb `hasSpeed` if you want it (`Position.hasSpeed`; `speed` is `-1`/`0` when
  invalid depending on platform — `GeolocatorLocationService._toSample` already maps
  `< 0` to null).
- In `core/files/run_gpx_log.dart`, write per-point `<extensions>` carrying
  `accuracy`, `has_accuracy`, `speed` (m/s), `has_speed`. The `gpx` package supports
  `Wpt.extensions`. Namespace them (e.g. `sat:accuracy`) so they're unambiguous.
- **Verify the server still parses these files**: `server/app/analysis/gpx_parser.py`
  (`parse_gpx`) must ignore unknown extensions, and the upload path must not reject
  them. Add a server test with an extension-bearing fixture. If that's awkward,
  fall back to a `.diag.csv` sidecar next to the GPX and have `RunExportService`
  copy it too — but extensions are preferred because the user already knows how to
  retrieve the GPX.
- Update `docs/how-it-works.html` §3's "raw stream of (lat, lon, timestamp,
  accuracy)" line if the readings change, and regenerate the PDF (command in
  `CLAUDE.md`).

**Verify**

- Unit test: `RunGpxLog` output contains the extension values for a synthetic point.
- On device: one indoor stationary capture (5 min, no window), one outdoor
  out-and-back walk (2–3 min, turn around once), one easy jog. Pull all three GPX
  files. Before anything else, tabulate per fix: interval, segment distance,
  accuracy, has_accuracy, chip speed. This tells you definitively which gate zeroed
  the tiles (1.3) and whether chip speed is ~0 during drift (1.6). **Do not skip
  this.** The whole previous session was spent tuning blind.

### Step 2 — Make the tiles honest regardless of gating

**Do**

- `Time` tile → wall-clock elapsed since Start minus paused intervals. Add an
  `elapsedWallClock` (name it clearly) to `LiveMetrics`/controller; keep
  `_movingElapsed` for `avgSpeedMps`. Decide (product call, ask the user) whether
  Avg pace uses moving time (Strava "moving pace") or wall-clock (Strava "elapsed
  pace"). Moving time is the current behaviour and is fine — just don't call it
  "Time".
- Consider surfacing accuracy next to the status line while tracking (the status
  line already shows `Accuracy: ±N m` — confirm it's visible on the running screen
  and not only in `LiveRunActive` when idle). A user seeing "±45 m" understands why
  distance isn't moving; a user seeing "0.00 km" and "0:00" for two minutes does not.

**Verify**

- Widget/unit test that Time advances while no segments are accepted.
- On device: start a run indoors, watch Time count up while Distance stays 0.

### Step 3 — Replace the per-segment noise floor with a stationary detector

The floor has to go; it is the wrong quantity (1.2). Two options, in preference order.

**3a. Chip-speed gate (preferred — solves #49's walking bug and #52 together)**

Gate segment acceptance on the fix's reported speed, not on segment length:

- If `point.speedMps != null` (platform reported a valid speed): accept the segment
  for distance/time only when `speedMps >= stationaryThreshold` (start at **0.5 m/s**,
  tune from step-1 captures; a slow walk is ~1.0–1.4 m/s, indoor drift should read
  ~0). Use hysteresis (e.g. need one fix above 0.6 to leave "stationary", one below
  0.4 to enter it) so pace jitter at a walk doesn't flicker distance on/off.
- If speed is unavailable (`null`): fall back to 3b.
- Keep the plausibility + absolute-jump + re-anchor logic exactly as-is above this;
  it handles teleports and is well tested.
- Remove `_noiseFloorMeters` and the `_recentPoints` / `_expireRecentPointsIfStale`
  code unless step 2 decides to display `currentSpeedMps` — it's dead weight today.

Why this should work for #52: the drift ramps in both indoor captures happened with
the phone motionless; GNSS Doppler speed comes from carrier frequency shift, not from
successive position fixes, so multipath that moves the *position* does not produce a
matching *speed*. That is exactly the difference between a drift and a turnaround.
Step 1's capture must confirm chip speed is genuinely ~0 during a drift on this
handset before committing to this — if it isn't, this is dead too.

Risks to check: iOS reports `-1` for invalid speed (already mapped to null);
some Android devices report `0.0` with `hasSpeed == false` (map to null via
`hasSpeed`, don't trust a bare 0); speed accuracy (`Position.speedAccuracy`) is
available and could widen the threshold when poor.

**3b. Displacement-from-anchor with hysteresis (fallback when speed is unavailable)**

Instead of per-segment distance, keep a `stationaryAnchor`; while successive fixes
stay within `R` metres of it (start at **max(4 m, accuracy)**) credit nothing; once a
fix lands outside `R`, credit the distance from the anchor and move the anchor there.
This is interval-independent (a slow walk still accrues, in `R`-sized chunks), and
indoor jitter inside the accuracy radius never accrues. It does *not* stop a
20 m drift ramp — that's #52 and needs 3a — but it bounds it and it stops
walking-pace tracking being broken.

**Verify (both)**

- Rewrite the `noise floor` and `#49` test groups in
  `test/domain/tracking/metrics_engine_test.dart` around the new semantics. Keep the
  out-and-back tests — they exist because the last attempt failed exactly there.
- Replay all step-1 captures through a small Dart harness (or the Python approach
  used in the previous session — parse GPX, run the same decision logic, print
  credited distance). Required outcomes before any device install:
  indoor stationary → ≈ 0 m and Time still counts; out-and-back walk → within ~10 %
  of raw path length; jog → same.
- On device, all three scenarios again, on a **full uninstall + `flutter clean` +
  fresh install** (see §4).

### Step 4 — Docs and cleanup

- Update `docs/how-it-works.html` §4 guard table (remove "Noise floor" as
  described, add the speed gate / anchor rule, fix the "Time" description in §3) and
  regenerate the PDF.
- Update the `CLAUDE.md` status entry for #49.
- `test/features/live_run/live_run_controller_test.dart` uses a real 50 ms timer and
  was flaky once in the full suite; if it recurs, raise the test timeout to 200 ms.
- Close #52 if 3a holds up on device; otherwise re-scope it with the step-1 numbers.

## 3. What went wrong last time (read this)

- Three fixes were validated against synthetic tests plus **one** class of real
  capture (indoor drift) and shipped to the phone. The very next real test (an
  ordinary out-and-back walk) broke completely. Any change to acceptance logic must
  be validated against *both* a stationary capture and a looped/out-and-back capture
  before install.
- Metrics were "fixed" for a value (`currentSpeedMps`) that isn't displayed. Trace a
  number from the tile back to the code before fixing it.
- Thresholds were tuned in metres when the underlying quantity was m/s. Write
  thresholds in the units of the thing you're actually deciding.
- The GPX lacked the gating inputs, so every analysis was inference. Instrument
  before tuning.

## 4. On-device install procedure (from this session)

Incremental `adb install -r` left a stale binary on the S10 at least once (the
launcher shortcut didn't refresh). For any verification install:

```
adb uninstall dev.sjefferson.simple_activity_tracker
cd mobile && flutter clean && flutter pub get && flutter build apk --debug
adb install build/app/outputs/flutter-apk/app-debug.apk
adb shell dumpsys package dev.sjefferson.simple_activity_tracker | grep -E "firstInstallTime|lastUpdateTime"
```

`firstInstallTime` must equal `lastUpdateTime`. `adb` is at
`~/Library/Android/sdk/platform-tools/adb` on this Mac and is not on PATH.
`flutter install` defaults to the *release* APK and will fail/mislead after a debug
build — use `adb install` directly.

## 5. Files

- `mobile/lib/domain/tracking/metrics_engine.dart` — all acceptance logic.
- `mobile/lib/features/live_run/live_run_controller.dart` — `_onSample`, readout
  speed source, acquiring timeout.
- `mobile/lib/features/live_run/live_run_screen.dart` — `_SpeedReadout`,
  `_MetricGrid` (`valueOf(metrics, null, useKmh)`), status line.
- `mobile/lib/features/live_run/metric_spec.dart` — what each tile displays.
- `mobile/lib/core/location/geolocator_location_service.dart` — `AndroidSettings`,
  `_toSample`.
- `mobile/lib/core/files/run_gpx_log.dart` — GPX writer (step 1).
- `mobile/test/domain/tracking/metrics_engine_test.dart` — 42 tests; the
  `#49: a real out-and-back route…` group must keep passing.
- Issue #52 — full history of the reverted straightness filter.
