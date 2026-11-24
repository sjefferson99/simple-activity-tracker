import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/models/track_point.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';
import 'package:simple_activity_tracker/domain/tracking/calibrated_display_speed.dart';
import 'package:simple_activity_tracker/domain/tracking/display_speed_window.dart';

/// Points along the equator (one degree ≈ 111,195 m), as other tracking
/// tests do, with an optional north offset for cross-track jitter.
TrackPoint _point(
  double eastMeters,
  int second, {
  double northMeters = 0,
  double? chipMps,
}) {
  return TrackPoint(
    latitude: northMeters / 111195,
    longitude: eastMeters / 111195,
    timestamp: DateTime.utc(2026, 1, 1).add(Duration(seconds: second)),
    accuracyMeters: 5,
    speedMps: chipMps,
    hasSpeed: chipMps != null && chipMps > 0,
  );
}

/// Feeds a steady run at [trueMps] for [seconds] 1 Hz fixes, the chip
/// reading [chipFactor] × true speed, returning every reading.
List<double?> _steadyRun(
  CalibratedDisplaySpeed estimator, {
  required double trueMps,
  required int seconds,
  double chipFactor = 1,
  int startSecond = 0,
  double startMeters = 0,
}) {
  return [
    for (var t = 0; t < seconds; t++)
      estimator.addPoint(_point(
        startMeters + trueMps * t,
        startSecond + t,
        chipMps: trueMps * chipFactor,
      )),
  ];
}

