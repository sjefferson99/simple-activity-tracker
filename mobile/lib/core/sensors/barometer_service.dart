/// Abstraction over the phone's pressure sensor. Same discipline as
/// `LocationService`: nothing else in the app talks to the sensor plugin.
abstract class BarometerService {
  /// Air pressure readings in hectopascals, many per second while a
  /// subscription is active. Errors immediately on a phone with no barometer,
  /// so callers must handle `onError`; a missing sensor never stops a run.
  Stream<double> get pressureHpa;
}
