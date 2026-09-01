import 'package:flutter_test/flutter_test.dart';
import 'package:simple_runner/domain/geo_math.dart';
import 'package:simple_runner/domain/models/track_point.dart';

void main() {
  group('haversineDistanceMeters', () {
    test('returns zero for identical points', () {
      final point = TrackPoint(
        latitude: 51.5,
        longitude: -0.12,
        timestamp: DateTime(2026),
      );
      expect(haversineDistanceMeters(point, point), closeTo(0, 0.001));
    });

    test('matches a known one-degree-latitude distance (~111.19 km)', () {
      final a = TrackPoint(latitude: 0, longitude: 0, timestamp: DateTime(2026));
      final b = TrackPoint(latitude: 1, longitude: 0, timestamp: DateTime(2026));
      expect(haversineDistanceMeters(a, b), closeTo(111195, 50));
    });
  });

  group('speedMpsBetween', () {
    test('computes speed from distance and elapsed time', () {
      final a = TrackPoint(
        latitude: 0,
        longitude: 0,
        timestamp: DateTime(2026, 1, 1, 0, 0, 0),
      );
      final b = TrackPoint(
        latitude: 0,
        longitude: 0.001, // roughly 111.2m at the equator
        timestamp: DateTime(2026, 1, 1, 0, 0, 10),
      );
      final speed = speedMpsBetween(a, b);
      expect(speed, isNotNull);
      expect(speed, closeTo(11.12, 0.5));
    });

    test('returns null for a non-positive time delta', () {
      final t = DateTime(2026);
      final a = TrackPoint(latitude: 0, longitude: 0, timestamp: t);
      final b = TrackPoint(latitude: 0, longitude: 0.001, timestamp: t);
      expect(speedMpsBetween(a, b), isNull);
    });
  });
}
