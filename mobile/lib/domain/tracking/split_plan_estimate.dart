import 'split_plan.dart';
import 'split_preference.dart';

/// What one planned split works out to at its target (issue #134): a
/// distance-kind split's size is a distance, so its target gives a time; a
/// time-kind split's size is a duration, so its target gives a distance.
/// The "other" dimension is null when the split has no target.
class SplitEstimate {
  final double? distanceMeters;
  final double? durationSeconds;

  const SplitEstimate({this.distanceMeters, this.durationSeconds});
}

/// Estimates one split of [kind] sized [size] (metres or seconds, per
/// [SplitPlan]'s convention) at [targetSpeedMps].
SplitEstimate estimateSplit(
  SplitKind kind,
  double size,
  double? targetSpeedMps,
) {
  final target = (targetSpeedMps != null && targetSpeedMps > 0)
      ? targetSpeedMps
      : null;
  if (kind == SplitKind.timeMin) {
    return SplitEstimate(
      durationSeconds: size,
      distanceMeters: target == null ? null : size * target,
    );
  }
  return SplitEstimate(
    distanceMeters: size,
    durationSeconds: target == null ? null : size / target,
  );
}

/// The summed estimate across a custom plan's splits. The dimension the
/// plan is measured in (distance for km/mi splits, time for minute splits)
/// is always known; the derived dimension is only summed when every split
/// has a target — a partial sum would silently understate the total, so it
/// is null instead and [untargetedCount] says how many splits are missing.
class SplitPlanTotals {
  final double? distanceMeters;
  final double? durationSeconds;
  final int untargetedCount;

  const SplitPlanTotals({
    required this.distanceMeters,
    required this.durationSeconds,
    required this.untargetedCount,
  });
}

SplitPlanTotals estimateCustomPlanTotals(SplitPlan plan) {
  var distance = 0.0;
  var duration = 0.0;
  var untargeted = 0;
  for (final split in plan.customSplits) {
    final estimate = estimateSplit(
      plan.base.kind,
      split.size,
      split.targetSpeedMps,
    );
    if (estimate.distanceMeters == null || estimate.durationSeconds == null) {
      untargeted++;
    }
    distance += estimate.distanceMeters ?? 0;
    duration += estimate.durationSeconds ?? 0;
  }
  final isTimeKind = plan.base.kind == SplitKind.timeMin;
  return SplitPlanTotals(
    distanceMeters: (isTimeKind && untargeted > 0) ? null : distance,
    durationSeconds: (!isTimeKind && untargeted > 0) ? null : duration,
    untargetedCount: untargeted,
  );
}
