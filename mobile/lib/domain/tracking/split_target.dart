/// Whether a split's average speed so far is on, above, or below its
/// target (issue #99). Judged on **average speed over moving time** — the
/// same figure the Split pace/speed tile already shows — never on
/// instantaneous/chip speed, which is too noisy to color a tile with.
enum SplitVerdict { onTarget, tooFast, tooSlow }

/// A split is "on target" within this fraction of its target speed either
/// way — e.g. a 5:00/km target (3.333 m/s) is on target from 3.167 to
/// 3.500 m/s (±5%).
const double splitTargetTolerance = 0.05;

/// No verdict is given until a split has at least this much moving time —
/// otherwise every split opens red for its first few seconds, since a
/// runner's pace hasn't stabilized yet.
const Duration splitVerdictGrace = Duration(seconds: 10);

/// Compares [avgSpeedMps] (the split's average speed so far, by moving
/// time) against [targetSpeedMps]. Returns null when there is no target, no
/// speed yet (the split has had no moving time), or [elapsedInSplit] is
/// still within [splitVerdictGrace].
SplitVerdict? splitVerdict({
  required double? avgSpeedMps,
  required double? targetSpeedMps,
  required Duration elapsedInSplit,
}) {
  if (targetSpeedMps == null || targetSpeedMps <= 0) return null;
  if (avgSpeedMps == null) return null;
  if (elapsedInSplit < splitVerdictGrace) return null;

  final ratio = avgSpeedMps / targetSpeedMps;
  if (ratio > 1 + splitTargetTolerance) return SplitVerdict.tooFast;
  if (ratio < 1 - splitTargetTolerance) return SplitVerdict.tooSlow;
  return SplitVerdict.onTarget;
}
