import '../../core/units/units.dart';
import '../../domain/models/current_split_info.dart';
import '../../domain/models/live_metrics.dart';
import '../../domain/tracking/activity_mode.dart';
import '../../domain/tracking/split_target.dart';

/// Describes one metric tile: how to label it and how to derive its display
/// string from the current run state. The Phase 1 layout below is a fixed
/// list; a future customizable display just swaps in a different
/// (persisted) list of specs — the tile grid itself doesn't need to change.
class MetricSpec {
  final String id;

  /// Most tiles have a fixed label regardless of the speed/pace toggle;
  /// [_currentSplitSpec] is the exception ("Split pace" only makes sense in
  /// a pace-flavored [SpeedUnit] — it reads "Split speed" otherwise), so
  /// every spec's label is a function of [SpeedUnit] even though most ignore
  /// the argument.
  final String Function(SpeedUnit unit) label;

  /// One or two plain sentences on what the number actually measures — shown
  /// on tapping the tile. Worth spelling out for anything ambiguous (Time is
  /// wall clock, Avg is over moving time).
  final String description;

  final String Function(
    LiveMetrics metrics,
    double? currentSpeedMps,
    SpeedUnit unit,
  )
  valueOf;

  /// A second line of text under [valueOf]'s value (issue #99) — the split's
  /// size/target and, once a verdict is available, the delta text. Null for
  /// every tile except the split tiles.
  final String? Function(LiveMetrics metrics, SpeedUnit unit)? detail;

  /// Whether this tile's split is on/off its target, driving the tile's
  /// background tint (issue #99) — null when there is no target (or no
  /// tile-level notion of a target at all, i.e. every non-split tile).
  final SplitVerdict? Function(LiveMetrics metrics)? verdict;

  const MetricSpec({
    required this.id,
    required this.label,
    required this.description,
    required this.valueOf,
    this.detail,
    this.verdict,
  });
}

String Function(SpeedUnit unit) _staticLabel(String text) =>
    (_) => text;

final MetricSpec _avgSpeedSpec = MetricSpec(
  id: 'avg_speed',
  label: _staticLabel('Avg'),
  description:
      'Average pace or speed over moving time only — time spent stationary '
      'or without usable GPS is excluded.',
  valueOf: (metrics, currentSpeedMps, unit) =>
      formatSpeedOrPace(metrics.avgSpeedMps, unit),
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
  valueOf: (metrics, currentSpeedMps, unit) =>
      formatDuration(metrics.elapsedWallClock),
);

final MetricSpec _distanceSpec = MetricSpec(
  id: 'distance',
  label: _staticLabel('Distance'),
  description:
      'Distance from accepted GPS fixes. Fixes with poor accuracy, '
      'implausible jumps, or stationary jitter are not counted.',
  // Both km and miles are always shown, stacked, regardless of the run's
  // distance unit — runners commonly use both at the same time (issue #94).
  valueOf: (metrics, currentSpeedMps, unit) =>
      '${formatDistanceKm(metrics.distanceMeters)} km\n'
      '${formatDistanceMi(metrics.distanceMeters)} mi',
);

/// The current split's average speed so far, by moving time — null if the
/// split has had no moving time yet. This is the figure both the tile's
/// value and its target verdict are judged on (issue #99): never
/// instantaneous/chip speed, which is too noisy to color a tile with.
double? _currentSplitAvgSpeedMps(LiveMetrics metrics) {
  final elapsedSeconds = metrics.currentSplitElapsed.inMilliseconds / 1000;
  return elapsedSeconds <= 0
      ? null
      : metrics.currentSplitDistanceMeters / elapsedSeconds;
}

String _formatSplitSize(CurrentSplitInfo split, SpeedUnit unit) =>
    switch (split.sizeKind) {
      SplitSizeKind.distanceMeters =>
        formatSplitSizeMeters(split.size, unit.distanceUnit),
      SplitSizeKind.durationSeconds => formatSplitSizeSeconds(split.size),
    };

