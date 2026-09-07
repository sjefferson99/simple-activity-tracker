/// Our own representation of a GPS fix, decoupled from any plugin's types.
/// Nothing outside `core/location` should ever import a geolocator type.
class LocationSample {
  final double latitude;
  final double longitude;
  final double? elevationMeters;

  /// Speed as reported by the platform for this fix, in meters/second — the
  /// raw value, which on Android is `0.0` both for "stationary" and for
  /// "not measured". Null only when the platform gave nothing usable at all.
  final double? speedMps;

  /// Whether [speedMps] is unambiguously a real measurement. False for a
  /// `0.0` that may or may not have been measured — see `sampleFromPosition`
  /// in `geolocator_location_service.dart` for why the platform's own flag
  /// can't be relied on.
  final bool hasSpeed;

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
    this.hasSpeed = false,
  });
}
