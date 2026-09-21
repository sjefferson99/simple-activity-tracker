# Split audio cues plan — issue #125

Status: **drafted 2026-09-20, not yet approved for implementation.**

Handoff plan for whoever implements it — read CLAUDE.md first (architecture rules, the
commit-approval rule, the on-device verification habit, and the "Server dev/test
workflow" section's mobile-equivalent spirit: build with tests, verify on a real device,
get sign-off before commit/push/PR), then this file end to end. Also skim
[docs/SPLIT-TARGETS-PLAN.md](SPLIT-TARGETS-PLAN.md) — this issue is a thin audio layer on
top of #99's `splitVerdict()`/`CurrentSplitInfo`/`SplitPlan` machinery, not a new metrics
concept, and reuses that plan's conventions (pure-Dart domain logic, a dedicated
persisted-settings controller, on-device verification before sign-off).

Scope, from [issue #125](https://github.com/sjefferson99/simple-activity-tracker/issues/125):

1. A simple **beep on split change** (a new split has started).
2. A **beep pattern on target-verdict change**, using the exact same on/too-fast/too-slow
   logic that already drives the split tiles' red/green tint (issue #99): **two beeps**
   for too fast, **three beeps** for too slow, **one long beep** for "back on target".
3. **Optional text-to-speech** announcing the split's duration/speed/pace.
4. **Optional text-to-speech** for a too-fast/too-slow verdict, including by how much.

## 1. Decisions (made with the owner on 2026-09-20 — do not re-open)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Audio packages | **`audioplayers` for beeps, `flutter_tts` for speech.** Two well-maintained, separately-scoped packages rather than trying to synthesize tones out of a TTS engine (unreliable/platform-inconsistent) or take on a heavier player than needed. |
| D2 | Cue priority when a split boundary and a verdict transition coincide | **The split-change beep always wins that tick.** On a split boundary, play only the single "split changed" beep, even if the new split immediately has a different verdict than the old one's last verdict. The verdict beep can still fire later once the new split clears `splitVerdictGrace` and settles on a real verdict. Avoids overlapping beep sounds. |
| D3 | Cycling mode | **No audio cues in cycling mode at all — same visibility boundary as the split tiles.** `MetricsEngine` still computes `currentSplit`/verdicts for cycling under the hood, but the live screen already hides every split-pace tile for cycling (issue #99 D8: "no split definition for cycling"). Audio cues must not surface via sound what the screen deliberately doesn't show on screen — `LiveRunController` simply skips invoking the cue detector when `ActivityMode` is cycling, the same way the UI layer already swaps tile lists by mode. The detector itself is not mode-aware; the caller is. |

## 2. What already exists (reuse, don't rebuild)

- `domain/tracking/split_target.dart`'s `splitVerdict()` — the on/tooFast/tooSlow
  judgement, ±5% tolerance, 10s moving-time grace period. **The audio cue's verdict logic
  is exactly this function** — no new threshold/grace logic gets invented for audio.
- `domain/models/current_split_info.dart`'s `CurrentSplitInfo` — split index, size kind,
  size, target — already stamped into `LiveMetrics.currentSplit` on every
  `MetricsEngine.addPoint()`.
- `domain/models/split.dart`'s `Split` (`lastCompletedSplit`) — a completed split's final
  index/duration/avgSpeedMps/targetSpeedMps, for the "split just finished" announcement.
- `core/units/units.dart`'s `formatSpeedOrPace()`/`formatSpeedDelta()` — the same text the
  tiles already compute; TTS reuses the *numbers*, not the compact tile strings (see §4).
- `LiveRunController._emitActive()` (`features/live_run/live_run_controller.dart`) —
  already recomputes `LiveMetrics` on every accepted GPS fix and every 1s tick
  (`_onTick`/`_onSample`). This is the one place a transition can be observed — there is
  no separate "split just changed" event anywhere in the codebase today, so it has to be
  derived here by diffing against the previous tick's `LiveMetrics`.
- `core/tracking/split_plan_controller.dart`'s `SplitPlanController` — the persistence
  pattern (secure storage, JSON, `_userHasSelected` guard against a race with an
  in-flight `_load()`) that the new audio-settings controller follows.

## 3. New pure-Dart domain logic

### 3.1 `domain/tracking/split_audio_cue.dart`

A stateless diff function, mirroring how `splitVerdict()` itself is a pure function of
its inputs rather than something stateful:

```dart
enum SplitAudioCueKind { splitChanged, verdict }

class SplitAudioCue {
  final SplitAudioCueKind kind;
  final SplitVerdict? verdict; // set iff kind == verdict
  // + whatever the announcement needs: split index, size kind/size, target,
  //   avg speed so far, delta — see §4.
}

/// Compares [previous] and [current] LiveMetrics snapshots and returns the
/// single cue to play for this tick, or null for no change worth announcing.
/// Per D2, a split-index change always wins over a same-tick verdict change.
SplitAudioCue? detectSplitAudioCue({
  required LiveMetrics? previous,
  required LiveMetrics current,
});
```

Rules (mirrors #99's own grace/hysteresis reasoning, applied to *transitions* rather than
level-triggering every tick):

- `previous == null` (first sample of a run) → no cue. Nothing to compare against, and a
  beep the instant GPS acquires would be surprising.
- `current.currentSplit.index > (previous?.currentSplit.index ?? 1)` → `splitChanged`,
  regardless of anything else that also changed this tick (D2).
- Otherwise, if `splitVerdict(...)` computed from `current` differs from
  `splitVerdict(...)` computed from `previous` (including `null` → non-null, i.e. the
  grace period just elapsed, and non-null → `null`, e.g. a re-anchor/pause cleared moving
  time) → `verdict` cue carrying the new verdict.
  - **A `null` new verdict does not itself produce a beep pattern** — there's nothing in
    the issue's spec for "no verdict" (only too-fast/too-slow/on-target have defined beep
    patterns), so this transition is silent. Confirm with the owner if this feels wrong
    in practice during on-device testing (§8).
  - `onTarget` fires the **single long beep** described as "split time OK again" — i.e.
    only a transition *into* `onTarget` from `tooFast`/`tooSlow` plays it, not staying on
    target from the start of a split all the way through (would otherwise beep once at
    the end of `splitVerdictGrace` even for a runner who was never off pace, which reads
    as a false "correction" cue). Worth confirming against the issue's actual intent
    during implementation review — the wording ("split time OK again") suggests a
    recovery cue, matching this reading.
- Both a split change and a verdict change in the same tick → `splitChanged` only (D2).

### 3.2 Unit tests

Table-driven, feeding synthetic `LiveMetrics` pairs (constructed directly — no GPS/engine
involved) through `detectSplitAudioCue`, covering:

- No previous metrics → null.
- Split index unchanged, verdict unchanged → null.
- Split index incremented, verdict also changed → `splitChanged` (not `verdict`).
- `null` → `tooFast`/`tooSlow`/`onTarget` (grace period elapsing) → `verdict` cue.
- `tooFast` → `onTarget` and `tooSlow` → `onTarget` → `verdict(onTarget)`.
- `onTarget` → `tooFast`, `onTarget` → `tooSlow`, `tooFast` → `tooSlow` directly → each
  produces the corresponding `verdict` cue.
- Non-null verdict → `null` verdict (e.g. pause/resume clearing `currentSplitElapsed`) →
  per the rule above, confirm this is silent (or produces whatever cue the owner confirms
  in the open question above).
- Same verdict sustained across many ticks → null every time after the first transition
  (this is the "don't re-beep every second while off pace" requirement — the whole reason
  this is a diff against `previous`, not a level check against `current` alone).

## 4. TTS content

The issue asks for **optional** speech for (a) split duration/speed/pace and (b)
too-fast/too-slow "by how much". Two independent toggles (§6), each producing its own
phrase, both triggered from the same `detectSplitAudioCue` result rather than a separate
polling mechanism:

- On `splitChanged` (i.e. a split just completed, or the very first split started) with
  the "announce split stats" toggle on: speak the **just-completed** split's stats from
  `LiveMetrics.lastCompletedSplit` — index, duration, avg pace/speed. Reuses the same
  numbers `_lastSplitSpec` (`features/live_run/metric_spec.dart`) shows, phrased for
  speech rather than a compact tile string, e.g. "Split 3 complete. 4 minutes 12 seconds.
  Average 5 30 per kilometre." New formatting helper(s) in `core/units/units.dart`
  (alongside the existing `formatSpeedOrPace`/`formatSpeedDelta`) rather than ad hoc
  string-building in the audio service — keeps unit-formatting logic in the one file the
  architecture rules already designate for it.
- On `verdict` cue with the "announce pace correction" toggle on: speak the verdict and
  magnitude, e.g. "2 minutes per kilometre too slow" / "1 kilometre per hour too fast" /
  "Back on target." — built from the same `formatSpeedDelta()` inputs the tile's detail
  line already uses (`_currentSplitSpec.detail` in `metric_spec.dart`), not a new
  computation.
- If **both** toggles are on and a beep is also playing (§5), TTS is queued to start only
  after the beep pattern finishes — never overlapped. `SplitAudioService` (§5) owns this
  ordering; the controller just calls it once per cue.

## 5. `core/audio/split_audio_service.dart`

Wraps `audioplayers`/`flutter_tts` the same way `core/location`/`core/files` wrap their
respective plugins — plugin types never leak past this file, matching the architecture
rule that `core/`/`domain/` stay pure/isolated elsewhere in the app.

```dart
abstract interface class SplitAudioService {
  Future<void> playSplitChanged();
  Future<void> playVerdict(SplitVerdict verdict); // 2 beeps / 3 beeps / 1 long beep
  Future<void> speak(String text);
  Future<void> dispose();
}
```

- Beep clips: short bundled asset files (e.g. `assets/audio/beep_short.mp3`,
  `beep_long.mp3`) under a new `mobile/assets/audio/` directory, declared in
  `pubspec.yaml`'s `flutter.assets`. Two beeps/three beeps are the short clip played
  back-to-back with a brief gap, not two separate asset files.
- `speak()` is a thin pass-through to `flutter_tts` — no SSML, plain sentences, default
  device voice/locale (no in-app language picker; out of scope per the issue).
- Must not throw into `LiveRunController` if the platform has no TTS engine available or
  audio focus can't be acquired (e.g. a phone call in progress) — swallow and log, same
  pattern as the existing periodic GPX flush's `catchError((_) {})`
  (`live_run_controller.dart`'s `_flushTimer`).
- `dispose()` releases both plugins' resources — called from
  `LiveRunController._disposeRun()`.
- Real device behavior to verify (§8), not something to guess at in code review: does a
  beep or TTS utterance duck/pause any music the runner has playing? `audioplayers`'
  default audio-focus behavior needs checking against both Android and (later) iOS —
  may need an explicit `AudioContext`/session-category configuration rather than the
  package default, which could otherwise stop the user's music entirely instead of
  briefly ducking it. Flag this as a real risk to budget time for, not a footnote.

## 6. Settings

New "Audio cues" section on the existing **Splits screen**
(`features/splits/splits_screen.dart`) — the natural home, since it's already where every
other split-behavior setting lives (split type, targets-as, plan editor), per D3 of #99's
own plan ("configuration screen for the run's split plan"). Toggles:

- **Audio cues** — master on/off (default off, so this is opt-in and doesn't surprise an
  existing user on their next run after an app update).
- **Beep on split change** — on/off.
- **Beep on target correction** (2/3/1-long pattern) — on/off; visually de-emphasized (or
  hidden) when the current plan has no targets configured at all, same spirit as the tile
  detail line only showing a target once one exists.
- **Announce split stats (speech)** — on/off.
- **Announce pace correction (speech)** — on/off; same targets-exist caveat as the beep
  toggle above.

### 6.1 `core/audio/split_audio_settings_controller.dart`

Follows `SplitPlanController`'s exact shape: a `Notifier<SplitAudioSettings>`,
`flutter_secure_storage`-backed, single JSON-encoded key, no legacy-key migration needed
(this is a new setting, not replacing an existing one the way #99 replaced the old
`SplitPreferenceController`). A plain immutable `SplitAudioSettings` value class in
`domain/tracking/` (pure Dart, `toJson`/`fromJson`/`copyWith`/`==`, matching `SplitPlan`'s
own shape) holds the five booleans above plus `SplitPlan.defaultPlan`-style defaults.

## 7. Wiring into `LiveRunController`

- New field `LiveMetrics? _previousMetricsForAudio` (or reuse the existing `state`'s
  metrics where available — needs checking against `_emitActive`'s exact call shape once
  implementation starts) updated every `_emitActive()` call.
- After computing `_currentMetrics()` in `_emitActive()`, and only when
  `_activityMode != ActivityMode.cycling` (D3) and the audio settings' master toggle is
  on: call `detectSplitAudioCue(previous: ..., current: ...)`, then dispatch to
  `SplitAudioService` per the cue kind and the individual toggles (§6).
- Cues must not fire while `RunPhase.paused` — `_onSample` already returns early on pause,
  and `_onTick` only re-emits during `RunPhase.tracking`, so this falls out for free as
  long as the cue check lives inside `_emitActive()`/its callers rather than being
  triggered by a separate timer. Confirm this holds once real code is written — don't
  assume without a test covering a fix arriving mid-pause.
- `SplitAudioService` instance created once per `LiveRunController` (or provided via a
  Riverpod provider, matching `locationServiceProvider`'s existing pattern) — not
  recreated per run, so `flutter_tts`/`audioplayers` initialization cost is paid once per
  app session, not once per Start tap.

## 8. Testing / verification

- **Unit tests** (the real logic, per §3.2): `detectSplitAudioCue` transition table, plus
  `SplitAudioSettings` JSON round-trip/default-value tests — same spirit as #99's
  `SplitPlan.fromJson` malformed-input tests.
- **Not meaningfully unit-testable**: the `audioplayers`/`flutter_tts` plugin wrapper
  itself (same class of thing as `flutter_secure_storage`/`geolocator` wrappers elsewhere
  in this codebase) — verified on-device instead, not mocked into a false sense of
  coverage.
- `flutter analyze` clean, Snyk clean on `mobile/`, per every other change in this repo.
- **On-device pass required before sign-off** (a real walk/run, matching #99's own
  verification bar in CLAUDE.md), specifically confirming:
  - Beep fires exactly once at each split boundary, with no cue lost or duplicated when a
    boundary and a verdict transition would otherwise coincide (D2).
  - Correct beep count/pattern entering too-fast vs too-slow, and the single long beep on
    recovering to on-target — not a beep every tick while sustained off-target.
  - No audio cues at all in cycling mode (D3) — confirm silence, not just "tiles hidden".
  - TTS phrasing is intelligible and its timing doesn't collide with or get cut off by a
    beep (§4's ordering).
  - Whether beeps/TTS interrupt or duck any music/podcast audio already playing — real
    risk flagged in §5, needs a real answer from a real device, not an assumption.
  - Settings toggles persist across relaunch and take effect immediately on an
    already-active run (or confirm+document if they're deliberately fixed-for-the-run,
    matching how `_activityMode`/`_splitPlan` are captured once at `start()` — needs an
    explicit decision during implementation, not left ambiguous).

## 9. Out of scope (not in issue #125, don't add speculatively)

- Cycling-mode audio cues (D3) — would need its own issue if ever wanted, since it has no
  split-target concept to trigger off today.
- An in-app voice/language picker for TTS — uses the device's default.
- Custom user-recorded or alternate beep sounds — one short/one long bundled asset.
- Any server-side change — this is a live-run, on-device feature only, same category as
  #99's mobile-only scope (server follow-up, if ever wanted, would be its own issue the
  way #100/#101 followed #99).