final MetricSpec _currentSplitSpec = MetricSpec(
  id: 'current_split',
  label: (unit) => unit.isPace ? 'Split pace' : 'Split speed',
  description:
      'Pace or speed over the current split so far, by moving time. Resets '
      'at each split boundary. When the split has a target, the tile turns '
      'green when you are within 5% of it and red otherwise, with an arrow '
      'showing which way to adjust.',
  valueOf: (metrics, currentSpeedMps, unit) =>
      formatSpeedOrPace(_currentSplitAvgSpeedMps(metrics), unit),
  detail: (metrics, unit) {
    final split = metrics.currentSplit;
    final sizeText = _formatSplitSize(split, unit);
    final countText = split.plannedCount != null
        ? '${split.index}/${split.plannedCount}'
        : '${split.index}';
    final header = 'Split $countText · $sizeText';
    final target = split.targetSpeedMps;
    if (target == null) return header;

    // The target itself stays on screen even once a delta is available —
    // otherwise the one number you're aiming for disappears the moment you
    // start moving, leaving only "how far off" with no "off from what"
    // (found on-device: the header read "1.0 km/h slow" alone, with no way
    // to see the 5.0 km/h target that judgement was made against).
    final targetText = formatTargetForEditing(target, unit);
    final avg = _currentSplitAvgSpeedMps(metrics);
    if (avg == null) return '$header @ $targetText';
    return '$header @ $targetText\n${formatSpeedDelta(avg, target, unit)}';
  },
  verdict: (metrics) => splitVerdict(
    avgSpeedMps: _currentSplitAvgSpeedMps(metrics),
    targetSpeedMps: metrics.currentSplit.targetSpeedMps,
    elapsedInSplit: metrics.currentSplitElapsed,
  ),
);

/// How much of the current split is left — a countdown of remaining time
/// (time-kind split) or remaining distance and an estimated time (distance-
/// kind split, estimated from this split's own average pace so far). Added
/// after real on-device testing showed there was no way to tell how far
/// into (or how much was left of) a split without doing mental maths
/// against the elapsed-so-far/target size shown elsewhere on screen.
final MetricSpec _remainingSpec = MetricSpec(
  id: 'split_remaining',
  label: _staticLabel('Remaining'),
  description:
      'How much of the current split is left. For a distance split, the '
      'time is estimated from this split\'s own average pace so far, so it '
      'settles in as the split gets underway and may jump early on.',
  valueOf: (metrics, currentSpeedMps, unit) {
    final split = metrics.currentSplit;
    switch (split.sizeKind) {
      case SplitSizeKind.durationSeconds:
        final remaining =
            Duration(milliseconds: (split.size * 1000).round()) -
            metrics.currentSplitElapsed;
        return formatDuration(remaining.isNegative ? Duration.zero : remaining);
      case SplitSizeKind.distanceMeters:
        final remainingMeters = split.size - metrics.currentSplitDistanceMeters;
        if (remainingMeters <= 0) {
          return '${formatSplitSizeMeters(0, unit.distanceUnit)}\n--:--';
        }
        final distanceText = formatSplitSizeMeters(
          remainingMeters,
          unit.distanceUnit,
        );
        final avgSpeed = _currentSplitAvgSpeedMps(metrics);
        if (avgSpeed == null || avgSpeed <= 0) {
          return '$distanceText\n--:--';
        }
        final etaSeconds = remainingMeters / avgSpeed;
        return '$distanceText\n${formatDuration(Duration(milliseconds: (etaSeconds * 1000).round()))}';
    }
  },
);

