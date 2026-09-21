import '../../domain/tracking/split_audio_cue.dart';
import '../units/units.dart';

/// Builds the spoken phrase for a [SplitAudioCue], per issue #125 §4 — kept
/// separate from [SplitAudioCue] itself (which is pure `domain/` and knows
/// nothing about [SpeedUnit]/formatting) and separate from
/// `SplitAudioService` (which just plays whatever text it's given). Returns
/// null when there's nothing sensible to say (e.g. a just-completed split
/// with no moving time yet, so no pace to report).
String? splitStatsAnnouncement(SplitAudioCue cue, SpeedUnit unit) {
  if (cue.kind != SplitAudioCueKind.splitChanged) return null;
  // cue.split is the *new* split at this point (see detectSplitAudioCue) —
  // the just-finished split is one index back.
  final finishedIndex = cue.split.index - 1;
  if (finishedIndex < 1) return null;
  final speech = speakSpeedOrPace(cue.avgSpeedMps, unit);
  if (speech == null) return null;
  return 'Split $finishedIndex complete. Average $speech.';
}

/// Builds the spoken correction phrase for a [SplitAudioCue], per issue #125
/// §4 — "2 minutes per kilometre too slow" / "back on target". Returns null
/// when the cue isn't a verdict cue, or there's no target/speed to compare
/// (shouldn't happen in practice, since [detectSplitAudioCue] only emits a
/// verdict cue when `splitVerdict` itself returned non-null, which already
/// requires both).
String? splitVerdictAnnouncement(SplitAudioCue cue, SpeedUnit unit) {
  if (cue.kind != SplitAudioCueKind.verdict) return null;
  final target = cue.split.targetSpeedMps;
  final avg = cue.avgSpeedMps;
  if (target == null || avg == null) return null;
  final phrase = speakSpeedDelta(avg, target, unit);
  return phrase[0].toUpperCase() + phrase.substring(1);
}
