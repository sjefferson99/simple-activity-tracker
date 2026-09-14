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

  group('formatSpeedDelta', () {
    // 5:00/km == 1000/300 m/s.
    final targetMps = 1000 / 300;

    test('reports "on target" within tolerance', () {
      expect(formatSpeedDelta(targetMps, targetMps, SpeedUnit.minKm), 'on target');
      // 4% faster is still within the 5% band.
      expect(
        formatSpeedDelta(targetMps * 1.04, targetMps, SpeedUnit.minKm),
        'on target',
      );
    });

    test(
      'pace: running faster than target (lower pace number) points the arrow UP, meaning "slow down"',
      () {
        // 10% faster than target speed => a lower (faster) pace number.
        final fasterMps = targetMps * 1.10;
        final delta = formatSpeedDelta(fasterMps, targetMps, SpeedUnit.minKm);
        expect(delta, startsWith('▲'));
        expect(delta, contains('fast'));
      },
    );

    test(
      'pace: running slower than target (higher pace number) points the arrow DOWN, meaning "speed up"',
      () {
        final slowerMps = targetMps * 0.90;
        final delta = formatSpeedDelta(slowerMps, targetMps, SpeedUnit.minKm);
        expect(delta, startsWith('▼'));
        expect(delta, contains('slow'));
      },
    );

    test(
      'pace mi: same arrow convention as pace km',
      () {
        final targetMi = 1609.344 / 300;
        expect(
          formatSpeedDelta(targetMi * 1.10, targetMi, SpeedUnit.minMi),
          startsWith('▲'),
        );
        expect(
          formatSpeedDelta(targetMi * 0.90, targetMi, SpeedUnit.minMi),
          startsWith('▼'),
        );
      },
    );

    test(
      'speed: running faster than target (higher km/h number) points the arrow DOWN, meaning "slow down"',
      () {
        final fasterMps = targetMps * 1.10;
        final delta = formatSpeedDelta(fasterMps, targetMps, SpeedUnit.kmh);
        expect(delta, startsWith('▼'));
        expect(delta, contains('fast'));
      },
    );

    test(
      'speed: running slower than target (lower km/h number) points the arrow UP, meaning "speed up"',
      () {
        final slowerMps = targetMps * 0.90;
        final delta = formatSpeedDelta(slowerMps, targetMps, SpeedUnit.kmh);
        expect(delta, startsWith('▲'));
        expect(delta, contains('slow'));
      },
    );

    test(
      'speed mph: same arrow convention as speed km/h',
      () {
        final targetMi = 1609.344 / 300;
        expect(
          formatSpeedDelta(targetMi * 1.10, targetMi, SpeedUnit.mph),
          startsWith('▼'),
        );
        expect(
          formatSpeedDelta(targetMi * 0.90, targetMi, SpeedUnit.mph),
          startsWith('▲'),
        );
      },
    );
  });

  group('formatSplitSizeMeters', () {
    test('shows whole meters under 1km for a km-kind split', () {
      expect(formatSplitSizeMeters(400, DistanceUnit.km), '400 m');
    });

    test('shows trimmed decimal km at or above 1km', () {
      expect(formatSplitSizeMeters(1000, DistanceUnit.km), '1 km');
      expect(formatSplitSizeMeters(1500, DistanceUnit.km), '1.5 km');
    });

    test('shows decimal miles for a mile-kind split', () {
      expect(formatSplitSizeMeters(1609.344, DistanceUnit.mi), '1 mi');
      expect(formatSplitSizeMeters(804.672, DistanceUnit.mi), '0.5 mi');
    });

    test('shows feet for a small mile-kind split', () {
      expect(formatSplitSizeMeters(30, DistanceUnit.mi), '98 ft');
    });
  });

  group('formatSplitSizeSeconds / formatMinSec', () {
    test('formats whole minutes and seconds as m:ss', () {
      expect(formatSplitSizeSeconds(90), '1:30');
      expect(formatMinSec(const Duration(seconds: 90)), '1:30');
      expect(formatMinSec(const Duration(minutes: 5)), '5:00');
    });
  });

  group('parseMinSec', () {
    test('parses a valid m:ss string', () {
      expect(parseMinSec('1:30'), const Duration(minutes: 1, seconds: 30));
      expect(parseMinSec('0:05'), const Duration(seconds: 5));
    });

    test('treats a colon-less whole number as whole minutes', () {
      // Easy to forget the colon on a phone keyboard — "5" for a pace/
      // duration field can only sensibly mean "5 minutes".
      expect(parseMinSec('5'), const Duration(minutes: 5));
      expect(parseMinSec('90'), const Duration(minutes: 90));
      expect(parseMinSec('0'), Duration.zero);
      expect(parseMinSec(' 5 '), const Duration(minutes: 5));
    });

    test('returns null for malformed input', () {
      expect(parseMinSec('abc'), isNull);
      expect(parseMinSec('1:30:00'), isNull);
      expect(parseMinSec('-5'), isNull);
      expect(parseMinSec('1:60'), isNull);
      expect(parseMinSec('1:-5'), isNull);
    });
  });

  group('parsePaceToMps / parseSpeedToMps round trips', () {
    test('parsePaceToMps round-trips formatPace for km', () {
      final mps = parsePaceToMps('5:00', SpeedUnit.minKm);
      expect(mps, isNotNull);
      expect(formatPace(paceSecPerKmFromMps(mps!)), '5:00');
    });

    test('parsePaceToMps round-trips formatPace for mi', () {
      final mps = parsePaceToMps('8:00', SpeedUnit.minMi);
      expect(mps, isNotNull);
      expect(formatPace(paceSecPerMileFromMps(mps!)), '8:00');
    });

    test('parsePaceToMps rejects zero/garbage', () {
      expect(parsePaceToMps('0:00', SpeedUnit.minKm), isNull);
      expect(parsePaceToMps('0', SpeedUnit.minKm), isNull);
      expect(parsePaceToMps('abc', SpeedUnit.minKm), isNull);
    });

    test(
      'parsePaceToMps accepts a colon-less whole-minute shorthand (e.g. "5" for "5:00")',
      () {
        // A real-device bug: typing just "5" (forgetting the colon) used to
        // be rejected outright and silently revert the field.
        final withColon = parsePaceToMps('5:00', SpeedUnit.minKm);
        final shorthand = parsePaceToMps('5', SpeedUnit.minKm);
        expect(shorthand, isNotNull);
        expect(shorthand, withColon);
      },
    );

    test('parseSpeedToMps round-trips formatKmh', () {
      final mps = parseSpeedToMps('12.0', SpeedUnit.kmh);
      expect(mps, isNotNull);
      expect(formatKmh(mps!), '12.0');
    });

    test('parseSpeedToMps round-trips formatMph', () {
      final mps = parseSpeedToMps('8.0', SpeedUnit.mph);
      expect(mps, isNotNull);
      expect(formatMph(mps!), '8.0');
    });

    test('parseSpeedToMps rejects zero/negative/garbage', () {
      expect(parseSpeedToMps('0', SpeedUnit.kmh), isNull);
      expect(parseSpeedToMps('-5', SpeedUnit.kmh), isNull);
      expect(parseSpeedToMps('abc', SpeedUnit.kmh), isNull);
    });
  });

  group('formatTargetForEditing', () {
    test('formats a pace target as m:ss', () {
      final mps = 1000 / 300;
      expect(formatTargetForEditing(mps, SpeedUnit.minKm), '5:00');
    });

    test('formats a speed target as a plain decimal', () {
      expect(formatTargetForEditing(10 / 3.6, SpeedUnit.kmh), '10.0');
    });
  });
}
