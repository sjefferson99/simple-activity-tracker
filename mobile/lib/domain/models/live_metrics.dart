import 'split.dart';

/// Snapshot of a run's metrics at a point in time. Produced by
/// [MetricsEngine] from accepted track points and pause history.
class LiveMetrics {
  final Duration elapsed;
  final double distanceMeters;
  final double? currentSpeedMps;
  final double? avgSpeedMps;
  final List<Split> completedSplits;

  /// Elapsed moving time and distance covered within the split still
  /// in progress (i.e. since the last completed split boundary).
  final Duration currentSplitElapsed;
  final double currentSplitDistanceMeters;

  const LiveMetrics({
    required this.elapsed,
    required this.distanceMeters,
    required this.currentSpeedMps,
    required this.avgSpeedMps,
    required this.completedSplits,
    required this.currentSplitElapsed,
    required this.currentSplitDistanceMeters,
  });

  static const zero = LiveMetrics(
    elapsed: Duration.zero,
    distanceMeters: 0,
    currentSpeedMps: null,
    avgSpeedMps: null,
    completedSplits: [],
    currentSplitElapsed: Duration.zero,
    currentSplitDistanceMeters: 0,
  );

  Split? get lastCompletedSplit =>
      completedSplits.isEmpty ? null : completedSplits.last;
}
