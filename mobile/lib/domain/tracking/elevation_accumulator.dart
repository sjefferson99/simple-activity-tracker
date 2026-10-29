import 'dart:math' as math;

/// Time constant of the exponential moving average applied to GPS altitude
/// before any climb is counted — see [ElevationAccumulator].
const double elevationSmoothingTauSeconds = 10;

/// How far the smoothed altitude must move from the last counted level
/// before the change counts as climb or descent.
const double elevationHysteresisMeters = 3;

/// Each fix may pull the smoothed altitude at most this fast towards itself,
/// so one wild altitude reading can't register as a climb. No one on foot or
/// a bike climbs or drops this fast.
const double elevationMaxVerticalSpeedMps = 5;

/// Elevation gain/loss from GPS altitude, issue #181.
///
/// GPS altitude jitters a few metres from fix to fix; summing every wobble
/// as climb overstated a 3.5 h walk's ascent ~2.5x. This smooths over time
/// (so the result doesn't depend on the fix rate), rate-limited by
/// [elevationMaxVerticalSpeedMps], then only counts a change
/// once it clears a dead-band of [elevationHysteresisMeters].
///
/// The server's analyzer runs the same algorithm with the same constants
/// (server/app/analysis/elevation.py) over the same accuracy-filtered fixes
/// the GPX log holds, so the live tile matches the analysis after upload.
/// Both test suites replay contract/elevation/gps-noise.json to prove it —
/// change neither side alone.
class ElevationAccumulator {
  double _gainMeters = 0;
  double _lossMeters = 0;
  double? _smoothed;
  double? _reference;
  DateTime? _lastTimestamp;

  double get gainMeters => _gainMeters;
  double get lossMeters => _lossMeters;

  /// Feeds one fix, in time order. A fix with no altitude is skipped.
  void add(DateTime timestamp, double? elevationMeters) {
    if (elevationMeters == null) return;
    final smoothed = _smoothed;
    final reference = _reference;
    final lastTimestamp = _lastTimestamp;
    if (smoothed == null || reference == null || lastTimestamp == null) {
      _smoothed = elevationMeters;
      _reference = elevationMeters;
      _lastTimestamp = timestamp;
      return;
    }
    var next = smoothed;
    final dtSeconds =
        timestamp.difference(lastTimestamp).inMicroseconds / 1000000;
    if (dtSeconds > 0) {
      final limit = elevationMaxVerticalSpeedMps * dtSeconds;
      final target = elevationMeters.clamp(smoothed - limit, smoothed + limit);
      final alpha = 1 - math.exp(-dtSeconds / elevationSmoothingTauSeconds);
      next += alpha * (target - smoothed);
      _smoothed = next;
      _lastTimestamp = timestamp;
    }
    final rise = next - reference;
    if (rise >= elevationHysteresisMeters) {
      _gainMeters += rise;
      _reference = next;
    } else if (-rise >= elevationHysteresisMeters) {
      _lossMeters += -rise;
      _reference = next;
    }
  }

  /// Call at every pause/resume (where the GPX log starts a new segment), so
  /// a height change while paused isn't counted. Totals are kept.
  void resetAnchor() {
    _smoothed = null;
    _reference = null;
    _lastTimestamp = null;
  }
}
