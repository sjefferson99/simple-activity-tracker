import 'dart:async';
import 'dart:developer' as developer;

import 'package:audioplayers/audioplayers.dart' as ap;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_tts/flutter_tts.dart' as tts;
import 'package:meta/meta.dart';

import '../../domain/tracking/split_target.dart';

/// Constructed once per app session (not per run) so the underlying
/// `audioplayers`/`flutter_tts` plugin initialization cost — and any audio
/// focus/session category setup — is paid once, not once per Start tap. See
/// `LiveRunController`, the sole reader.
final splitAudioServiceProvider = Provider<SplitAudioService>((ref) {
  final service = AudioPlayersSplitAudioService();
  ref.onDispose(() => unawaited(service.dispose()));
  return service;
});

/// Plays split audio cues (issue #125): a short beep for a plain split
/// change, a 2/3-beep or single-long-beep pattern for a target-verdict
/// change, and optional spoken phrases. Wraps `audioplayers`/`flutter_tts`
/// the same way `core/location`/`core/files` wrap their own plugins —
/// package types never leak past this file.
abstract interface class SplitAudioService {
  /// A short beep on Start (issue #125 follow-up) — fires immediately,
  /// independent of GPS/split state, purely so the user can confirm their
  /// audio/volume/Bluetooth routing is actually working before they start
  /// moving (the split-changed/verdict beeps may not fire for a while, or
  /// at all indoors with no GPS — this doesn't wait on any of that).
  Future<void> playActivityStarted();

  Future<void> playSplitChanged();

  /// [SplitVerdict.tooFast] → two beeps, [SplitVerdict.tooSlow] → three
  /// beeps, [SplitVerdict.onTarget] → one long beep ("split time OK again"
  /// per issue #125).
  Future<void> playVerdict(SplitVerdict verdict);

  Future<void> speak(String text);

  Future<void> dispose();
}

/// One self-contained WAV per cue — the double/triple-beep patterns are
/// baked into the file at generation time (`docs/generate_split_beeps.py`),
/// not produced by chaining repeated `play()` calls at runtime. This is a
/// deliberate design change (2026-09-21, issue #125 follow-up): both an
/// earlier "repeat one short beep on the same player" and a later "repeat
/// it on a fresh player each time" approach silently dropped the second and
/// third beeps of a pattern on a real device (Samsung S23) — every
/// individual `play()` call completed with no error, but only the first
/// beep was ever audible. Baking the whole pattern into one file means
/// exactly one `play()` call per cue, so there's nothing left for the
/// platform layer to drop mid-pattern. See mobile/assets/audio/README.md.
const _singleBeepAsset = 'audio/beep_single.wav';
const _doubleBeepAsset = 'audio/beep_double.wav';
const _tripleBeepAsset = 'audio/beep_triple.wav';
const _longBeepAsset = 'audio/beep_long.wav';

/// Gap after a beep before any spoken phrase for that same cue starts — on
/// a real device (S23) the beep and TTS were audibly overlapping despite
/// going through the same serialized queue, because `AudioPlayer.play()`
/// resolves once playback *starts*, not once it *finishes* (see
/// `_playBeep`'s own fix, which waits for real completion). This half-second
/// pause is on top of that fix, not instead of it — belt and braces, and
/// it's also just a clearer listening experience to have a beat between the
/// beep and the words that follow it.
const _beepToSpeechGap = Duration(milliseconds: 500);

/// Cap on any single setup platform call in [AudioPlayersSplitAudioService._initialize]
/// — generous for a real device, but finite, so a platform call that never
/// resolves (suspected cause of a real on-device bug: no beep/TTS at all on
/// a cold app process, no exception, nothing logged past this point) can't
/// silently block every cue for the rest of the app session.
const _initStepTimeout = Duration(seconds: 3);

/// Temporary diagnostic logging for a real class of on-device audio bugs
/// (a cold-process race, and a dropped-beeps-in-a-pattern bug — see git log)
/// — visible via `adb logcat -s SplitAudio:V`. Worth keeping past the
/// immediate diagnosis (cheap, and this is exactly the kind of
/// silent-failure-prone plugin-glue code where a future regression would
/// otherwise be just as hard to diagnose as these were).
void _log(String message) =>
    developer.log(message, name: 'SplitAudio');

