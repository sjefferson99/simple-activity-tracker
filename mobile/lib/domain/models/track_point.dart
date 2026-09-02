import '../../core/location/location_sample.dart';

/// A single accepted point in a run's track. Distinct from [LocationSample]
/// so the domain layer never depends on how a fix was obtained.
class TrackPoint {
  final double latitude;
  final double longitude;
  final double? elevationMeters;
  final DateTime timestamp;
  final double accuracyMeters;

  const TrackPoint({
    required this.latitude,
    required this.longitude,
    required this.timestamp,
    required this.accuracyMeters,
    this.elevationMeters,
  });

  factory TrackPoint.fromSample(LocationSample sample) => TrackPoint(
        latitude: sample.latitude,
        longitude: sample.longitude,
        elevationMeters: sample.elevationMeters,
        timestamp: sample.timestamp,
        accuracyMeters: sample.accuracyMeters,
      );
}
