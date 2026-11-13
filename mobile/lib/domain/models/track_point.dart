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

  /// Mean barometer reading over the second before this fix, in
  /// hectopascals (issue #184).
  /// Null on a phone with no barometer, or if the sensor stopped reporting.
  final double? pressureHpa;

  /// Elevation-tuning diagnostics (docs/BAROMETER-PLAN.md), each null when
  /// unavailable: the spread of the readings averaged into [pressureHpa],
  /// GPS altitude accuracy, and the accelerometer's shake (m/s², gravity
  /// removed) and dominant rhythm over the moments before this fix.
  final double? pressureSdHpa;
  final double? verticalAccuracyMeters;
  final double? motionRmsMps2;
  final double? cadenceHz;

  const TrackPoint({
    required this.latitude,
    required this.longitude,
    required this.timestamp,
    required this.accuracyMeters,
    this.hasAccuracy = true,
    this.elevationMeters,
    this.speedMps,
    this.hasSpeed = false,
    this.pressureHpa,
    this.pressureSdHpa,
    this.verticalAccuracyMeters,
    this.motionRmsMps2,
    this.cadenceHz,
  });

  factory TrackPoint.fromSample(
    LocationSample sample, {
    double? pressureHpa,
    double? pressureSdHpa,
    double? motionRmsMps2,
    double? cadenceHz,
  }) =>
      TrackPoint(
        latitude: sample.latitude,
        longitude: sample.longitude,
        elevationMeters: sample.elevationMeters,
        timestamp: sample.timestamp,
        accuracyMeters: sample.accuracyMeters,
        hasAccuracy: sample.hasAccuracy,
        speedMps: sample.speedMps,
        hasSpeed: sample.hasSpeed,
        pressureHpa: pressureHpa,
        pressureSdHpa: pressureSdHpa,
        verticalAccuracyMeters: sample.verticalAccuracyMeters,
        motionRmsMps2: motionRmsMps2,
        cadenceHz: cadenceHz,
      );
}
