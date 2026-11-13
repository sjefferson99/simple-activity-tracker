# Barometer elevation plan (issue #184)

Goal: decide, from real recordings, how the phone's barometer and GPS altitude should be combined for elevation (live tile and server analysis), per activity and carry position, before building it (step 2). This is an ongoing loop: every new recording is assessed, until new recordings stop changing the answer.

This file is the method. The recordings, coverage tracker, findings and assessment log are private (recordings hold locations), so they live outside the repo in a shared captures folder, in `TUNING-LOG.md` next to the data. Whoever is working on this says where that folder is on their machine.

## Status

| Step | What | State |
|---|---|---|
| 1 | Log pressure per fix (`sat:pressure_hpa`, mean of the last second) | Built, on a test phone |
| 1b | Log tuning diagnostics (pressure spread, GPS vertical accuracy, motion, cadence) | Built, on a test phone |
| — | Collect recordings with references, assess each one | **Ongoing**: see `TUNING-LOG.md` |
| 2 | Shared live + server algorithm, contract fixture, terrain anchoring, source note, walk/run tile | Waiting on the data |

## What the phone logs per fix

All are per-point `sat:` GPX extensions, each absent when unavailable. None changes analysis yet; the server parses only `pressure_hpa`.

| Extension | Meaning |
|---|---|
| `pressure_hpa` | Mean barometer reading over the second before the fix (Android: as fast as the sensor allows, typically 10 Hz; iOS: CMAltimeter's own rate) |
| `pressure_sd` | Spread (population SD, hPa) of those readings: how disturbed the barometer is right now |
| `vertical_accuracy` | GPS altitude accuracy the platform reports (m) |
| `motion_rms` | Accelerometer shake over the last second (m/s², gravity removed) |
| `cadence_hz` | Dominant rhythm of the accelerometer over the last 4 s (1–4 Hz), absent if there isn't a clear one. Only meaningful when `motion_rms` is above about 0.5 m/s². |

## Routine for every new recording

1. Record with the phone, and a barometric reference where possible (a bike computer for rides, a watch for runs and walks). Note the carry position.
2. Pull the phone GPX: `adb pull /sdcard/Download/SimpleActivityTracker/<file>.gpx`. Export the reference's **original** FIT (from Strava: Export Original), not a GPX.
3. Sync the shared captures folder into the repo's `captures/elevation/` (gitignored). Copy both files in, and add an entry to `manifest.json` (`activity`: run/walk/ride, `carry`: pocket/hand/armband/handlebar).
4. From `server/`: `uv run python -m scripts.elevation_replay ../captures/elevation --save`.
5. In `TUNING-LOG.md`: add a row to the assessment log, update the coverage tracker, and record anything new in the findings.
6. Sync back to the shared folder: newer files only, both ways, never delete. If `manifest.json` or `TUNING-LOG.md` was edited on two machines, merge by hand.
7. Apply the stopping rule.

## What to collect

The tracker in `TUNING-LOG.md` counts recordings with a reference against these targets:

| Activity | Carry | Target |
|---|---|---|
| Run | Pocket | 3 |
| Run | Hand / armband | 2 |
| Walk | Pocket | 2 |
| Walk | Hand | 1 |
| Ride | Pocket | 3 |
| Ride | Handlebar mount | 2 |
| Any | Hilly route, repeated ups and downs | 1 |

## Candidates the replay scores

- **gps_181**: today's analysis, GPS through the #181 filter. The baseline, and the only option for activities recorded without a barometer.
- **baro**: barometer height with a smoothing time constant and dead-band grid.
- **baro_wind**: the same, minus a wind term k·v². Airflow over a pocket lowers the pressure with the square of speed; early rides measured about 1.7 m at 10 m/s, so k = 0.017 m per (m/s)².
- **blend**: complementary filter. Barometer for short-term change, plus a slowly tracked barometer-minus-GPS offset (2–15 min) for the level.
- **kalman**: height, vertical speed and barometer offset, weighted per fix by `pressure_sd` and `vertical_accuracy`, so it leans on whichever source is quieter at that moment instead of using a rule per activity.

Scores, over the time both devices cover:
- **gain_err**: |gain − ref| + |loss − ref| as a fraction of the reference's own session ascent + descent (the figure users see).
- **shape**: the RMS height difference from the reference once their offset is removed.
- **loop**: how far a loop recording without a reference ends from its starting height.

Each family's setting is also chosen **leave-one-out** (tuned on all other recordings, scored on this one). That is the number to trust, not the best fit.

## Stopping rule

Stop collecting and build step 2 when both hold:
- every target above has at least 2 recordings with a reference, and
- over the last 3 recordings added, the leading family didn't change and its leave-one-out gain error moved by less than 2 percentage points.

## Historical activities

Activities already recorded have no barometer data, so step 2 can only change them through the GPS path. The replay scores `gps_181` on every recording, so it also checks whether the #181 constants still hold. Older phone recordings with a matching reference FIT can be added to the manifest with no barometer data to strengthen that.

## What the early recordings suggest

Directional only. The numbers behind these are in `TUNING-LOG.md`.

- The barometer reports on every fix, and weather drift over a 40-minute activity is negligible.
- Running with the phone in a pocket, single barometer readings are noisier than the phone's (already smoothed) GPS altitude. Averaging each second's readings roughly halves the noise at rest; the effect while running is still to be measured.
- Cycling with the phone in a pocket, the barometer follows a dedicated barometric bike computer's profile about twice as closely as GPS. GPS under-reads descent.
- The #181 GPS filter is too heavy for barometer data: it drops about half of a bike computer's own climb.
- The wind effect is small (1–2 m at 10 m/s) and consistent.
- Squeezing or blowing on the phone barely moved the reading on the test phone.
