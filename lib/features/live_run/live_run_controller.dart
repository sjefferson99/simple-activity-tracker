import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/location/geolocator_location_service.dart';
import '../../core/location/location_permission_state.dart';
import '../../core/location/location_sample.dart';
import '../../core/location/location_service.dart';
import '../../domain/geo_math.dart';
import '../../domain/models/track_point.dart';
import 'live_run_state.dart';

final locationServiceProvider = Provider<LocationService>((ref) {
  return GeolocatorLocationService();
});

final liveRunControllerProvider =
    NotifierProvider<LiveRunController, LiveRunState>(LiveRunController.new);

class LiveRunController extends Notifier<LiveRunState> {
  StreamSubscription<LocationSample>? _subscription;
  TrackPoint? _previousPoint;

  @override
  LiveRunState build() {
    ref.onDispose(() => _subscription?.cancel());
    return const LiveRunIdle();
  }

  bool get isActive => state is LiveRunAcquiring || state is LiveRunActive;

  Future<void> toggle() async {
    if (isActive) {
      await stop();
    } else {
      await start();
    }
  }

  Future<void> start() async {
    final service = ref.read(locationServiceProvider);
    final permission = await service.requestPermission();

    switch (permission) {
      case LocationPermissionState.serviceDisabled:
        state = const LiveRunServiceDisabled();
        return;
      case LocationPermissionState.denied:
        state = const LiveRunPermissionDenied(forever: false);
        return;
      case LocationPermissionState.deniedForever:
        state = const LiveRunPermissionDenied(forever: true);
        return;
      case LocationPermissionState.granted:
        break;
    }

    _previousPoint = null;
    state = const LiveRunAcquiring();
    _subscription = service.stream.listen(_onSample);
  }

  Future<void> stop() async {
    await _subscription?.cancel();
    _subscription = null;
    _previousPoint = null;
    state = const LiveRunIdle();
  }

  void _onSample(LocationSample sample) {
    final point = TrackPoint.fromSample(sample);

    final speed = sample.speedMps ?? _fallbackSpeed(point);
    _previousPoint = point;

    state = LiveRunActive(speedMps: speed, accuracyMeters: sample.accuracyMeters);
  }

  double? _fallbackSpeed(TrackPoint point) {
    final previous = _previousPoint;
    if (previous == null) return null;
    return speedMpsBetween(previous, point);
  }
}
