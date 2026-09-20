import '../geo_math.dart';
import '../models/track_point.dart';

/// The live "current speed" tile's speed source (issue #50 follow-up):
/// path length covered over the last ~[_windowDuration] of GPS fixes, not
/// the GPS chip's own reported Doppler speed.
///
/// A real measured test (760m out-and-back, 8:00 exactly, 5.7 km/h) found
/// the chip's raw speed field reading ~13% low throughout (mean 4.96 km/h)
/// while position-derived distance/pace matched the stopwatch almost
/// exactly — the same bias this issue's wheel-sensor evidence found in
/// chip-speed *distance* integration, now also confirmed in the chip's
/// *instantaneous* speed reading. [MetricsEngine]'s distance/split/average
/// math never used chip speed for its own numbers (only to drive the
/// moving/stationary gate), so this brings the live display in line with
/// those, rather than fixing this in isolation with an unvalidated
/// correction factor.
///
/// Sums each consecutive segment's own distance inside the window, rather
/// than a single start-to-end displacement — a second real capture (a 6
/// km/h target on a short out-and-back route with turns) showed straight-
/// line displacement actually gets *worse* as the window widens, because a
/// wider window more often spans a turn and the straight-line chord cuts
/// the corner short. Path-summing is immune to that: replaying the same
/// capture held the mean locked at ~5.97 km/h (against a 6.0 target) at
/// every window size from 3-20s, with no drift and no jitter-inflation —
/// the per-fix position jitter that inflates *cumulative* distance over an
/// entire activity (see MetricsEngine's own credited-distance doc) never
/// became visible here even at 20s, at this capture's GPS accuracy.
/// [_windowDuration] was chosen from the same capture: widening from 3s to
/// 6s cut the standard deviation from 0.58 to 0.48 km/h (range 4.71 to
/// 3.65) while keeping a real pace change roughly half-reflected within
/// ~3s — a similar feel to [SpeedSmoother]'s old 3s time constant, just on
/// the corrected, path-summed measure.
///
/// Fed every accepted GPS fix regardless of the stationary gate's
/// moving/not-moving verdict — same as the chip-speed display it replaces —
/// so it settles toward zero on its own while genuinely stationary rather
/// than freezing at a stale reading.
class DisplaySpeedWindow {
  static const Duration _windowDuration = Duration(seconds: 6);

  final List<TrackPoint> _points = [];

  /// Feeds one more GPS fix and returns the updated windowed speed, or null
  /// until at least two points span a non-zero duration.
  double? addPoint(TrackPoint point) {
    _points.add(point);
    final cutoff = point.timestamp.subtract(_windowDuration);
    while (_points.length > 1 && _points.first.timestamp.isBefore(cutoff)) {
      _points.removeAt(0);
    }
    if (_points.length < 2) return null;

    final dtSeconds =
        _points.last.timestamp.difference(_points.first.timestamp).inMilliseconds /
            1000;
    if (dtSeconds <= 0) return null;

    var pathMeters = 0.0;
    for (var i = 0; i < _points.length - 1; i++) {
      pathMeters += haversineDistanceMeters(_points[i], _points[i + 1]);
    }
    return pathMeters / dtSeconds;
  }

  /// Clears the window — call alongside any discontinuity (pause, re-anchor
  /// after a GPS teleport) so a stale window from before the gap doesn't
  /// blend into the first reading after it.
  void reset() {
    _points.clear();
  }
}
