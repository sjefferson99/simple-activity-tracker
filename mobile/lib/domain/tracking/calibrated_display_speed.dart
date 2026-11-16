import 'dart:math';

import '../geo_math.dart';
import '../models/track_point.dart';
import 'activity_mode.dart';
import 'display_speed_window.dart';

/// The live "current speed" tile's speed source (issue #153): the GPS chip's
/// own (Doppler) speed, smoothed, then rescaled so it agrees with
/// position-derived distance.
///
/// ```
/// display = EMA(chipSpeed, τ) × clamp(pathDist_60s / chipDist_60s, 0.8, 1.3)
/// ```
///
/// Why not [DisplaySpeedWindow] alone: path length ÷ time over 6 s is
/// dominated by ~1 m of position error at the window's ends against only
/// ~10 m travelled at 6 km/h, which pace display amplifies (at 6 km/h one
/// km/h is ~100 s/km). Doppler speed has no such term, but on the phones
/// tested it reads low (~8-13%), which is why #50 dropped it. The 60 s
/// ratio removes that bias adaptively, so the readout stays consistent with
/// distance, Avg and split averages, which are all position-based in
/// [MetricsEngine]. That consistency is what matters for hitting a split
/// target.
///
/// Replaying real captures against a centred 30 s path speed (see
/// docs/GPS-METRICS-PLAN.md §2 Step 6): about 4× less jumpy than the 6 s
/// window (mean pace change per update ~5 vs ~20 s/km on ~6 km/h runs),
/// with no measurable bias and a slightly *shorter* lag (~4 s vs ~5 s to
/// show 63% of a step change).
///
/// Falls back to [DisplaySpeedWindow] whenever the calibrated value isn't
/// available: until the last 60 s cover more than [_minCalibrationPathMeters]
/// (warm-up after start/resume), and on any fix without a chip speed.
/// geolocator_android reports `hasSpeed` as `speed > 0`, so a fix reading
/// exactly 0 (standing still) also uses the window, which settles toward
/// zero on its own.
///
/// Display-only: [MetricsEngine]'s distance and split math are unaffected.
class CalibratedDisplaySpeed {
  CalibratedDisplaySpeed({required this.smoothingSeconds})
      : assert(smoothingSeconds > 0);

  /// τ per activity: cycling gets a longer constant. Ride replays showed
  /// smaller gains and a ~3.5% high reading at τ = 3 s; provisional until a
  /// ride capture is checked on this estimator.
  factory CalibratedDisplaySpeed.forMode(ActivityMode mode) =>
      CalibratedDisplaySpeed(
        smoothingSeconds: mode == ActivityMode.cycling ? 5 : 3,
      );

  /// Time constant of the chip-speed exponential moving average, seconds.
  final double smoothingSeconds;

  static const Duration _calibrationWindow = Duration(seconds: 60);

  /// Below this much path in the calibration window, the path ÷ chip ratio
  /// is too noisy to trust (a few metres of jitter would swing it widely).
  static const double _minCalibrationPathMeters = 20;

  /// A chip-distance total this small can't be a meaningful denominator.
  static const double _minCalibrationChipMeters = 1;

  /// Past this gap, two endpoint chip speeds don't describe the path between
  /// them (fixes were dropped), so the segment credits no chip distance.
  static const double _maxChipIntegrationGapSeconds = 5;

  static const double _minRatio = 0.8;
  static const double _maxRatio = 1.3;

  final DisplaySpeedWindow _fallback = DisplaySpeedWindow();

  /// Running totals at each fix in the calibration window.
  final List<_Entry> _entries = [];
  TrackPoint? _previous;
  double _pathCumulative = 0;
  double _chipCumulative = 0;

  double? _ema;
  DateTime? _emaAt;

  /// Feeds one more GPS fix and returns the speed to display in m/s, or null
  /// when there's nothing to show yet.
  double? addPoint(TrackPoint point) {
    final fallback = _fallback.addPoint(point);

    final previous = _previous;
    if (previous != null) {
      final dt = _seconds(previous.timestamp, point.timestamp);
      if (dt > 0) {
        _pathCumulative += haversineDistanceMeters(previous, point);
        final previousSpeed = _chipSpeed(previous);
        final speed = _chipSpeed(point);
        if (previousSpeed != null &&
            speed != null &&
            dt <= _maxChipIntegrationGapSeconds) {
          _chipCumulative += (previousSpeed + speed) / 2 * dt;
        }
      }
    }
    _previous = point;

    _entries.add(_Entry(point.timestamp, _pathCumulative, _chipCumulative));
    final cutoff = point.timestamp.subtract(_calibrationWindow);
    while (_entries.length > 1 && _entries.first.timestamp.isBefore(cutoff)) {
      _entries.removeAt(0);
    }

    final speed = _chipSpeed(point);
    if (speed == null) return fallback;

    final ema = _updateEma(speed, point.timestamp);

    final first = _entries.first;
    final path = _pathCumulative - first.pathCumulative;
    final chip = _chipCumulative - first.chipCumulative;
    if (path <= _minCalibrationPathMeters || chip <= _minCalibrationChipMeters) {
      return fallback;
    }
    return ema * (path / chip).clamp(_minRatio, _maxRatio);
  }

  /// Clears all state. Call alongside any discontinuity (start, pause,
  /// resume) so a stale window or calibration from before the gap doesn't
  /// blend into the first reading after it.
  void reset() {
    _fallback.reset();
    _entries.clear();
    _previous = null;
    _pathCumulative = 0;
    _chipCumulative = 0;
    _ema = null;
    _emaAt = null;
  }

  double _updateEma(double speed, DateTime at) {
    final previous = _ema;
    final previousAt = _emaAt;
    final double next;
    if (previous == null || previousAt == null) {
      next = speed;
    } else {
      final dt = _seconds(previousAt, at);
      final alpha = dt <= 0 ? 0.0 : 1 - exp(-dt / smoothingSeconds);
      next = previous + alpha * (speed - previous);
    }
    _ema = next;
    _emaAt = at;
    return next;
  }

  static double? _chipSpeed(TrackPoint point) {
    final speed = point.speedMps;
    if (!point.hasSpeed || speed == null || speed.isNaN || speed < 0) {
      return null;
    }
    return speed;
  }

  static double _seconds(DateTime from, DateTime to) =>
      to.difference(from).inMilliseconds / 1000;
}

class _Entry {
  const _Entry(this.timestamp, this.pathCumulative, this.chipCumulative);
  final DateTime timestamp;
  final double pathCumulative;
  final double chipCumulative;
}
