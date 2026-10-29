/// Whether a split's average speed so far is on, above, or below its
/// target (issue #99). Judged on **average speed over moving time** — the
/// same figure the Split pace/speed tile already shows — never on
/// instantaneous/chip speed, which is too noisy to color a tile with.
enum SplitVerdict { onTarget, tooFast, tooSlow }

/// A split is "on target" within this fraction of its target speed either
/// way — e.g. a 5:00/km target (3.333 m/s) is on target from 3.290 to
/// 3.377 m/s (±1.3%, about ±4 s/km; ±6 s/mi at 8:00/mi).
///
/// One *relative* band for pace and speed targets alike (issue #152): pace
/// is 1/speed, so a percentage is the same physical band in either unit,
/// and GPS error in a split's average is itself roughly relative (metres of
/// error ÷ distance covered). A fixed s/km band would be a different
/// percentage at every pace. Mirrored by the server's
/// `_SPLIT_TARGET_TOLERANCE` (app/analysis/v1.py) — change both together,
/// and bump its ANALYSIS_VERSION so stored history is re-judged.
const double splitTargetTolerance = 0.013;

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
