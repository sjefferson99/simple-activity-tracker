import 'package:flutter_test/flutter_test.dart';
import 'package:simple_runner/core/units/units.dart';

void main() {
  group('kmhFromMps', () {
    test('converts meters/second to km/h', () {
      expect(kmhFromMps(1), closeTo(3.6, 0.0001));
      expect(kmhFromMps(0), 0);
    });
  });

  group('paceSecPerKmFromMps', () {
    test('returns seconds per km for a positive speed', () {
      // 1000m / (1000/300 m/s) => 300s = 5:00/km at that speed.
      final secPerKm = paceSecPerKmFromMps(1000 / 300);
      expect(secPerKm, closeTo(300, 0.001));
    });

    test('returns null when stopped', () {
      expect(paceSecPerKmFromMps(0), isNull);
      expect(paceSecPerKmFromMps(-1), isNull);
    });
  });

  group('formatKmh', () {
    test('formats to one decimal place', () {
      expect(formatKmh(1), '3.6');
      expect(formatKmh(10 / 3.6), '10.0');
    });
  });

  group('formatPace', () {
    test('formats seconds-per-km as m:ss', () {
      expect(formatPace(300), '5:00');
      expect(formatPace(292), '4:52');
      expect(formatPace(65), '1:05');
    });

    test('shows placeholder when pace is undefined', () {
      expect(formatPace(null), '--:--');
      expect(formatPace(double.infinity), '--:--');
    });
  });

  group('formatDuration', () {
    test('formats under an hour as m:ss', () {
      expect(formatDuration(const Duration(minutes: 12, seconds: 35)), '12:35');
      expect(formatDuration(const Duration(seconds: 5)), '0:05');
    });

    test('formats an hour or more as h:mm:ss', () {
      expect(
        formatDuration(const Duration(hours: 1, minutes: 2, seconds: 35)),
        '1:02:35',
      );
    });
  });

  group('formatDistanceKm', () {
    test('formats meters as km with two decimals', () {
      expect(formatDistanceKm(5210), '5.21');
      expect(formatDistanceKm(0), '0.00');
    });
  });
}
