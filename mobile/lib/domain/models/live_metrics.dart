import 'current_split_info.dart';
import 'split.dart';

/// Snapshot of a run's metrics at a point in time. Produced by
/// [MetricsEngine] from accepted track points and pause history.
class LiveMetrics {
  /// **Moving** time: only advances while GPS segments are being accepted.
  /// Feeds [avgSpeedMps] and the server's `moving_seconds`. Not what the
  /// "Time" tile shows — that's [elapsedWallClock].
  final Duration elapsed;

  /// Wall-clock time since Start minus explicit pauses (see `RunClock`).
  /// Stamped in by the controller, not [MetricsEngine], because it must keep
  /// counting even when no fix is accepted (or arrives at all).
  final Duration elapsedWallClock;

  final double distanceMeters;
  final double? avgSpeedMps;
  final List<Split> completedSplits;

  /// Elapsed moving time and distance covered within the split still
  /// in progress (i.e. since the last completed split boundary).
  final Duration currentSplitElapsed;
  final double currentSplitDistanceMeters;

  /// The split currently in progress: its index, size, and target (issue
  /// #99). Never null once a run has a [MetricsEngine] — even
  /// [LiveMetrics.zero] carries split 1 of whatever plan the engine was
  /// constructed with as its default.
  final CurrentSplitInfo currentSplit;

  /// Highest accepted instantaneous/segment speed seen so far this run. Null
  /// until at least one segment has been accepted, so "no data yet" isn't
  /// confused with "stationary". Unaffected by pause/resume, same as
  /// [distanceMeters].
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
    required this.avgSpeedMps,
    required this.completedSplits,
    required this.currentSplitElapsed,
    required this.currentSplitDistanceMeters,
    required this.currentSplit,
    this.maxSpeedMps,
    this.elevationGainMeters = 0,
    this.elapsedWallClock = Duration.zero,
  });

  LiveMetrics copyWith({Duration? elapsedWallClock}) => LiveMetrics(
    elapsed: elapsed,
    elapsedWallClock: elapsedWallClock ?? this.elapsedWallClock,
    distanceMeters: distanceMeters,
    avgSpeedMps: avgSpeedMps,
    completedSplits: completedSplits,
    currentSplitElapsed: currentSplitElapsed,
    currentSplitDistanceMeters: currentSplitDistanceMeters,
    currentSplit: currentSplit,
    maxSpeedMps: maxSpeedMps,
    elevationGainMeters: elevationGainMeters,
  );

  static const zero = LiveMetrics(
    elapsed: Duration.zero,
    distanceMeters: 0,
    avgSpeedMps: null,
    completedSplits: [],
    currentSplitElapsed: Duration.zero,
    currentSplitDistanceMeters: 0,
    currentSplit: CurrentSplitInfo(
      index: 1,
      plannedCount: null,
      sizeKind: SplitSizeKind.distanceMeters,
      size: 1000,
      targetSpeedMps: null,
    ),
    maxSpeedMps: null,
    elevationGainMeters: 0,
  );

  Split? get lastCompletedSplit =>
      completedSplits.isEmpty ? null : completedSplits.last;
}
