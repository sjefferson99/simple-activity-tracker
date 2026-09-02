import '../../core/units/units.dart';
import '../../domain/models/live_metrics.dart';

/// Describes one metric tile: how to label it and how to derive its display
/// string from the current run state. The Phase 1 layout below is a fixed
/// list; a future customizable display just swaps in a different
/// (persisted) list of specs — the tile grid itself doesn't need to change.
class MetricSpec {
  final String id;
  final String label;
  final String Function(LiveMetrics metrics, double? currentSpeedMps, bool useKmh) valueOf;

  const MetricSpec({required this.id, required this.label, required this.valueOf});
}

String _speedOrPace(double? mps, bool useKmh) {
  if (mps == null) return useKmh ? '--.-' : '--:--';
  return useKmh ? formatKmh(mps) : formatPace(paceSecPerKmFromMps(mps));
}

final List<MetricSpec> defaultMetricSpecs = [
  MetricSpec(
    id: 'avg_speed',
    label: 'Avg',
    valueOf: (metrics, currentSpeedMps, useKmh) =>
        _speedOrPace(metrics.avgSpeedMps, useKmh),
  ),
  MetricSpec(
    id: 'elapsed',
    label: 'Time',
    valueOf: (metrics, currentSpeedMps, useKmh) => formatDuration(metrics.elapsed),
  ),
  MetricSpec(
    id: 'distance',
    label: 'Distance (km)',
    valueOf: (metrics, currentSpeedMps, useKmh) =>
        formatDistanceKm(metrics.distanceMeters),
  ),
  MetricSpec(
    id: 'current_split',
    label: 'Split pace',
    valueOf: (metrics, currentSpeedMps, useKmh) {
      final elapsedSeconds = metrics.currentSplitElapsed.inMilliseconds / 1000;
      if (elapsedSeconds <= 0) return _speedOrPace(null, useKmh);
      final speed = metrics.currentSplitDistanceMeters / elapsedSeconds;
      return _speedOrPace(speed, useKmh);
    },
  ),
  MetricSpec(
    id: 'last_split',
    label: 'Last split',
    valueOf: (metrics, currentSpeedMps, useKmh) {
      final last = metrics.lastCompletedSplit;
      if (last == null) return '--:--';
      return formatDuration(last.duration);
    },
  ),
];
