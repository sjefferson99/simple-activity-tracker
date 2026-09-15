import 'dart:math' as math;

/// Lightly smooths the live speed readout so it settles enough to actually
/// aim at, without lagging so much a real pace change takes ages to show.
/// Display-only: [MetricsEngine]'s distance/split/average math and the GPX
/// log both keep reading raw per-fix speed — this only affects what the
/// "current speed" number on screen shows (found real: at ~1Hz GPS sampling
/// the raw chip speed swings enough between consecutive fixes that trying to
/// hit a split target by watching it made pacing worse, not better).
///
/// A time-weighted exponential moving average: each new fix is blended in
/// proportionally to how long it's been since the last one, so a sparse
/// stretch of fixes (weak signal, backgrounded app) doesn't leave the
/// readout frozen on a stale blend — a fix arriving after a long gap is
/// trusted almost fully, one arriving quickly after the last is blended
/// lightly. Pure Dart; the caller supplies `now` so it's testable without a
/// real clock.
class SpeedSmoother {
  /// Time constant: roughly how long a step change in true speed takes to
  /// dominate the readout. Short enough that a real pace change shows up in
  /// a few seconds, long enough to damp single-fix noise at ~1Hz sampling.
  static const Duration _timeConstant = Duration(seconds: 3);

  double? _smoothedMps;
  DateTime? _lastFixAt;

  /// The smoothed speed after the most recent [addSpeed] call, or null
  /// before any fix has been added (or after [reset]).
  double? get smoothedMps => _smoothedMps;

  /// Blends [speedMps] in at [now], weighted by the elapsed time since the
  /// previous fix, and returns the updated smoothed value.
  double addSpeed(double speedMps, DateTime now) {
    final lastFixAt = _lastFixAt;
    _lastFixAt = now;
    final previous = _smoothedMps;
    if (previous == null || lastFixAt == null) {
      _smoothedMps = speedMps;
      return speedMps;
    }

    final dt = now.difference(lastFixAt).inMilliseconds / 1000;
    // A non-positive gap (clock skew, or a duplicate/out-of-order fix) can't
    // produce a sane blend weight — treat it like a fresh start instead of
    // dividing by (or exponentiating) an unreasonable value.
    if (dt <= 0) {
      _smoothedMps = speedMps;
      return speedMps;
    }

    final tau = _timeConstant.inMilliseconds / 1000;
    // Larger dt (relative to tau) => alpha closer to 1 => the new fix
    // dominates, which is exactly "trust it almost fully after a long gap".
    final alpha = 1 - math.exp(-dt / tau);
    _smoothedMps = previous + alpha * (speedMps - previous);
    return _smoothedMps!;
  }

  /// Clears the smoothed value — call alongside any discontinuity (pause,
  /// re-anchor after a GPS teleport) so a stale blend from before the gap
  /// doesn't drag down/up the first reading after it.
  void reset() {
    _smoothedMps = null;
    _lastFixAt = null;
  }
}
