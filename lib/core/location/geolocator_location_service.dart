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
  Stream<LocationSample> get stream => Geolocator.getPositionStream(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.bestForNavigation,
          distanceFilter: 0,
        ),
      ).map(_toSample);

  LocationSample _toSample(Position position) {
    return LocationSample(
      latitude: position.latitude,
      longitude: position.longitude,
      elevationMeters: position.altitude,
      speedMps: position.speed >= 0 ? position.speed : null,
      accuracyMeters: position.accuracy,
      timestamp: position.timestamp,
    );
  }
}