class AudioPlayersSplitAudioService implements SplitAudioService {
  AudioPlayersSplitAudioService()
    : _beepPlayer = ap.AudioPlayer(playerId: 'split_audio_beep'),
      _tts = tts.FlutterTts() {
    // Seeds _queue with the async setup below instead of Future.value(), so
    // every real play/speak call — including the very first one — actually
    // waits for setup to finish rather than racing it. Found on a real
    // device (S23): the very first activity's start-cue after a fresh app
    // launch played with default/uninitialized audio routing (technically
    // audible but on the wrong stream — same symptom as the sonification-
    // routing bug below), while every subsequent run that session worked
    // fine. Root cause was this constructor firing setAudioContext/
    // awaitSpeakCompletion/setIosAudioCategory with `unawaited(...)` — those
    // are real async platform-channel calls, and `splitAudioServiceProvider`
    // is lazily constructed on the very first `ref.read`, which happens
    // moments before the first cue plays. Nothing raced on a *second* run
    // because the provider (and this constructor) had already run and
    // finished during the first one.
    _queue = _initialize();
  }

  Future<void> _initialize() async {
    _log('initialize: start');
    try {
      // Media/music content type+usage, not sonification: on a real device
      // (S23) the beep played successfully at the OS level (confirmed in
      // logcat — MediaPlayer prepared/started/completed it cleanly, no
      // error) but was inaudible, while TTS on the same device was heard
      // fine — almost certainly because sonification/assistanceSonification
      // routes through a different (and separately, possibly lower/muted)
      // volume stream than media. `music`/`media` puts the beep on the same
      // stream as everything else this service plays (and the same one a
      // user's music volume slider already controls), so it can't go
      // silently mute on its own. gainTransient (pause, not duck, background
      // audio — issue #135: a ducked-under pace cue was hard to make out
      // over music/podcasts) is unaffected by this — it's an orthogonal
      // focus request, not the stream choice.
      await _beepPlayer
          .setAudioContext(
            ap.AudioContext(
              android: const ap.AudioContextAndroid(
                contentType: ap.AndroidContentType.music,
                usageType: ap.AndroidUsageType.media,
                audioFocus: ap.AndroidAudioFocus.gainTransient,
              ),
              // AVAudioSessionCategory.ambient can't take exclusive-focus
              // options — only playback/playAndRecord/multiRoute can
              // (asserted by AudioContextIOS itself; caught on a real
              // device, see git log). playback is the right one here:
              // output-only, silenced by the ring/silent switch like
              // ambient. No duckOthers/mixWithOthers option means other
              // apps' audio is paused/interrupted for the cue's duration
              // (issue #135), not just lowered in volume, and resumes once
              // this session's playback ends.
              iOS: ap.AudioContextIOS(
                category: ap.AVAudioSessionCategory.playback,
              ),
            ),
          )
          .timeout(_initStepTimeout);
      _log('initialize: setAudioContext done');

      // NOT awaited with the rest of setup: on a real device (S23), a cold
      // app process's very first activity had no beep/TTS at all, no
      // exception, nothing past this point in the log — consistent with
      // this specific platform call hanging rather than completing or
      // throwing. flutter_tts's own docs describe awaitSpeakCompletion as
      // pairing with a completion *handler*, which this service doesn't
      // register (speak() doesn't need to wait for its own completion here
      // — _enqueue's chain already serializes calls); registering it may be
      // what the engine is waiting on. Given TTS worked without it in
      // earlier on-device testing, and the whole point is to stop init from
      // ever being able to block every future cue permanently, it's fired
      // and forgotten rather than awaited — a timeout here would still leave
      // _initialize() itself uncompleted for up to _initStepTimeout for no
      // benefit, since nothing downstream depends on it finishing first.
      unawaited(
        _tts
            .awaitSpeakCompletion(true)
            .timeout(_initStepTimeout)
            .then((_) => _log('initialize: awaitSpeakCompletion done'))
            .catchError((Object e) => _log('initialize: awaitSpeakCompletion FAILED: $e')),
      );

      // .ambient is inherently mixable regardless of options (per
      // flutter_tts's own doc comment on the enum) — dropping duckOthers
      // alone would leave speech still mixed quietly under other audio
      // rather than pausing it. .playback (same category the beep now
      // uses, see above) is nonmixable by default, so spoken cues actually
      // interrupt/pause background audio too, not just the beeps.
      await _tts
          .setIosAudioCategory(tts.IosTextToSpeechAudioCategory.playback, [])
          .timeout(_initStepTimeout);
      _log('initialize: setIosAudioCategory done');
    } catch (e, st) {
      // Never let a setup failure/timeout permanently block every future
      // cue this session (see _enqueue's own catchError, which only
      // protects individual play/speak calls, not this method) — log it and
      // let the queue continue so later calls still get a chance, even if
      // this specific setup step never completed.
      _log('initialize: FAILED: $e\n$st');
    }
    _log('initialize: end');
  }

