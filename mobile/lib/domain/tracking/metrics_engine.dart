import '../geo_math.dart';
import '../models/live_metrics.dart';
import '../models/split.dart';
import '../models/track_point.dart';
import 'activity_mode.dart';

const double _splitDistanceMeters = 1000;
const double _maxAcceptableAccuracyMeters = 25;
const Duration _currentSpeedWindow = Duration(seconds: 3);

/// The two plausibility thresholds [MetricsEngine] checks every accepted
/// segment against — see [MetricsEngine._isPlausibleSegment]. Per-[ActivityMode]
/// because a cyclist routinely exceeds a runner's plausible speed and can
/// cover far more distance in a sparse-fix gap (freewheeling downhill, a
/// tunnel) without it being a GPS glitch.
class _PlausibilityLimits {
  /// No one sustains this for the given activity; a segment implying more is
  /// a bad fix (e.g. a stale/default location before the GPS gets a real
  /// lock), not real motion.
  final double maxPlausibleSpeedMps;

  /// Backstop for the "a long enough gap makes anything look slow" hole in a
  /// speed-only test: a 65km jump implies a plausible ~18 m/s once the
  /// previous fix is an hour old. Set well above any distance a
  /// sparse-but-real stretch of fixes could cover (a tunnel or a
  /// backgrounded app can easily leave kilometres between consecutive
  /// fixes), so this only catches teleports.
  final double maxPlausibleSegmentMeters;

  const _PlausibilityLimits({
    required this.maxPlausibleSpeedMps,
    required this.maxPlausibleSegmentMeters,
  });

  factory _PlausibilityLimits.forMode(ActivityMode mode) => switch (mode) {
        ActivityMode.running => const _PlausibilityLimits(
            maxPlausibleSpeedMps: 12, // ~43 km/h
            maxPlausibleSegmentMeters: 20000,
          ),
        // Downhill cycling comfortably exceeds a runner's cap, and a bike can
        // cover much more ground than a runner in the same sparse-fix gap —
        // both thresholds raised accordingly. Still well short of "obviously
        // not a bike" (a car, a plane) so genuine teleports are still caught.
        ActivityMode.cycling => const _PlausibilityLimits(
            maxPlausibleSpeedMps: 25, // 90 km/h
            maxPlausibleSegmentMeters: 40000,
          ),
      };
}

/// How long a rejected fix stays eligible to be recognised as the real
/// position (see the recovery path in [MetricsEngine.addPoint]). Beyond this
/// the run is treated as having a genuine gap rather than a recoverable
/// glitch, so a stale candidate can't be resurrected minutes later.
const Duration _pendingCandidateTtl = Duration(seconds: 30);

/// How far two rejected fixes must be apart before they count as evidence
/// that the runner really is over there, rather than a GPS repeating one
/// wrong position. Above plausible fix-to-fix noise, below a running stride's
/// worth of travel between fixes.
const double _minReanchorMotionMeters = 2;

/// Accumulates accepted track points into live run metrics: elapsed time,
/// distance, current/average speed, and interpolated 1km splits.
///
/// Pure Dart, no Flutter dependency — fed one point at a time via [addPoint]
/// so it never has to recompute a whole run's history from scratch.
///
/// [mode] only affects which GPS segments are accepted as plausible motion
/// versus discarded as a bad fix — see [_PlausibilityLimits]. It does not
/// yet change how metrics are computed or displayed.
class MetricsEngine {
  final _PlausibilityLimits _limits;

  MetricsEngine({ActivityMode mode = ActivityMode.running})
      : _limits = _PlausibilityLimits.forMode(mode);

  final List<TrackPoint> _recentPoints = [];
  TrackPoint? _lastAccepted;

  /// A point rejected as an implausible jump from [_lastAccepted], kept in
  /// case it turns out [_lastAccepted] was the bad fix rather than this one —
  /// see [addPoint].
  TrackPoint? _pendingCandidate;

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

