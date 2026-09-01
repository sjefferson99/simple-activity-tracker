import 'location_permission_state.dart';
import 'location_sample.dart';

/// Abstraction over the platform GPS. Real GPS, emulator, and test fakes
/// are interchangeable behind this interface — nothing else in the app
/// should talk to geolocator directly.
abstract class LocationService {
  /// Checks current permission/service status without prompting the user.
  Future<LocationPermissionState> checkPermission();

  /// Requests permission, prompting the user if needed.
  Future<LocationPermissionState> requestPermission();

  /// Stream of location fixes. Only produces events while a subscription
  /// is active; cancel the subscription to stop consuming GPS.
  Stream<LocationSample> get stream;
}
