/// Abstraction over the phone's accelerometer, same discipline as
/// `BarometerService`: nothing else in the app talks to the sensor plugin.
abstract class MotionService {
  /// Magnitude of the measured acceleration in m/s², gravity included,
  /// about 50 times a second while a subscription is active. May error on a
  /// phone without the sensor; callers must handle `onError`.
  Stream<double> get accelerationMagnitude;
}
