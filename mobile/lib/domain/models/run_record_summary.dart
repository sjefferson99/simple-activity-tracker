import '../../core/units/units.dart' show DistanceUnit;
import '../tracking/split_plan.dart' show metersPerMile;
import 'current_split_info.dart';
import 'live_metrics.dart';
import 'run_record.dart';
import 'run_summary.dart';
import 'split.dart';

/// A finished run's terminal state, reconstructed from a persisted
/// [RunRecord] (issue #106) — enough for a reopened summary screen to render
/// the same tile grid/splits list a fresh finished screen would, without
/// touching [LiveRunController]'s live state machine at all.
class ReopenedRunSummary {
  final LiveMetrics metrics;
  final DistanceUnit distanceUnit;

  const ReopenedRunSummary({required this.metrics, required this.distanceUnit});
}

/// Builds a [ReopenedRunSummary] from [record]'s persisted [RunSummary].
///
/// Two fields [LiveRunFinished] normally carries aren't recoverable from
/// what's persisted, and are deliberately approximated rather than treated
/// as stored facts:
/// - `elapsed`/`elapsedWallClock` both use [RunSummary.movingSeconds] — the
///   original wall-clock time (including any paused time) isn't separately
///   persisted, so this under-counts by however long the run was paused,
///   same as a run with no pauses at all would show either way.
/// - The distance unit isn't persisted directly — inferred from the first
///   split's size instead (mile splits round to ~1609m, km splits to
///   ~1000m), defaulting to km when there's nothing to infer from (no
///   splits, or a size that matches neither).
ReopenedRunSummary reopenedRunSummaryFrom(RunRecord record) {
  final summary = record.summary;

  final completedSplits = [
    for (final split in summary.splits)
      Split(
        index: split.index,
        duration: Duration(
          milliseconds: (split.durationSeconds * 1000).round(),
        ),
        avgSpeedMps: split.avgSpeedMps,
        distanceMeters: split.distanceMeters,
        targetSpeedMps: split.targetSpeedMps,
      ),
  ];

  final elapsed = Duration(
    milliseconds: (summary.movingSeconds * 1000).round(),
  );

  final metrics = LiveMetrics(
    elapsed: elapsed,
    elapsedWallClock: elapsed,
    distanceMeters: summary.distanceMeters,
    avgSpeedMps: summary.avgSpeedMps,
    completedSplits: completedSplits,
    currentSplitElapsed: Duration.zero,
    currentSplitDistanceMeters: 0,
    // No split is "in progress" for a finished, reopened run — same
    // placeholder shape LiveMetrics.zero already uses, so the current-split
    // tiles degrade the same way they would for any run with nothing left
    // to show, not a new failure mode.
    currentSplit: CurrentSplitInfo(
      index: completedSplits.length + 1,
      plannedCount: null,
      sizeKind: SplitSizeKind.distanceMeters,
      size: 1000,
      targetSpeedMps: null,
    ),
    maxSpeedMps: summary.maxSpeedMps,
    elevationGainMeters: summary.elevationGainMeters,
  );

  return ReopenedRunSummary(
    metrics: metrics,
    distanceUnit: _inferDistanceUnit(summary.splits),
  );
}

/// Half a percent either way — comfortably wider than any GPS-derived
/// distance's expected rounding error for a plausible split, but narrow
/// enough that a genuinely different split size (a custom plan, a
/// mid-distance time split) never gets misread as a mile split by
/// coincidence.
const double _inferenceTolerance = 0.005;

/// Infers km vs. mi from the first split's recorded distance — the split
/// plan itself (the actual source of truth at record-time) isn't persisted.
/// A time-based split preference's distance varies split-to-split and won't
/// land near either constant, so this only ever narrows to mi on a confident
/// match and falls back to km (the more common default) otherwise.
DistanceUnit _inferDistanceUnit(List<RunSummarySplit> splits) {
  if (splits.isEmpty) return DistanceUnit.km;
  final firstDistance = splits.first.distanceMeters;
  final ratio = firstDistance / metersPerMile;
  final nearestWhole = ratio.roundToDouble();
  final isMileMultiple =
      nearestWhole > 0 &&
      (ratio - nearestWhole).abs() / nearestWhole <= _inferenceTolerance;
  return isMileMultiple ? DistanceUnit.mi : DistanceUnit.km;
}
