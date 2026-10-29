import '../models/current_split_info.dart';
import '../models/live_metrics.dart';
import 'split_target.dart';

/// Live-only hysteresis on the split verdict (issue #154). Once the split in
/// progress reads on target, it stays on target until its average leaves the
/// band by more than [liveVerdictExitMargin] as well; off-target re-enters
/// at the plain band edge. Without this, an average hovering at the band
/// edge flips on/off target every few fixes, beeping each time.
///
/// Completed splits (and the server's history) use the plain band: their
/// average is final, so there's nothing left to flip.

/// The exit margin at the start of a split, as a fraction of target speed:
/// twice the band (so leaving on-target early needs ±3.9% in total).
///
/// Tuned by replaying 17 real targeted activities (116 splits) through
/// tool/replay_split_audio.dart: these settings cut verdict beeps from 408
/// (plain band) to 287. Wider margins cut a little more (3× the band: 255)
/// at the cost of staying green further off target.
const double liveVerdictMaxExitMargin = splitTargetTolerance * 2;

/// The exit margin it shrinks to once the split's average has settled:
/// half the band (±1.95% in total, about ±6 s/km at 5:00/km).
const double liveVerdictMinExitMargin = splitTargetTolerance / 2;

/// Split progress up to which the full [liveVerdictMaxExitMargin] applies.
const double _fullMarginUntilProgress = 0.15;

/// The extra margin needed to leave on target at [progress] (0 at the
/// split's start, 1 at its end). GPS error in the split's average is
/// roughly (metres of error ÷ distance covered so far), so the margin
/// falls as 1/progress: full until 15% of the split, down to its minimum
/// (a quarter of the full margin) from 60% on.
double liveVerdictExitMargin(double progress) {
  if (progress <= _fullMarginUntilProgress) return liveVerdictMaxExitMargin;
  final scaled = liveVerdictMaxExitMargin * _fullMarginUntilProgress / progress;
  return scaled < liveVerdictMinExitMargin ? liveVerdictMinExitMargin : scaled;
}

/// [splitVerdict] with hysteresis against [previous], the verdict this same
/// split had on the last tick.
SplitVerdict? liveSplitVerdict({
  required double? avgSpeedMps,
  required double? targetSpeedMps,
  required Duration elapsedInSplit,
  required double progress,
  required SplitVerdict? previous,
}) {
  final plain = splitVerdict(
    avgSpeedMps: avgSpeedMps,
    targetSpeedMps: targetSpeedMps,
    elapsedInSplit: elapsedInSplit,
  );
  if (plain == null || plain == SplitVerdict.onTarget) return plain;
  if (previous != SplitVerdict.onTarget) return plain;

  // Non-null: splitVerdict returned a verdict, so both were usable.
  final ratio = avgSpeedMps! / targetSpeedMps!;
  final exitEdge = splitTargetTolerance + liveVerdictExitMargin(progress);
  return (ratio - 1).abs() <= exitEdge ? SplitVerdict.onTarget : plain;
}

/// The split in progress's average speed so far, by moving time, or null
/// before it has any moving time.
double? currentSplitAvgSpeedMps(LiveMetrics metrics) {
  final elapsedSeconds = metrics.currentSplitElapsed.inMilliseconds / 1000;
  return elapsedSeconds <= 0 ? null : metrics.currentSplitDistanceMeters / elapsedSeconds;
}

/// How far through the split in progress [metrics] is, 0..1, by distance or
/// moving time according to the split's kind.
double currentSplitProgress(LiveMetrics metrics) {
  final split = metrics.currentSplit;
  if (split.size <= 0) return 1;
  final done = switch (split.sizeKind) {
    SplitSizeKind.distanceMeters => metrics.currentSplitDistanceMeters,
    SplitSizeKind.durationSeconds => metrics.currentSplitElapsed.inMilliseconds / 1000,
  };
  return (done / split.size).clamp(0.0, 1.0);
}

/// Remembers the split in progress's last live verdict, so each tick can
/// apply [liveSplitVerdict]'s hysteresis. One per run; owned by
/// LiveRunController, whose result both the Split tile and the audio cues
/// read (via [LiveMetrics.currentSplitVerdict]) so they can never disagree.
///
/// [update] is idempotent for the same metrics, so it's safe to call on
/// every read of the run's metrics, not only on new GPS fixes.
class LiveSplitVerdictTracker {
  int? _splitIndex;
  SplitVerdict? _verdict;

  SplitVerdict? update(LiveMetrics metrics) {
    if (metrics.currentSplit.index != _splitIndex) {
      _splitIndex = metrics.currentSplit.index;
      _verdict = null;
    }
    _verdict = liveSplitVerdict(
      avgSpeedMps: currentSplitAvgSpeedMps(metrics),
      targetSpeedMps: metrics.currentSplit.targetSpeedMps,
      elapsedInSplit: metrics.currentSplitElapsed,
      progress: currentSplitProgress(metrics),
      previous: _verdict,
    );
    return _verdict;
  }

  void reset() {
    _splitIndex = null;
    _verdict = null;
  }
}
