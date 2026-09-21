import '../../domain/models/current_split_info.dart';
import '../../domain/tracking/split_audio_cue.dart';
import '../../domain/tracking/split_target.dart';
import '../units/units.dart';

/// Builds the spoken phrase announcing a split's target, e.g. "Target 5
/// kilometres per hour" or "No target" — used both for
/// [splitStartAnnouncement] (a split boundary mid-run) and directly by
/// `LiveRunController`'s immediate start-of-activity cue (issue #125
/// follow-up, 2026-09-21), which announces split 1's target the same way
/// before any GPS tick has even arrived. Kept separate from [SplitAudioCue]
/// (pure `domain/`, no [SpeedUnit]/formatting) and from `SplitAudioService`
/// (just plays whatever text it's given).
String targetAnnouncement(CurrentSplitInfo split, SpeedUnit unit) {
  final target = split.targetSpeedMps;
  if (target == null) return 'No target.';
  final speech = speakSpeedOrPace(target, unit);
  return speech == null ? 'No target.' : 'Target $speech.';
}

/// Speaks a split's size for the "now on rolling splits" announcement, e.g.
/// "1 kilometre" or "1 minute 30 seconds".
String _speakSplitSize(CurrentSplitInfo split, SpeedUnit unit) =>
    switch (split.sizeKind) {
      SplitSizeKind.distanceMeters =>
        speakSplitSize(split.size, unit.distanceUnit),
      SplitSizeKind.durationSeconds => speakSplitSizeSeconds(split.size),
    };

/// Builds the spoken phrase for a [SplitAudioCueKind.splitChanged] cue
/// (issue #125 follow-up, 2026-09-21 — replaces the old "Splt N complete,
/// average X" end-of-split summary): the new split's target, prefixed with
/// a short "now on rolling splits of Y" when [SplitAudioCue.rolledOntoRollingSplits]
/// is true (a custom plan's splits have just been exhausted). Returns null
/// when [cue] isn't a splitChanged cue.
String? splitStartAnnouncement(SplitAudioCue cue, SpeedUnit unit) {
  if (cue.kind != SplitAudioCueKind.splitChanged) return null;
  final target = targetAnnouncement(cue.split, unit);
  if (!cue.rolledOntoRollingSplits) return target;
  final sizeSpeech = _speakSplitSize(cue.split, unit);
  return 'Now on rolling splits of $sizeSpeech. $target';
}

/// Builds the spoken correction phrase for a [SplitAudioCueKind.verdict]
/// cue, per issue #125's follow-up spec — "Pace is 2 minutes per kilometre
/// too slow, target pace is 5 minutes per kilometre" / "Back on target."
/// (no target restated on returning to target — "fine" is the whole point).
/// Returns null when [cue] isn't a verdict cue, or there's no target/speed
/// to compare (shouldn't happen in practice, since [detectSplitAudioCue]
/// only emits a verdict cue when `splitVerdict` itself returned non-null,
/// which already requires both).
String? splitVerdictAnnouncement(SplitAudioCue cue, SpeedUnit unit) {
  if (cue.kind != SplitAudioCueKind.verdict) return null;
  final target = cue.split.targetSpeedMps;
  final avg = cue.avgSpeedMps;
  if (target == null || avg == null) return null;

  // Checked against cue.verdict directly, not by string-matching
  // speakSpeedDelta's "back on target" return value — that string is meant
  // for concatenating into the too-fast/too-slow phrase below, not as an
  // API contract callers pattern-match on; cue.verdict is the actual typed
  // source of truth for which case this is.
  if (cue.verdict == SplitVerdict.onTarget) return 'Back on target.';

  final delta = speakSpeedDelta(avg, target, unit);
  final noun = unit.isPace ? 'Pace' : 'Speed';
  final targetSpeech = speakSpeedOrPace(target, unit);
  return '$noun is $delta, target ${unit.isPace ? 'pace' : 'speed'} is $targetSpeech.';
}
