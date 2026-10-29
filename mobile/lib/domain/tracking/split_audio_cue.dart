import '../models/current_split_info.dart';
import '../models/live_metrics.dart';
import 'live_split_verdict.dart';
import 'split_target.dart';

/// The two kinds of audio cue issue #125 defines — "a new split has
/// started" (including the very first split of the run), or a beep pattern
/// reflecting a [SplitVerdict] transition (2 beeps too fast, 3 beeps too
/// slow, 1 long beep back on target — see [SplitAudioService.playVerdict]).
/// [SplitAudioCue.verdict] is only set for [verdict].
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

  /// The split this cue is about — always the split now in progress (issue
  /// #125 follow-up, 2026-09-21: a [SplitAudioCueKind.splitChanged] cue used
  /// to also carry the just-*finished* split's average for a spoken
  /// end-of-split summary; that summary was removed in favour of announcing
  /// the *new* split's target instead, so this is simply
  /// [LiveMetrics.currentSplit] at the tick the cue fired, for both kinds).
  final CurrentSplitInfo split;

  /// This split's average speed so far (by moving time), for the verdict
  /// TTS's "by how much" figure. Null if there has been no moving time yet,
  /// or for a [SplitAudioCueKind.splitChanged] cue, which doesn't use it.
  final double? avgSpeedMps;

  /// True iff this [SplitAudioCueKind.splitChanged] cue is the exact tick a
  /// custom plan's splits are exhausted and tracking rolls on at the plan's
  /// base rolling size (issue #99's roll-on behaviour) — i.e.
  /// `split.plannedCount != null && split.index == split.plannedCount! + 1`.
  /// Always false for a [SplitAudioCueKind.verdict] cue.
  final bool rolledOntoRollingSplits;

  const SplitAudioCue._({
    required this.kind,
    required this.verdict,
    required this.split,
    required this.avgSpeedMps,
    required this.rolledOntoRollingSplits,
  });

  const SplitAudioCue.splitChanged({
    required CurrentSplitInfo split,
    required bool rolledOntoRollingSplits,
  }) : this._(
         kind: SplitAudioCueKind.splitChanged,
         verdict: null,
         split: split,
         avgSpeedMps: null,
         rolledOntoRollingSplits: rolledOntoRollingSplits,
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
         rolledOntoRollingSplits: false,
       );

  @override
  String toString() =>
      'SplitAudioCue($kind, verdict: $verdict, splitIndex: ${split.index}, '
      'rolledOntoRollingSplits: $rolledOntoRollingSplits)';
}

/// No verdict *cue* (beep or spoken correction) until a split has this much
/// moving time — the tile's colour still shows from [splitVerdictGrace]
/// (issue #154 follow-up). With the ±1.3% band, a split's average flips
/// most in its first 20-30 s; replaying 112 real completed targeted splits,
/// 30 s cut verdict cues from 279 (2.5/split) to 184 (1.6/split), while
/// waiting 60 s only saved ~30 more and silenced a third of short splits.
const Duration splitVerdictAudioGrace = Duration(seconds: 30);

/// True iff [split] is the exact roll-on tick — see
/// [SplitAudioCue.rolledOntoRollingSplits].
bool _isRollOnTick(CurrentSplitInfo split) =>
    split.plannedCount != null && split.index == split.plannedCount! + 1;

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
///
/// Verdict cues are held until [splitVerdictAudioGrace]; the tick that
/// crosses it announces the verdict in force then (even if it was already
/// showing on screen), and only genuine transitions after that.
///
/// [previous] being null (the very first tick of a run) never itself
/// produces a cue — split 1's start is announced separately and immediately
/// on Start, by [LiveRunController]'s own start-of-activity cue (which
/// carries the same "target for this split" content), so this function
/// would otherwise double up with it the moment the first GPS tick arrives.
SplitAudioCue? detectSplitAudioCue({
  required LiveMetrics? previous,
  required LiveMetrics current,
}) {
  if (previous == null) return null;

  if (current.currentSplit.index > previous.currentSplit.index) {
    return SplitAudioCue.splitChanged(
      split: current.currentSplit,
      rolledOntoRollingSplits: _isRollOnTick(current.currentSplit),
    );
  }

  // The live verdict, hysteresis included (issue #154) — the same one the
  // Split tile shows, so a beep always matches the tile's colour change.
  final currentVerdict = current.currentSplitVerdict;
  if (currentVerdict == null) return null;
  if (current.currentSplitElapsed < splitVerdictAudioGrace) return null;

  // On the tick that crosses the audio grace, nothing has been announced
  // for this split yet, so the verdict in force is news whatever it was.
  final crossedAudioGrace = previous.currentSplitElapsed < splitVerdictAudioGrace;
  if (!crossedAudioGrace && currentVerdict == previous.currentSplitVerdict) {
    return null;
  }

  return SplitAudioCue.verdict(
    verdict: currentVerdict,
    split: current.currentSplit,
    avgSpeedMps: currentSplitAvgSpeedMps(current),
  );
}
