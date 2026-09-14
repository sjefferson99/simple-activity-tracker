import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/units/units.dart';

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

  group('milesFromMeters', () {
    test('converts meters to miles', () {
      expect(milesFromMeters(1609.344), closeTo(1, 0.0001));
      expect(milesFromMeters(0), 0);
    });
  });

  group('formatDistanceMi', () {
    test('formats meters as miles with two decimals', () {
      expect(formatDistanceMi(1609.344), '1.00');
      expect(formatDistanceMi(0), '0.00');
    });
  });

  group('formatMeters', () {
    test('rounds to the nearest whole metre', () {
      expect(formatMeters(123.4), '123');
      expect(formatMeters(123.6), '124');
      expect(formatMeters(0), '0');
    });
  });

  group('mphFromMps', () {
    test('converts meters/second to mph', () {
      expect(mphFromMps(0.44704), closeTo(1, 0.0001));
      expect(mphFromMps(0), 0);
    });
  });

  group('paceSecPerMileFromMps', () {
    test('returns seconds per mile for a positive speed', () {
      final secPerMile = paceSecPerMileFromMps(1609.344 / 300);
      expect(secPerMile, closeTo(300, 0.001));
    });

    test('returns null when stopped', () {
      expect(paceSecPerMileFromMps(0), isNull);
      expect(paceSecPerMileFromMps(-1), isNull);
    });
  });

  group('formatMph', () {
    test('formats to one decimal place', () {
      expect(formatMph(0.44704), '1.0');
    });
  });

  group('feetFromMeters / formatFeet', () {
    test('converts meters to feet, rounded to a whole number', () {
      expect(feetFromMeters(1), closeTo(3.28084, 0.0001));
      expect(formatFeet(100), '328');
      expect(formatFeet(0), '0');
    });
  });

  group('SpeedUnit', () {
    test('distanceUnit groups km-based and mile-based members', () {
      expect(SpeedUnit.kmh.distanceUnit, DistanceUnit.km);
      expect(SpeedUnit.minKm.distanceUnit, DistanceUnit.km);
      expect(SpeedUnit.mph.distanceUnit, DistanceUnit.mi);
      expect(SpeedUnit.minMi.distanceUnit, DistanceUnit.mi);
    });

    test('isPace is true only for the pace-flavored members', () {
      expect(SpeedUnit.kmh.isPace, isFalse);
      expect(SpeedUnit.minKm.isPace, isTrue);
      expect(SpeedUnit.mph.isPace, isFalse);
      expect(SpeedUnit.minMi.isPace, isTrue);
    });

    test('toggled swaps speed <-> pace within the same distance unit', () {
      expect(SpeedUnit.kmh.toggled, SpeedUnit.minKm);
      expect(SpeedUnit.minKm.toggled, SpeedUnit.kmh);
      expect(SpeedUnit.mph.toggled, SpeedUnit.minMi);
      expect(SpeedUnit.minMi.toggled, SpeedUnit.mph);
    });

    test(
      'initialFor picks the speed-flavored member for each distance unit',
      () {
        expect(SpeedUnit.initialFor(DistanceUnit.km), SpeedUnit.kmh);
        expect(SpeedUnit.initialFor(DistanceUnit.mi), SpeedUnit.mph);
      },
    );
  });

  group('formatSpeedOrPace', () {
    test('formats km/h with its suffix', () {
      expect(formatSpeedOrPace(10 / 3.6, SpeedUnit.kmh), '10.0 km/h');
    });

    test('formats min/km with its suffix', () {
      expect(formatSpeedOrPace(1000 / 300, SpeedUnit.minKm), '5:00 /km');
    });

    test('formats mph with its suffix', () {
      expect(formatSpeedOrPace(0.44704, SpeedUnit.mph), '1.0 mph');
    });

    test('formats min/mi with its suffix', () {
      expect(formatSpeedOrPace(1609.344 / 300, SpeedUnit.minMi), '5:00 /mi');
    });

    test('shows a unit-appropriate placeholder when speed is null', () {
      expect(formatSpeedOrPace(null, SpeedUnit.kmh), '--.- km/h');
      expect(formatSpeedOrPace(null, SpeedUnit.minKm), '--:-- /km');
      expect(formatSpeedOrPace(null, SpeedUnit.mph), '--.- mph');
      expect(formatSpeedOrPace(null, SpeedUnit.minMi), '--:-- /mi');
    });
  });
}
