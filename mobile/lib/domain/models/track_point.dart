import '../../core/location/location_sample.dart';

/// A single accepted point in a run's track. Distinct from [LocationSample]
/// so the domain layer never depends on how a fix was obtained.
class TrackPoint {
  final double latitude;
  final double longitude;
  final double? elevationMeters;
  final DateTime timestamp;
  final double accuracyMeters;

  /// See [LocationSample.hasAccuracy]. Defaults to true so call sites that
  /// construct a [TrackPoint] directly (tests, anything not sourced from a
  /// real GPS fix) don't spuriously fail the accuracy-measured check.
  final bool hasAccuracy;

  /// Raw platform-reported speed in meters/second; a `0.0` is only a
  /// trustworthy "stationary" when [hasSpeed] is true — see
  /// [LocationSample.speedMps].
  final double? speedMps;

  /// See [LocationSample.hasSpeed]. Defaults to false so a [TrackPoint] built
  /// without an explicit speed (tests, GPX round-trips) doesn't imply a
  /// measured-but-null speed.
  final bool hasSpeed;

  const TrackPoint({
    required this.latitude,
    required this.longitude,
    required this.timestamp,
    required this.accuracyMeters,
    this.hasAccuracy = true,
    this.elevationMeters,
    this.speedMps,
    this.hasSpeed = false,
  });

  factory TrackPoint.fromSample(LocationSample sample) => TrackPoint(
        latitude: sample.latitude,
        longitude: sample.longitude,
        elevationMeters: sample.elevationMeters,
        timestamp: sample.timestamp,
        accuracyMeters: sample.accuracyMeters,
        hasAccuracy: sample.hasAccuracy,
        speedMps: sample.speedMps,
        hasSpeed: sample.hasSpeed,
      );
}