    if (previous == null) {
      _lastAccepted = point;
      _recentPoints.add(point);
      _pruneRecentPoints(point.timestamp);
      _metrics = _buildMetrics();
      return;
    }

    final segmentDistance = haversineDistanceMeters(previous, point);
    final segmentDuration = point.timestamp.difference(previous.timestamp);
    if (segmentDuration <= Duration.zero) {
      _metrics = _buildMetrics();
      return;
    }

    // A jump implying an impossible running speed is a bad fix (GPS glitch,
    // stale location before a real lock), not real motion — drop it like a
    // low-accuracy point rather than let it poison cumulative distance/speed
    // forever.
    if (!_isPlausibleSegment(segmentDistance, segmentDuration)) {
      // But keeping the anchor pinned on `previous` forever is just as wrong
      // if `previous` was actually the bad fix (e.g. one stale point far from
      // where the run really is) — every subsequent good point would then
      // look like an impossible jump and be rejected too, quarantining the
      // rest of the run. Two consecutive rejects that agree with *each other*
      // say the anchor was the outlier, so re-anchor onto them.
      final pending = _pendingCandidate;
      final sincePending = pending == null
          ? null
          : point.timestamp.difference(pending.timestamp);
      final pendingDistance =
          pending == null ? null : haversineDistanceMeters(pending, point);
      // Agreement has to be *evidence*, not merely an absence of
      // contradiction. A GPS stuck on one wrong position repeats it exactly:
      // those duplicates imply 0 m/s, trivially "agree", and would hand the
      // anchor to the bad location. Requiring the pair to show real movement
      // means only a fix that is genuinely tracking the runner can re-anchor.
      final agreesWithPending = pending != null &&
          sincePending! <= _pendingCandidateTtl &&
          pendingDistance! >= _minReanchorMotionMeters &&
          _isPlausibleSegment(pendingDistance, sincePending);

      if (agreesWithPending) {
        // How the runner got from `previous` to here is unknown — the jump
        // between them is exactly the thing being rejected — so this is a
        // discontinuity, not a segment. Re-anchor without crediting any
        // distance or time, the same way a pause/resume does. Crediting the
        // pending->point leg instead would bank a bad-fix cluster's own
        // drift as real running.
        _resetAnchorTo(point);
      } else {
        _pendingCandidate = point;
      }
      return;
    }

    _pendingCandidate = null;
    _acceptSegment(segmentDistance, segmentDuration, point);
  }

  /// Whether a segment could have been covered under [mode] rather than
  /// being a GPS glitch. Distance and speed are both bounded: speed alone
  /// lets an arbitrarily large jump through once the gap is long enough, and
  /// distance alone would reject a legitimately sparse stretch of fixes.
  bool _isPlausibleSegment(double distanceMeters, Duration duration) {
    if (distanceMeters > _limits.maxPlausibleSegmentMeters) return false;
    if (duration <= Duration.zero) return distanceMeters == 0;
    return distanceMeters / (duration.inMilliseconds / 1000) <=
        _limits.maxPlausibleSpeedMps;
  }

  /// Restarts measurement from [point] without crediting distance or elapsed
  /// time, for when the run continues but the path in between is unknowable.
  void _resetAnchorTo(TrackPoint point) {
    _lastAccepted = point;
    _pendingCandidate = null;
    // The speed window must not straddle the discontinuity, or current speed
    // reads as the teleport's implied speed for the next few seconds.
    _recentPoints
      ..clear()
      ..add(point);
    _metrics = _buildMetrics();
  }

  void _acceptSegment(
      double segmentDistance, Duration segmentDuration, TrackPoint point) {
    _lastAccepted = point;
    _recentPoints.add(point);
    _pruneRecentPoints(point.timestamp);

    _applySegment(segmentDistance, segmentDuration);
    _metrics = _buildMetrics();
  }

  /// Call when tracking pauses/resumes so elapsed/distance calculations
  /// don't bridge the gap as if it were continuous movement.
  void resetSegmentAnchor() {
    _lastAccepted = null;
    _pendingCandidate = null;
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