void main() {
  group('CalibratedDisplaySpeed', () {
    test('returns null for the first point (nothing to show yet)', () {
      final estimator = CalibratedDisplaySpeed(smoothingSeconds: 3);
      expect(estimator.addPoint(_point(0, 0, chipMps: 1.5)), isNull);
    });

    test(
      'during warm-up (under 20 m of path) shows the path window, not the '
      'uncorrected chip speed',
      () {
        final estimator = CalibratedDisplaySpeed(smoothingSeconds: 3);
        // 1.5 m/s for 10 s = 15 m of path; the chip reads 20% low.
        final readings =
            _steadyRun(estimator, trueMps: 1.5, seconds: 11, chipFactor: 0.8);
        expect(readings.last, closeTo(1.5, 0.01));
      },
    );

    test(
      'a chip reading 13% low is rescaled to agree with position-derived '
      'speed once calibrated',
      () {
        final estimator = CalibratedDisplaySpeed(smoothingSeconds: 3);
        final readings =
            _steadyRun(estimator, trueMps: 1.7, seconds: 90, chipFactor: 0.87);
        expect(readings.last, closeTo(1.7, 0.02));
      },
    );

    test(
      'with ~1 m position jitter at a steady chip speed, the readout is far '
      'steadier than the 6 s path window',
      () {
        final estimator = CalibratedDisplaySpeed(smoothingSeconds: 3);
        final window = DisplaySpeedWindow();
        final random = Random(42);
        const trueMps = 1.67; // ~6 km/h
        final calibrated = <double>[];
        final windowed = <double>[];
        for (var t = 0; t < 300; t++) {
          final point = _point(
            trueMps * t + (random.nextDouble() * 2 - 1),
            t,
            northMeters: random.nextDouble() * 2 - 1,
            chipMps: trueMps * 0.9,
          );
          final c = estimator.addPoint(point);
          final w = window.addPoint(point);
          if (t >= 90) {
            calibrated.add(c!);
            windowed.add(w!);
          }
        }

        double spread(List<double> xs) => xs.reduce(max) - xs.reduce(min);
        expect(spread(calibrated), lessThan(spread(windowed) / 3));
        // Jitter adds path length, so the calibrated value tracks the
        // position-based speed (above the true speed here), which is what
        // Distance, Avg and splits show, not the chip's own reading.
        double mean(List<double> xs) => xs.reduce((a, b) => a + b) / xs.length;
        expect(mean(calibrated), closeTo(mean(windowed), mean(windowed) * 0.02));
      },
    );

    test('a fix without a chip speed falls back to the path window', () {
      final estimator = CalibratedDisplaySpeed(smoothingSeconds: 3);
      _steadyRun(estimator, trueMps: 2, seconds: 60, chipFactor: 0.5);
      // Path says 1 m/s for this fix; no chip speed.
      final reading = estimator.addPoint(_point(119, 60));
      final window = DisplaySpeedWindow();
      for (var t = 54; t < 60; t++) {
        window.addPoint(_point(2.0 * t, t));
      }
      expect(reading, closeTo(window.addPoint(_point(119, 60))!, 1e-9));
    });

    test('the correction ratio is clamped to 0.8-1.3', () {
      final high = CalibratedDisplaySpeed(smoothingSeconds: 3);
      // Chip reads half the path speed: ratio 2.0, clamped to 1.3.
      final highReadings =
          _steadyRun(high, trueMps: 2, seconds: 90, chipFactor: 0.5);
      expect(highReadings.last, closeTo(1.0 * 1.3, 0.01));

      final low = CalibratedDisplaySpeed(smoothingSeconds: 3);
      // Chip reads double the path speed: ratio 0.5, clamped to 0.8.
      final lowReadings =
          _steadyRun(low, trueMps: 1, seconds: 90, chipFactor: 2);
      expect(lowReadings.last, closeTo(2.0 * 0.8, 0.01));
    });

    test(
      'a step change shows 63% of the change within ~4 s (τ = 3 s)',
      () {
        final estimator = CalibratedDisplaySpeed(smoothingSeconds: 3);
        const slow = 6 / 3.6, fast = 8 / 3.6;
        _steadyRun(estimator, trueMps: slow, seconds: 90);
        var meters = slow * 89;
        double? reading;
        for (var t = 90; t <= 94; t++) {
          meters += fast;
          reading = estimator.addPoint(_point(meters, t, chipMps: fast));
        }
        expect(reading, greaterThan(slow + 0.63 * (fast - slow)));
        expect(reading, lessThan(fast * 1.01));
      },
    );

    test('cycling uses a longer smoothing constant than running and walking',
        () {
      expect(
        CalibratedDisplaySpeed.forMode(ActivityMode.cycling).smoothingSeconds,
        greaterThan(
          CalibratedDisplaySpeed.forMode(ActivityMode.running).smoothingSeconds,
        ),
      );
      expect(
        CalibratedDisplaySpeed.forMode(ActivityMode.walking).smoothingSeconds,
        CalibratedDisplaySpeed.forMode(ActivityMode.running).smoothingSeconds,
      );
    });

    test(
      'a dropout over 5 s is left out of both ledgers, so it does not skew '
      'the calibration',
      () {
        final estimator = CalibratedDisplaySpeed(smoothingSeconds: 3);
        // Calibrate with the chip reading 10% low.
        _steadyRun(estimator, trueMps: 2, seconds: 40, chipFactor: 0.9);
        // A 10 s dropout covering 50 m, then the same pace. Counting the
        // gap's path but not its chip distance (or vice versa) would push
        // the ratio well away from 1/0.9.
        final readings = _steadyRun(
          estimator,
          trueMps: 2,
          seconds: 5,
          chipFactor: 0.9,
          startSecond: 49,
          startMeters: 2 * 39 + 50,
        );
        expect(readings.last, closeTo(2.0, 0.02));
      },
    );

    test('a GPS jump is left out of the calibration', () {
      final estimator = CalibratedDisplaySpeed(smoothingSeconds: 3);
      _steadyRun(estimator, trueMps: 2, seconds: 40, chipFactor: 0.9);
      // One fix 200 m off in 1 s, then back on track: the path ledger would
      // gain ~400 m against ~4 m of chip and pin the ratio at the 1.3 clamp.
      estimator.addPoint(_point(2.0 * 40 + 200, 40, chipMps: 1.8));
      final readings = _steadyRun(
        estimator,
        trueMps: 2,
        seconds: 10,
        chipFactor: 0.9,
        startSecond: 41,
        startMeters: 2.0 * 41,
      );
      expect(readings.last, closeTo(2.0, 0.02));
    });

    test('reset clears everything, so warm-up starts again', () {
      final estimator = CalibratedDisplaySpeed(smoothingSeconds: 3);
      _steadyRun(estimator, trueMps: 2, seconds: 90, chipFactor: 0.5);

      estimator.reset();

      expect(estimator.addPoint(_point(1000, 400, chipMps: 1)), isNull);
      // Back in warm-up: path window (2 m/s), not the chip value or the old
      // calibration.
      final reading = estimator.addPoint(_point(1002, 401, chipMps: 1));
      expect(reading, closeTo(2.0, 0.01));
    });
  });
}
