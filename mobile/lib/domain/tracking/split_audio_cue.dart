import '../models/current_split_info.dart';
import '../models/live_metrics.dart';
import 'split_target.dart';

/// The two kinds of audio cue issue #125 defines — a plain "a new split has
/// started" beep, or a beep pattern reflecting a [SplitVerdict] transition
/// (2 beeps too fast, 3 beeps too slow, 1 long beep back on target — see
/// [SplitAudioService.playVerdict]). [SplitAudioCue.verdict] is only set for
/// [verdict].
enum SplitAudioCueKind { splitChanged, verdict }

/// One audio cue to play, as decided by [detectSplitAudioCue] from a single
/// tick's metrics transition. Carries enough of the current split's state
/// for the optional text-to-speech announcements (issue #125 §4) to build a
/// spoken phrase from, without re-deriving it from [LiveMetrics] a second
/// time in the caller.
class SplitAudioCue {
  final SplitAudioCueKind kind;

  /// Set iff [kind] is [SplitAudioCueKind.verdict].
  final SplitVerdict? verdict;

  /// The split this cue is about — the split that just finished for
  /// [SplitAudioCueKind.splitChanged] (i.e. [LiveMetrics.lastCompletedSplit]
  /// at the tick the cue fired), or the split now in progress for
  /// [SplitAudioCueKind.verdict].
  final CurrentSplitInfo split;

  /// This split's average speed so far (by moving time), for TTS. Null if
  /// there has been no moving time yet.
  final double? avgSpeedMps;

  const SplitAudioCue._({
    required this.kind,
    required this.verdict,
    required this.split,
    required this.avgSpeedMps,
  });

  const SplitAudioCue.splitChanged({
    required CurrentSplitInfo split,
    required double? avgSpeedMps,
  }) : this._(
         kind: SplitAudioCueKind.splitChanged,
         verdict: null,
         split: split,
         avgSpeedMps: avgSpeedMps,
       );

  const SplitAudioCue.verdict({
    required SplitVerdict verdict,
    required CurrentSplitInfo split,
    required double? avgSpeedMps,
  }) : this._(
         kind: SplitAudioCueKind.verdict,
         verdict: verdict,
         split: split,
         avgSpeedMps: avgSpeedMps,
       );

  @override
  String toString() =>
      'SplitAudioCue($kind, verdict: $verdict, splitIndex: ${split.index})';
}

double? _avgSpeedMps(LiveMetrics metrics) {
  final elapsedSeconds = metrics.currentSplitElapsed.inMilliseconds / 1000;
  return elapsedSeconds <= 0
      ? null
      : metrics.currentSplitDistanceMeters / elapsedSeconds;
}

SplitVerdict? _verdictOf(LiveMetrics metrics) => splitVerdict(
  avgSpeedMps: _avgSpeedMps(metrics),
  targetSpeedMps: metrics.currentSplit.targetSpeedMps,
  elapsedInSplit: metrics.currentSplitElapsed,
);

/// Diffs [previous] against [current] and returns the single audio cue to
/// play for this tick, or null if nothing changed that's worth a cue.
///
/// This is deliberately a diff against the *previous* tick, not a level
/// check against [current] alone — [splitVerdict] itself stays steady for
/// many consecutive ticks while a runner is off pace, and re-announcing that
/// every tick would be constant beeping rather than a correction cue. Only a
/// genuine transition (including the grace period elapsing, i.e. null →
/// non-null) produces a cue.
///
/// Split-boundary changes always take priority over a same-tick verdict
/// change (issue #125 plan §1 D2) — playing both would overlap two beep
/// sounds. The verdict beep for the new split can still fire on a later tick
/// once that split's own grace period elapses.
SplitAudioCue? detectSplitAudioCue({
  required LiveMetrics? previous,
  required LiveMetrics current,
}) {
  if (previous == null) return null;

  if (current.currentSplit.index > previous.currentSplit.index) {
    final justFinished = current.lastCompletedSplit;
    return SplitAudioCue.splitChanged(
      split: current.currentSplit,
      avgSpeedMps: justFinished?.avgSpeedMps,
    );
  }

  final previousVerdict = _verdictOf(previous);
  final currentVerdict = _verdictOf(current);
  if (currentVerdict == null || currentVerdict == previousVerdict) {
    return null;
  }

  return SplitAudioCue.verdict(
    verdict: currentVerdict,
    split: current.currentSplit,
    avgSpeedMps: _avgSpeedMps(current),
  );
}
