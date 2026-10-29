import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/tracking/elevation_accumulator.dart';

final _start = DateTime.utc(2026, 10, 23, 9);

DateTime _at(num seconds) =>
    _start.add(Duration(microseconds: (seconds * 1000000).round()));

void main() {
  test('contract replay matches the server (contract/elevation/)', () {
    // server/tests/test_elevation.py replays the same file — this is what
    // keeps the live tile and the analysis in agreement (issue #181).
    final contract = jsonDecode(
      File('../contract/elevation/gps-noise.json').readAsStringSync(),
    ) as Map<String, dynamic>;
    expect(contract['tau_s'], elevationSmoothingTauSeconds);
    expect(contract['hysteresis_m'], elevationHysteresisMeters);
    expect(contract['max_vertical_speed_mps'], elevationMaxVerticalSpeedMps);

    final accumulator = ElevationAccumulator();
    for (final segment in contract['segments'] as List<dynamic>) {
      accumulator.resetAnchor();
      for (final point in segment as List<dynamic>) {
        final pair = point as List<dynamic>;
        accumulator.add(_at(pair[0] as num), (pair[1] as num?)?.toDouble());
      }
    }

    final expected = contract['expected'] as Map<String, dynamic>;
    expect(accumulator.gainMeters, closeTo(expected['gain_m'] as num, 1e-6));
    expect(accumulator.lossMeters, closeTo(expected['loss_m'] as num, 1e-6));
  });

  test('a noisy but flat track has almost no gain', () {
    final random = math.Random(5);
    final accumulator = ElevationAccumulator();
    for (var i = 0; i < 3600; i++) {
      // Sum of uniforms ≈ normal, sd ~1.5 m.
      final noise =
          (random.nextDouble() +
              random.nextDouble() +
              random.nextDouble() -
              1.5) *
          3;
      accumulator.add(_at(i), 40 + noise);
    }
    expect(accumulator.gainMeters, lessThan(6));
    expect(accumulator.lossMeters, lessThan(6));
  });

  test('a climb while paused is not counted', () {
    final accumulator = ElevationAccumulator()
      ..add(_at(0), 100)
      ..add(_at(1), 100)
      ..resetAnchor()
      ..add(_at(600), 150)
      ..add(_at(601), 150);
    expect(accumulator.gainMeters, 0);
  });

  test('fixes without altitude are skipped', () {
    final accumulator = ElevationAccumulator();
    for (var t = 0; t < 200; t++) {
      accumulator.add(_at(t), t.isOdd ? null : 100 + t * 0.1);
    }
    expect(
      accumulator.gainMeters,
      greaterThan(19.8 - elevationHysteresisMeters - 1),
    );
    expect(accumulator.gainMeters, lessThanOrEqualTo(19.8));
    expect(accumulator.lossMeters, 0);
  });
}
