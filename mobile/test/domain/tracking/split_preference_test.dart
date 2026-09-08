import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';

void main() {
  group('gpxSplitType', () {
    test('maps each SplitKind to its wire value', () {
      expect(
        const SplitPreference(kind: SplitKind.distanceKm, value: 1).gpxSplitType,
        'distance_km',
      );
      expect(
        const SplitPreference(kind: SplitKind.distanceMi, value: 1).gpxSplitType,
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

    test('round-trips a valid time_min pair', () {
      expect(
        SplitPreference.fromGpxValues('time_min', '10'),
        const SplitPreference(kind: SplitKind.timeMin, value: 10),
      );
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
