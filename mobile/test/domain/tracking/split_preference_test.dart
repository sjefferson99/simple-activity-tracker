import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/units/units.dart'
    show DistanceUnit;
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';

void main() {
  group('effectiveDistanceUnit', () {
    test('a km split is always km, regardless of timeSplitDisplayUnit', () {
      expect(
        const SplitPreference(
          kind: SplitKind.distanceKm,
          value: 1,
          timeSplitDisplayUnit: DistanceUnit.mi,
        ).effectiveDistanceUnit,
        DistanceUnit.km,
      );
    });

    test('a mile split is always mi, regardless of timeSplitDisplayUnit', () {
      expect(
        const SplitPreference(
          kind: SplitKind.distanceMi,
          value: 1,
          timeSplitDisplayUnit: DistanceUnit.km,
        ).effectiveDistanceUnit,
        DistanceUnit.mi,
      );
    });

    test('a time split follows timeSplitDisplayUnit', () {
      expect(
        const SplitPreference(
          kind: SplitKind.timeMin,
          value: 5,
          timeSplitDisplayUnit: DistanceUnit.mi,
        ).effectiveDistanceUnit,
        DistanceUnit.mi,
      );
      expect(
        const SplitPreference(
          kind: SplitKind.timeMin,
          value: 5,
        ).effectiveDistanceUnit,
        DistanceUnit.km,
      );
    });
  });

  group('gpxSplitType', () {
    test('maps each SplitKind to its wire value', () {
      expect(
        const SplitPreference(
          kind: SplitKind.distanceKm,
          value: 1,
        ).gpxSplitType,
        'distance_km',
      );
      expect(
        const SplitPreference(
          kind: SplitKind.distanceMi,
          value: 1,
        ).gpxSplitType,
        'distance_mi',
      );
      expect(
        const SplitPreference(kind: SplitKind.timeMin, value: 5).gpxSplitType,
        'time_min',
      );
    });
  });

  group('fromGpxValues', () {
    test('round-trips a valid distance_km pair', () {
      expect(
        SplitPreference.fromGpxValues('distance_km', '1'),
        const SplitPreference(kind: SplitKind.distanceKm, value: 1),
      );
    });

    test('round-trips a valid distance_mi pair', () {
      expect(
        SplitPreference.fromGpxValues('distance_mi', '3'),
        const SplitPreference(kind: SplitKind.distanceMi, value: 3),
      );
    });

    test('round-trips a valid time_min pair, defaulting to km display', () {
      final preference = SplitPreference.fromGpxValues('time_min', '10');
      expect(
        preference,
        const SplitPreference(kind: SplitKind.timeMin, value: 10),
      );
      expect(preference!.timeSplitDisplayUnit, DistanceUnit.km);
    });

    test('returns null for an unrecognized split type', () {
      expect(SplitPreference.fromGpxValues('distance_furlongs', '1'), isNull);
    });

    test('returns null for a non-integer value', () {
      expect(SplitPreference.fromGpxValues('distance_km', 'abc'), isNull);
    });

    test('returns null for a non-positive value', () {
      expect(SplitPreference.fromGpxValues('distance_km', '0'), isNull);
      expect(SplitPreference.fromGpxValues('distance_km', '-1'), isNull);
    });

    test('returns null when either value is missing', () {
      expect(SplitPreference.fromGpxValues(null, '1'), isNull);
      expect(SplitPreference.fromGpxValues('distance_km', null), isNull);
      expect(SplitPreference.fromGpxValues(null, null), isNull);
    });
  });
}