final MetricSpec _lastSplitSpec = MetricSpec(
  id: 'last_split',
  label: (unit) => unit.isPace ? 'Last split pace' : 'Last split speed',
  description:
      'Average pace or speed for the most recently completed split. For a '
      'time-based split preference every split has the same fixed duration, '
      // #78: showing that duration told the user nothing new — pace/speed
      // is the number that actually varies split-to-split there.
      'so pace/speed (not duration) is what actually varies split-to-split. '
      'When the split had a target, green/red shows whether it was met.',
  valueOf: (metrics, currentSpeedMps, unit) {
    final last = metrics.lastCompletedSplit;
    if (last == null) return formatSpeedOrPace(null, unit);
    // Split.index is already 1-based (see MetricsEngine).
    return '#${last.index}  ${formatSpeedOrPace(last.avgSpeedMps, unit)}';
  },
  detail: (metrics, unit) {
    final last = metrics.lastCompletedSplit;
    final target = last?.targetSpeedMps;
    if (last == null || target == null) return null;
    return formatSpeedDelta(last.avgSpeedMps, target, unit);
  },
  verdict: (metrics) {
    final last = metrics.lastCompletedSplit;
    if (last == null) return null;
    // splitVerdict still applies its grace threshold against the split's
    // own duration — for any split long enough to be worth targeting in
    // practice this always passes, since a completed split's average is
    // already its final, settled figure (unlike the in-progress split
    // tile, whose grace exists because its average is still noisy this
    // early). A custom plan could in principle define a split shorter than
    // the grace period, in which case it simply shows no verdict, the same
    // as it would have while in progress.
    return splitVerdict(
      avgSpeedMps: last.avgSpeedMps,
      targetSpeedMps: last.targetSpeedMps,
      elapsedInSplit: last.duration,
    );
  },
);

/// Cycling has no notion of a 1km "split pace" the way running does — swapped
/// for max speed instead. Follows the same speed unit (km/h vs mph) as every
/// other tile, driven by the run's split preference (issue #94) rather than
/// a manual toggle — cycling mode hides pace entirely (see LiveRunScreen),
/// so [unit] is always a speed-flavored member here, never a pace one.
final MetricSpec _maxSpeedSpec = MetricSpec(
  id: 'max_speed',
  label: _staticLabel('Max speed'),
  description: 'Fastest speed between two accepted GPS fixes this ride.',
  valueOf: (metrics, currentSpeedMps, unit) {
    final maxSpeedMps = metrics.maxSpeedMps;
    if (maxSpeedMps == null) return '--.-';
    return unit.distanceUnit == DistanceUnit.mi
        ? '${formatMph(maxSpeedMps)} mph'
        : '${formatKmh(maxSpeedMps)} km/h';
  },
);

final MetricSpec _elevationGainSpec = MetricSpec(
  id: 'elevation_gain',
  label: (unit) => unit.distanceUnit == DistanceUnit.mi
      ? 'Elevation gain (ft)'
      : 'Elevation gain (m)',
  description:
      'Total climb from GPS altitude between accepted fixes — a rough live '
      'figure; the server computes a smoothed one after upload.',
  valueOf: (metrics, currentSpeedMps, unit) =>
      unit.distanceUnit == DistanceUnit.mi
      ? formatFeet(metrics.elevationGainMeters)
      : formatMeters(metrics.elevationGainMeters),
);

/// The Phase 1 static layout, used for [ActivityMode.running]. `avg_speed`,
/// `elapsed`, `distance` are shared with [_cyclingMetricSpecs] — only the two
/// pace-oriented split tiles differ.
final List<MetricSpec> _runningMetricSpecs = [
  _avgSpeedSpec,
  _elapsedSpec,
  _distanceSpec,
  _remainingSpec,
  _currentSplitSpec,
  _lastSplitSpec,
];

/// [ActivityMode.cycling] swaps the two split-pace tiles (which cycling mode
/// hides the whole speed/pace toggle for — pace isn't a cycling concept)
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
  // Walking is tagged separately from running (issue #129) but shares its
  // tile layout — pace is just as relevant on foot whether walking or
  // running.
  ActivityMode.running || ActivityMode.walking => _runningMetricSpecs,
  ActivityMode.cycling => _cyclingMetricSpecs,
};
