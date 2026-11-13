import 'dart:math' as math;

import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/tracking/pressure_window.dart';

void main() {
  final t0 = DateTime.utc(2026, 11, 11, 9);
  DateTime ms(int milliseconds) => t0.add(Duration(milliseconds: milliseconds));

  test('has nothing before the first reading', () {
    expect(PressureWindow().at(t0), isNull);
  });

  test('averages the readings in the last second', () {
    final window = PressureWindow()
      ..add(1000.0, ms(0))
      ..add(1013.0, ms(1500))
      ..add(1013.2, ms(1800))
      ..add(1013.4, ms(2400));
    final reading = window.at(ms(2500))!;
    expect(reading.hpa, closeTo(1013.2, 1e-9));
    // Population spread of 1013.0, 1013.2, 1013.4.
    expect(reading.sdHpa, closeTo(math.sqrt(0.08 / 3), 1e-9));
  });

  test('a reading exactly a window old is still averaged', () {
    final window = PressureWindow()
      ..add(1013.0, ms(0))
      ..add(1014.0, ms(500));
    expect(
      window.at(t0.add(pressureAveragingWindow))!.hpa,
      closeTo(1013.5, 1e-9),
    );
  });

  test('a single reading in the window has no spread', () {
    final window = PressureWindow()..add(1013.0, t0);
    expect(window.at(ms(500)), (hpa: 1013.0, sdHpa: null));
  });

  test('a slow sensor falls back to its latest reading while fresh', () {
    final window = PressureWindow()
      ..add(1013.0, ms(0))
      ..add(1013.1, ms(500));
    expect(window.at(ms(2000)), (hpa: 1013.1, sdHpa: null));
    expect(window.at(ms(500).add(maxPressureReadingAge))!.hpa, 1013.1);
    expect(window.at(ms(501).add(maxPressureReadingAge)), isNull);
  });

  test('a sensor that stopped reporting gives nothing', () {
    final window = PressureWindow()..add(1013.0, t0);
    expect(
      window.at(
        t0.add(maxPressureReadingAge + const Duration(milliseconds: 1)),
      ),
      isNull,
    );
  });

  test('reset forgets every reading', () {
    final window = PressureWindow()
      ..add(1013.2, t0)
      ..reset();
    expect(window.at(t0), isNull);
  });
}
