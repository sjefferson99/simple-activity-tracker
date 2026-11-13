import 'dart:math' as math;

/// Motion intensity is measured over the same second as the pressure mean
/// (see pressure_window.dart), so the two line up per fix.
const Duration motionIntensityWindow = Duration(seconds: 1);

/// Cadence needs several cycles to find a period: 4 s holds ~11 running
/// steps or ~6 pedal strokes.
const Duration motionCadenceWindow = Duration(seconds: 4);

/// Cadences outside this band aren't footsteps or pedal strokes.
const double _minCadenceHz = 1;
const double _maxCadenceHz = 4;

/// Below this autocorrelation the motion isn't rhythmic enough to call a
/// cadence (a handlebar mount's road buzz, a phone on a desk).
const double _minPeriodicity = 0.3;

/// The accelerometer is resampled onto this grid before autocorrelating, so
/// uneven sensor delivery doesn't skew the period.
const double _gridSeconds = 0.02;

/// What the accelerometer says about one fix (docs/BAROMETER-PLAN.md):
/// [rmsMps2] is how hard the phone is being shaken (gravity removed),
/// [cadenceHz] the dominant rhythm (running ~2.5–3 Hz, pedalling in a
/// pocket ~1–1.7 Hz), or null if there isn't a clear one. Logged so
/// recordings can be told apart by activity and carry position.
typedef MotionFeatures = ({double rmsMps2, double? cadenceHz});

/// Collects accelerometer magnitudes so each GPS fix can carry the motion
/// around it into the GPX log.
class MotionWindow {
  final List<({double magnitude, DateTime at})> _samples = [];

  void add(double magnitude, DateTime receivedAt) {
    _samples.add((magnitude: magnitude, at: receivedAt));
    _samples.removeWhere(
      (s) => receivedAt.difference(s.at) > motionCadenceWindow,
    );
  }

  /// Features over the windows ending at [now], or null with fewer than two
  /// samples in the last [motionIntensityWindow] (no accelerometer, or it
  /// stopped reporting).
  MotionFeatures? at(DateTime now) {
    final recent = [
      for (final s in _samples)
        if (now.difference(s.at) <= motionIntensityWindow) s.magnitude,
    ];
    if (recent.length < 2) return null;
    final mean = recent.reduce((a, b) => a + b) / recent.length;
    final rms = math.sqrt(
      recent.map((m) => (m - mean) * (m - mean)).reduce((a, b) => a + b) /
          recent.length,
    );
    return (rmsMps2: rms, cadenceHz: _cadenceHz(now));
  }

  /// The dominant period by autocorrelation over [motionCadenceWindow].
  double? _cadenceHz(DateTime now) {
    final window = [
      for (final s in _samples)
        if (now.difference(s.at) <= motionCadenceWindow) s,
    ];
    if (window.length < 2) return null;
    final start = window.first.at;
    double secondsOf(DateTime t) => t.difference(start).inMicroseconds / 1e6;
    final span = secondsOf(window.last.at);
    // At least two full cycles of the slowest cadence.
    if (span < 2 / _minCadenceHz) return null;

    // Linear interpolation onto an even grid.
    final grid = <double>[];
    var j = 0;
    for (var t = 0.0; t <= span; t += _gridSeconds) {
      while (j < window.length - 2 && secondsOf(window[j + 1].at) < t) {
        j++;
      }
      final t0 = secondsOf(window[j].at);
      final t1 = secondsOf(window[j + 1].at);
      final m0 = window[j].magnitude;
      final m1 = window[j + 1].magnitude;
      grid.add(t1 > t0 ? m0 + (m1 - m0) * ((t - t0) / (t1 - t0)) : m0);
    }
    final mean = grid.reduce((a, b) => a + b) / grid.length;
    final x = [for (final g in grid) g - mean];
    final energy = x.map((v) => v * v).reduce((a, b) => a + b);
    if (energy == 0) return null;

    final minLag = (1 / _maxCadenceHz / _gridSeconds).floor();
    final maxLag = (1 / _minCadenceHz / _gridSeconds).ceil();
    if (maxLag + 1 >= x.length) return null;
    double r(int lag) {
      var sum = 0.0;
      for (var i = 0; i + lag < x.length; i++) {
        sum += x[i] * x[i + lag];
      }
      return sum / energy;
    }

    final rs = {
      for (var lag = minLag - 1; lag <= maxLag + 1; lag++) lag: r(lag),
    };
    final peaks = [
      for (var lag = minLag; lag <= maxLag; lag++)
        if (rs[lag]! >= rs[lag - 1]! && rs[lag]! > rs[lag + 1]!) lag,
    ];
    if (peaks.isEmpty) return null;
    final best = peaks.map((lag) => rs[lag]!).reduce(math.max);
    if (best < _minPeriodicity) return null;
    // The shortest strong period, not a multiple of it: a running stride
    // (two steps) correlates almost as well as one step.
    final lag = peaks.firstWhere((lag) => rs[lag]! >= 0.8 * best);
    // Parabolic interpolation for sub-grid precision.
    final a = rs[lag - 1]!, b = rs[lag]!, c = rs[lag + 1]!;
    final denominator = a - 2 * b + c;
    final offset = denominator == 0 ? 0.0 : 0.5 * (a - c) / denominator;
    return 1 / ((lag + offset) * _gridSeconds);
  }

  void reset() => _samples.clear();
}
