import '../geo_math.dart';
import '../models/live_metrics.dart';
import '../models/split.dart';
import '../models/track_point.dart';

const double _splitDistanceMeters = 1000;
const double _maxAcceptableAccuracyMeters = 25;
const Duration _currentSpeedWindow = Duration(seconds: 3);

/// Accumulates accepted track points into live run metrics: elapsed time,
/// distance, current/average speed, and interpolated 1km splits.
///
/// Pure Dart, no Flutter dependency — fed one point at a time via [addPoint]
/// so it never has to recompute a whole run's history from scratch.
class MetricsEngine {
  final List<TrackPoint> _recentPoints = [];
  TrackPoint? _lastAccepted;

  Duration _movingElapsed = Duration.zero;
  double _totalDistanceMeters = 0;

  double _splitStartDistanceMeters = 0;
  Duration _splitStartElapsed = Duration.zero;
  final List<Split> _completedSplits = [];

  LiveMetrics _metrics = LiveMetrics.zero;
  LiveMetrics get metrics => _metrics;

  /// Feeds one more accepted GPS fix into the engine. Points with worse
  /// accuracy than [_maxAcceptableAccuracyMeters] are dropped entirely —
  /// call site should not call this for paused/rejected points.
  void addPoint(TrackPoint point) {
    if (point.accuracyMeters > _maxAcceptableAccuracyMeters) return;

    final previous = _lastAccepted;
    _lastAccepted = point;
    _recentPoints.add(point);
    _pruneRecentPoints(point.timestamp);

    if (previous == null) {
      _metrics = _buildMetrics();
      return;
    }

    final segmentDistance = haversineDistanceMeters(previous, point);
    final segmentDuration = point.timestamp.difference(previous.timestamp);
    if (segmentDuration <= Duration.zero) {
      _metrics = _buildMetrics();
      return;
    }

    _applySegment(segmentDistance, segmentDuration);
    _metrics = _buildMetrics();
  }

  /// Call when tracking pauses/resumes so elapsed/distance calculations
  /// don't bridge the gap as if it were continuous movement.
  void resetSegmentAnchor() {
    _lastAccepted = null;
    _recentPoints.clear();
  }

  void _applySegment(double segmentDistance, Duration segmentDuration) {
    var remainingDistance = segmentDistance;
    var elapsedBefore = _movingElapsed;

    while (_totalDistanceMeters + remainingDistance >=
            _splitStartDistanceMeters + _splitDistanceMeters &&
        remainingDistance > 0) {
      final distanceIntoSplit =
          (_splitStartDistanceMeters + _splitDistanceMeters) - _totalDistanceMeters;
      final fraction = distanceIntoSplit / remainingDistance;
      final crossingDuration = segmentDuration * fraction;
      final crossingElapsed = elapsedBefore + crossingDuration;

      final splitDuration = crossingElapsed - _splitStartElapsed;
      _completedSplits.add(Split(
        index: _completedSplits.length + 1,
        duration: splitDuration,
        // A split covering measurable distance in no measurable time would
        // divide by zero; report 0 rather than an infinite pace.
        avgSpeedMps: splitDuration.inMilliseconds > 0
            ? _splitDistanceMeters / splitDuration.inMilliseconds * 1000
            : 0,
      ));

      _totalDistanceMeters += distanceIntoSplit;
      elapsedBefore = crossingElapsed;
      _splitStartDistanceMeters = _totalDistanceMeters;
      _splitStartElapsed = crossingElapsed;

      remainingDistance -= distanceIntoSplit;
      segmentDuration = segmentDuration - crossingDuration;
    }

    _totalDistanceMeters += remainingDistance;
    _movingElapsed = elapsedBefore + segmentDuration;
  }

  /// Trims the smoothing window to [_currentSpeedWindow], but always keeps
  /// the last two fixes. When fixes arrive slower than the window (weak GPS,
  /// doze), a strict cutoff would leave a single point and make current
  /// speed permanently null; falling back to the last pair still gives a
  /// usable — if less smoothed — reading.
  void _pruneRecentPoints(DateTime latestTimestamp) {
    final cutoff = latestTimestamp.subtract(_currentSpeedWindow);
    while (_recentPoints.length > 2 &&
        _recentPoints.first.timestamp.isBefore(cutoff)) {
      _recentPoints.removeAt(0);
    }
  }

  double? _currentSpeedMps() {
    if (_recentPoints.length < 2) return null;
    final oldest = _recentPoints.first;
    final newest = _recentPoints.last;
    return speedMpsBetween(oldest, newest);
  }

  double? _avgSpeedMps() {
    if (_movingElapsed <= Duration.zero) return null;
    return _totalDistanceMeters / _movingElapsed.inMilliseconds * 1000;
  }

  LiveMetrics _buildMetrics() {
    return LiveMetrics(
      elapsed: _movingElapsed,
      distanceMeters: _totalDistanceMeters,
      currentSpeedMps: _currentSpeedMps(),
      avgSpeedMps: _avgSpeedMps(),
      completedSplits: List.unmodifiable(_completedSplits),
      currentSplitElapsed: _movingElapsed - _splitStartElapsed,
      currentSplitDistanceMeters: _totalDistanceMeters - _splitStartDistanceMeters,
    );
  }
}
