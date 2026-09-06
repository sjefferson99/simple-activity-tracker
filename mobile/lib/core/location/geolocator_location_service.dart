import 'dart:io' show Platform;

import 'package:geolocator/geolocator.dart';

import 'location_permission_state.dart';
import 'location_sample.dart';
import 'location_service.dart';

class GeolocatorLocationService implements LocationService {
  @override
  Future<LocationPermissionState> checkPermission() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      return LocationPermissionState.serviceDisabled;
    }
    return _mapPermission(await Geolocator.checkPermission());
  }

  @override
  Future<LocationPermissionState> requestPermission() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      return LocationPermissionState.serviceDisabled;
    }

    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    return _mapPermission(permission);
  }

  LocationPermissionState _mapPermission(LocationPermission permission) {
    switch (permission) {
      case LocationPermission.always:
      case LocationPermission.whileInUse:
        return LocationPermissionState.granted;
      case LocationPermission.deniedForever:
        return LocationPermissionState.deniedForever;
      case LocationPermission.denied:
      case LocationPermission.unableToDetermine:
        return LocationPermissionState.denied;
    }
  }

  @override
  Stream<LocationSample> get stream =>
      Geolocator.getPositionStream(locationSettings: _settings())
          .map(_toSample);

  /// Per-platform tuning. The Android and Apple settings classes expose
  /// different background mechanisms, so they can't be expressed as one
  /// shared LocationSettings.
  LocationSettings _settings() {
    if (Platform.isAndroid) {
      return AndroidSettings(
        accuracy: LocationAccuracy.bestForNavigation,
        distanceFilter: 0,
        intervalDuration: const Duration(seconds: 1),
        // enableWakeLock defaults to false; wakelock_plus already keeps
        // the screen on during tracking (see LiveRunController), and
        // enabling it here would need the WAKE_LOCK manifest permission.
        //
        // forceLocationManager routes through Android's legacy
        // LocationManager/GPS_PROVIDER instead of Play Services'
        // FusedLocationProviderClient, which blends in Wi-Fi/cell-based
        // positioning and (per #49) can stall indefinitely waiting on that
        // network-location backend when Wi-Fi is off, even though GPS
        // itself is on and working. This trades away fused positioning's
        // faster/smoother fixes in open sky for not depending on Wi-Fi to
        // get a fix at all.
        forceLocationManager: true,
        foregroundNotificationConfig: const ForegroundNotificationConfig(
          notificationTitle: 'Simple Activity Tracker',
          notificationText: 'Tracking your run',
        ),
      );
    }

    if (Platform.isIOS) {
      return AppleSettings(
        accuracy: LocationAccuracy.bestForNavigation,
        distanceFilter: 0,
        activityType: ActivityType.fitness,
        // Requires the `location` UIBackgroundModes entry in Info.plist.
        allowBackgroundLocationUpdates: true,
        pauseLocationUpdatesAutomatically: false,
      );
    }

    return const LocationSettings(
      accuracy: LocationAccuracy.bestForNavigation,
      distanceFilter: 0,
    );
  }

  LocationSample _toSample(Position position) {
    return LocationSample(
      latitude: position.latitude,
      longitude: position.longitude,
      elevationMeters: position.altitude,
      speedMps: position.speed >= 0 ? position.speed : null,
      accuracyMeters: position.accuracy,
      hasAccuracy: position.hasAccuracy,
      timestamp: position.timestamp,
    );
  }
}
