/// Whether a split's [CurrentSplitInfo.size] is a distance (metres) or a
/// duration (seconds) — mirrors [SplitPreference.kind] being either a
/// distance kind or [SplitKind.timeMin], but named independently here since
/// this file is consumed by display code that shouldn't need to reach into
/// `SplitPreference` just to know which one `size` means.
enum SplitSizeKind { distanceMeters, durationSeconds }

/// Describes the split currently in progress (issue #99): its 1-based
/// index, how many splits the plan has defined (null for a rolling plan,
/// which has no fixed count), its size, and its target speed if any.
///
/// Stamped into [LiveMetrics.currentSplit] by [MetricsEngine] on every
/// [MetricsEngine.addPoint] call — see [MetricsEngine._buildMetrics].
class CurrentSplitInfo {
  /// 1-based — equal to `completedSplits.length + 1`.
  final int index;

  /// Number of splits explicitly planned by a custom [SplitPlan], or null
  /// for a rolling plan (see [SplitPlan.plannedCount]).
  final int? plannedCount;

  final SplitSizeKind sizeKind;

  /// Metres if [sizeKind] is [SplitSizeKind.distanceMeters], seconds if
  /// [SplitSizeKind.durationSeconds].
  final double size;

  /// Target average speed for this split in m/s, or null for no target.
  final double? targetSpeedMps;

  const CurrentSplitInfo({
    required this.index,
    required this.plannedCount,
    required this.sizeKind,
    required this.size,
    required this.targetSpeedMps,
  });

  @override
  bool operator ==(Object other) =>
      other is CurrentSplitInfo &&
      other.index == index &&
      other.plannedCount == plannedCount &&
      other.sizeKind == sizeKind &&
      other.size == size &&
      other.targetSpeedMps == targetSpeedMps;

  @override
  int get hashCode =>
      Object.hash(index, plannedCount, sizeKind, size, targetSpeedMps);
}