  final ap.AudioPlayer _beepPlayer;
  final tts.FlutterTts _tts;

  /// Serializes every beep/speech call through this service, so a beep and
  /// the TTS for the same cue never overlap. Seeded with _initialize()
  /// itself (see the constructor's comment) so the first real call also
  /// waits for setup, not just later ones. A later call waits for the one
  /// ahead of it rather than interrupting it.
  late Future<void> _queue;

  Future<void> _enqueue(Future<void> Function() action) {
    final next = _queue.then((_) => action()).catchError((Object e) {
      // A cue failing to play (no audio focus, TTS engine unavailable,
      // etc.) must never surface into LiveRunController — same "swallow and
      // move on" contract as the periodic GPX flush's catchError.
      _log('enqueue: action FAILED: $e');
    });
    _queue = next;
    return next;
  }

  /// Plays [asset] and waits for it to actually finish sounding — not just
  /// for playback to *start*, which is all `AudioPlayer.play()` itself
  /// resolves on. `onPlayerComplete` fires once the clip genuinely
  /// finishes; the timeout is a defensive fallback only, well past any
  /// asset's real duration, so a missed platform completion event can never
  /// wedge the queue indefinitely. Every cue is now exactly one call to
  /// this — see the module doc above for why multi-beep patterns are now
  /// baked into their own asset rather than produced by calling this
  /// repeatedly.
  Future<void> _playBeep(String asset) async {
    _log('playBeep: $asset start');
    final completed = _beepPlayer.onPlayerComplete.first;
    await _beepPlayer.play(ap.AssetSource(asset));
    _log('playBeep: $asset play() returned, awaiting completion');
    await completed.timeout(const Duration(seconds: 2), onTimeout: () {});
    _log('playBeep: $asset done');
  }

  @override
  Future<void> playActivityStarted() {
    _log('playActivityStarted: called');
    return _enqueue(() => _playBeep(_singleBeepAsset));
  }

  @override
  Future<void> playSplitChanged() => _enqueue(() => _playBeep(_singleBeepAsset));

  @override
  Future<void> playVerdict(SplitVerdict verdict) => _enqueue(() {
    _log('playVerdict: ${verdict.name}');
    final asset = switch (verdict) {
      SplitVerdict.tooFast => _doubleBeepAsset,
      SplitVerdict.tooSlow => _tripleBeepAsset,
      SplitVerdict.onTarget => _longBeepAsset,
    };
    return _playBeep(asset);
  });

  @override
  Future<void> speak(String text) => _enqueue(() async {
    // The gap is here, not in LiveRunController, because every speak() call
    // in practice follows a beep for the same cue (see the plan's §4
    // ordering rule) — centralizing it means every caller gets the pause
    // for free rather than each one remembering to insert it. A speak()
    // that happens to be the very first thing in the queue (nothing played
    // yet) still gets a harmless half-second pre-roll — never wrong, just
    // occasionally a beat more silence than strictly necessary.
    await Future<void>.delayed(_beepToSpeechGap);
    _log('speak: "$text" start');
    await _tts.speak(text);
    _log('speak: "$text" done');
  });

  @override
  Future<void> dispose() async {
    await _queue;
    await _beepPlayer.dispose();
    await _tts.stop();
  }
}

/// A no-op implementation used before a real `AudioPlayersSplitAudioService`
/// is constructed, and by widget/controller tests that don't want to touch
/// real platform audio channels.
@visibleForTesting
class NoopSplitAudioService implements SplitAudioService {
  final List<String> calls = [];

  @override
  Future<void> playActivityStarted() async {
    calls.add('playActivityStarted');
  }

  @override
  Future<void> playSplitChanged() async {
    calls.add('playSplitChanged');
  }

  @override
  Future<void> playVerdict(SplitVerdict verdict) async {
    calls.add('playVerdict:${verdict.name}');
  }

  @override
  Future<void> speak(String text) async {
    calls.add('speak:$text');
  }

  @override
  Future<void> dispose() async {}
}
