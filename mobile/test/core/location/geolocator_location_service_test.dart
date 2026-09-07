import 'package:flutter_test/flutter_test.dart';
import 'package:geolocator/geolocator.dart';
import 'package:simple_activity_tracker/core/location/geolocator_location_service.dart';

/// Builds a position the way geolocator_android 5.0.3's
/// `AndroidPosition.fromMap` does: values populated, every `has*` flag left
/// at its false default. This is what a real Android fix looks like to the
/// app, regardless of what the chip measured. (A plain [Position] has the
/// same defaults, so the Android subclass isn't needed to reproduce it.)
Position _androidFix({required double accuracy, required double speed}) =>
    Position(
      latitude: 51.5,
      longitude: -0.1,
      timestamp: DateTime.utc(2026, 1, 1, 9),
      accuracy: accuracy,
      altitude: 12,
      altitudeAccuracy: 0,
      heading: 0,
      headingAccuracy: 0,
      speed: speed,
      speedAccuracy: 0,
    );

void main() {
  group('sampleFromPosition on Android (has* flags always false upstream)', () {
    test('a measured accuracy and speed are recognised despite the flags', () {
      final sample = sampleFromPosition(_androidFix(accuracy: 4.2, speed: 1.7));

      expect(sample.hasAccuracy, isTrue);
      expect(sample.accuracyMeters, 4.2);
      expect(sample.hasSpeed, isTrue);
      expect(sample.speedMps, 1.7);
    });

    test(
      'an unmeasured accuracy (substituted 0.0) is not treated as measured',
      () {
        final sample = sampleFromPosition(_androidFix(accuracy: 0, speed: 1.7));

        expect(sample.hasAccuracy, isFalse);
      },
    );

    test('a 0.0 speed keeps the raw value but is flagged as ambiguous', () {
      final sample = sampleFromPosition(_androidFix(accuracy: 4.2, speed: 0));

      expect(sample.speedMps, 0.0);
      expect(sample.hasSpeed, isFalse);
    });

    test('a negative speed (iOS "invalid") maps to null', () {
      final sample = sampleFromPosition(_androidFix(accuracy: 4.2, speed: -1));

      expect(sample.speedMps, isNull);
      expect(sample.hasSpeed, isFalse);
    });
  });
}
