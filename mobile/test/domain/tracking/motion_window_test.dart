import 'dart:math' as math;

import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/tracking/motion_window.dart';

void main() {
  final t0 = DateTime.utc(2026, 11, 13, 9);

  /// Feeds [seconds] of 50 Hz samples of [signal] (time in s) and returns the
  /// window and the time of the last sample.
  (MotionWindow, DateTime) feed(
    double Function(double t) signal, {
    double seconds = 5,
  }) {
    final window = MotionWindow();
    late DateTime last;
    for (var i = 0; i <= seconds * 50; i++) {
      last = t0.add(Duration(milliseconds: i * 20));
      window.add(signal(i * 0.02), last);
    }
    return (window, last);
  }

  test('has nothing without samples', () {
    expect(MotionWindow().at(t0), isNull);
  });

  test('finds a running cadence and its shake', () {
    // ~2.8 steps a second, ±6 m/s² around gravity.
    final (window, now) = feed(
      (t) => 9.81 + 6 * math.sin(2 * math.pi * 2.8 * t),
    );
    final features = window.at(now)!;
    expect(features.cadenceHz, closeTo(2.8, 0.05));
    expect(features.rmsMps2, closeTo(6 / math.sqrt2, 0.3));
  });

  test(
    'a stride (every other step a bit harder) still reports the step rate',
    () {
      final (window, now) = feed(
        (t) =>
            9.81 +
            6 * math.sin(2 * math.pi * 2.8 * t) +
            1.5 * math.sin(2 * math.pi * 1.4 * t),
      );
      expect(window.at(now)!.cadenceHz, closeTo(2.8, 0.05));
    },
  );

  test('finds a pedalling cadence', () {
    final (window, now) = feed(
      (t) => 9.81 + 2 * math.sin(2 * math.pi * 1.4 * t),
    );
    expect(window.at(now)!.cadenceHz, closeTo(1.4, 0.05));
  });

  test('a phone lying still has no shake and no cadence', () {
    final (window, now) = feed((_) => 9.81);
    final features = window.at(now)!;
    expect(features.rmsMps2, 0);
    expect(features.cadenceHz, isNull);
  });

  test('random buzz has a shake but no cadence', () {
    final random = math.Random(184);
    final (window, now) = feed((_) => 9.81 + random.nextDouble() * 2 - 1);
    final features = window.at(now)!;
    expect(features.rmsMps2, greaterThan(0.3));
    expect(features.cadenceHz, isNull);
  });

  test('too short a window gives a shake but no cadence yet', () {
    final (window, now) = feed(
      (t) => 9.81 + 6 * math.sin(2 * math.pi * 2.8 * t),
      seconds: 1.5,
    );
    final features = window.at(now)!;
    expect(features.rmsMps2, greaterThan(0));
    expect(features.cadenceHz, isNull);
  });

  test('a sensor that stopped reporting gives nothing', () {
    final (window, now) = feed(
      (t) => 9.81 + 6 * math.sin(2 * math.pi * 2.8 * t),
    );
    expect(window.at(now.add(const Duration(seconds: 2))), isNull);
  });

  test('reset forgets every sample', () {
    final (window, now) = feed(
      (t) => 9.81 + 6 * math.sin(2 * math.pi * 2.8 * t),
    );
    window.reset();
    expect(window.at(now), isNull);
  });
}
