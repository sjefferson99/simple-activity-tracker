/// Our own representation of a GPS fix, decoupled from any plugin's types.
/// Nothing outside `core/location` should ever import a geolocator type.
class LocationSample {
  final double latitude;
  final double longitude;
  final double? elevationMeters;

  /// Speed reported directly by the GPS fix, in meters/second. Null when
  /// the platform doesn't provide it for this sample.
  final double? speedMps;

  final double accuracyMeters;

  /// Whether the platform actually measured [accuracyMeters] for this fix,
  /// as opposed to it being an unset/placeholder value the platform never
  /// filled in. A fix with this false must be rejected regardless of what
  /// [accuracyMeters] says — see `MetricsEngine.addPoint`.
  final bool hasAccuracy;

  final DateTime timestamp;

  const LocationSample({
    required this.latitude,
    required this.longitude,
    required this.accuracyMeters,
    required this.hasAccuracy,
    required this.timestamp,
    this.elevationMeters,
    this.speedMps,
  });
}
