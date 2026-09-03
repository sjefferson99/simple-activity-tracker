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

  /// Highest accepted instantaneous/segment speed seen so far this run. Null
  /// until at least one segment has been accepted — mirrors [currentSpeedMps]
  /// rather than defaulting to 0, so "no data yet" isn't confused with
  /// "stationary". Unaffected by pause/resume, same as [distanceMeters].
  final double? maxSpeedMps;

  /// Cumulative positive elevation change across accepted points (sum of
  /// each accepted-point-to-next-accepted-point altitude increase, ignoring
  /// decreases and points with no elevation reading) — a rough live
  /// indicator, not the server's smoothed figure. Unaffected by pause/resume,
  /// same as [distanceMeters].
  final double elevationGainMeters;

  const LiveMetrics({
    required this.elapsed,
    required this.distanceMeters,
    required this.currentSpeedMps,
    required this.avgSpeedMps,
    required this.completedSplits,
    required this.currentSplitElapsed,
    required this.currentSplitDistanceMeters,
    this.maxSpeedMps,
    this.elevationGainMeters = 0,
  });

  static const zero = LiveMetrics(
    elapsed: Duration.zero,
    distanceMeters: 0,
    currentSpeedMps: null,
    avgSpeedMps: null,
    completedSplits: [],
    currentSplitElapsed: Duration.zero,
    currentSplitDistanceMeters: 0,
    maxSpeedMps: null,
    elevationGainMeters: 0,
  );

  Split? get lastCompletedSplit =>
      completedSplits.isEmpty ? null : completedSplits.last;
}
