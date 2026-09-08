import '../../core/units/units.dart';
import '../../domain/models/live_metrics.dart';
import '../../domain/tracking/activity_mode.dart';

/// Describes one metric tile: how to label it and how to derive its display
/// string from the current run state. The Phase 1 layout below is a fixed
/// list; a future customizable display just swaps in a different
/// (persisted) list of specs — the tile grid itself doesn't need to change.
class MetricSpec {
  final String id;

  /// Most tiles have a fixed label regardless of the km/h ⇄ min/km toggle;
  /// [_currentSplitSpec] is the exception ("Split pace" only makes sense in
  /// min/km — it reads "Split speed" in km/h mode), so every spec's label is
  /// a function of [useKmh] even though most ignore the argument.
  final String Function(bool useKmh) label;

  /// One or two plain sentences on what the number actually measures — shown
  /// on tapping the tile. Worth spelling out for anything ambiguous (Time is
  /// wall clock, Avg is over moving time).
  final String description;

  final String Function(
    LiveMetrics metrics,
    double? currentSpeedMps,
    bool useKmh,
  )
  valueOf;

  const MetricSpec({
    required this.id,
    required this.label,
    required this.description,
    required this.valueOf,
  });
}

String Function(bool useKmh) _staticLabel(String text) => (_) => text;

String _speedOrPace(double? mps, bool useKmh) {
  if (mps == null) return useKmh ? '--.-' : '--:--';
  return useKmh ? formatKmh(mps) : formatPace(paceSecPerKmFromMps(mps));
}

final MetricSpec _avgSpeedSpec = MetricSpec(
  id: 'avg_speed',
  label: _staticLabel('Avg'),
  description:
      'Average pace or speed over moving time only — time spent stationary '
      'or without usable GPS is excluded.',
  valueOf: (metrics, currentSpeedMps, useKmh) =>
      _speedOrPace(metrics.avgSpeedMps, useKmh),
);

/// Wall-clock since Start (minus pauses), not moving time — a tile that
/// froze whenever GPS was weak or the user stood still read as a broken app.
/// Avg pace deliberately stays on moving time (Strava's "moving pace").
final MetricSpec _elapsedSpec = MetricSpec(
  id: 'elapsed',
  label: _staticLabel('Time'),
  description:
      'Time since you pressed Start, not counting pauses. Keeps counting '
      'while you are stationary or have no GPS fix.',
  valueOf: (metrics, currentSpeedMps, useKmh) =>
      formatDuration(metrics.elapsedWallClock),
);

final MetricSpec _distanceSpec = MetricSpec(
  id: 'distance',
  label: _staticLabel('Distance'),
  description:
      'Distance from accepted GPS fixes. Fixes with poor accuracy, '
      'implausible jumps, or stationary jitter are not counted.',
  valueOf: (metrics, currentSpeedMps, useKmh) =>
      '${formatDistanceKm(metrics.distanceMeters)} km / '
      '${formatDistanceMi(metrics.distanceMeters)} mi',
);

final MetricSpec _currentSplitSpec = MetricSpec(
  id: 'current_split',
  label: (useKmh) => useKmh ? 'Split speed' : 'Split pace',
  description:
      'Pace or speed over the current split so far, by moving time. Resets '
      'at each split boundary.',
  valueOf: (metrics, currentSpeedMps, useKmh) {
    final elapsedSeconds = metrics.currentSplitElapsed.inMilliseconds / 1000;
    if (elapsedSeconds <= 0) return _speedOrPace(null, useKmh);
    final speed = metrics.currentSplitDistanceMeters / elapsedSeconds;
    return _speedOrPace(speed, useKmh);
  },
);

final MetricSpec _lastSplitSpec = MetricSpec(
  id: 'last_split',
  label: _staticLabel('Last split'),
  description: 'Moving time taken for the most recently completed split.',
  valueOf: (metrics, currentSpeedMps, useKmh) {
    final last = metrics.lastCompletedSplit;
    if (last == null) return '--:--';
    // Split.index is already 1-based (see MetricsEngine).
    return '#${last.index}  ${formatDuration(last.duration)}';
  },
);

/// Cycling has no notion of a 1km "split pace" the way running does — swapped
/// for max speed instead. Always shows km/h regardless of the [useKmh]
/// toggle (which cycling mode forces to km/h anyway — see LiveRunScreen).
final MetricSpec _maxSpeedSpec = MetricSpec(
  id: 'max_speed',
  label: _staticLabel('Max speed'),
  description: 'Fastest speed between two accepted GPS fixes this ride.',
  valueOf: (metrics, currentSpeedMps, useKmh) {
    final maxSpeedMps = metrics.maxSpeedMps;
    return maxSpeedMps == null ? '--.-' : formatKmh(maxSpeedMps);
  },
);

final MetricSpec _elevationGainSpec = MetricSpec(
  id: 'elevation_gain',
  label: _staticLabel('Elevation gain (m)'),
  description:
      'Total climb from GPS altitude between accepted fixes — a rough live '
      'figure; the server computes a smoothed one after upload.',
  valueOf: (metrics, currentSpeedMps, useKmh) =>
      formatMeters(metrics.elevationGainMeters),
);

/// The Phase 1 static layout, used for [ActivityMode.running]. `avg_speed`,
/// `elapsed`, `distance` are shared with [_cyclingMetricSpecs] — only the two
/// pace-oriented split tiles differ.
final List<MetricSpec> _runningMetricSpecs = [
  _avgSpeedSpec,
  _elapsedSpec,
  _distanceSpec,
  _currentSplitSpec,
  _lastSplitSpec,
];

/// [ActivityMode.cycling] swaps the two split-pace tiles (which cycling mode
/// hides the whole km/h ⇄ min/km toggle for — pace isn't a cycling concept)
/// for max speed and elevation gain.
final List<MetricSpec> _cyclingMetricSpecs = [
  _avgSpeedSpec,
  _elapsedSpec,
  _distanceSpec,
  _maxSpeedSpec,
  _elevationGainSpec,
];

/// Kept for callers that haven't migrated to [metricSpecsFor] yet — equal to
/// the running-mode layout, which was the only layout before cycling mode
/// got its own tiles.
final List<MetricSpec> defaultMetricSpecs = _runningMetricSpecs;

List<MetricSpec> metricSpecsFor(ActivityMode mode) => switch (mode) {
  ActivityMode.running => _runningMetricSpecs,
  ActivityMode.cycling => _cyclingMetricSpecs,
};
