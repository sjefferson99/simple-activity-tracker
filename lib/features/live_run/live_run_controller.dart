import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../../core/files/run_file_paths.dart';
import '../../core/files/run_gpx_log.dart';
import '../../core/location/geolocator_location_service.dart';
import '../../core/location/location_permission_state.dart';
import '../../core/location/location_sample.dart';
import '../../core/location/location_service.dart';
import '../../domain/geo_math.dart';
import '../../domain/models/live_metrics.dart';
import '../../domain/models/track_point.dart';
import '../../domain/tracking/metrics_engine.dart';
import '../../domain/tracking/run_phase.dart';
import 'live_run_state.dart';

const _gpxFlushInterval = Duration(seconds: 5);

final locationServiceProvider = Provider<LocationService>((ref) {
  return GeolocatorLocationService();
});

final liveRunControllerProvider =
    NotifierProvider<LiveRunController, LiveRunState>(LiveRunController.new);

class LiveRunController extends Notifier<LiveRunState> {
  StreamSubscription<LocationSample>? _subscription;
  TrackPoint? _previousPoint;
  MetricsEngine? _metricsEngine;
  RunGpxLog? _gpxLog;
  Timer? _flushTimer;

  @override
  LiveRunState build() {
    ref.onDispose(_disposeRun);
    return const LiveRunIdle();
  }

  RunPhase? get _phase => switch (state) {
        LiveRunActive(:final phase) => phase,
        _ => null,
      };

  bool get isTrackingOrPaused =>
      _phase == RunPhase.tracking || _phase == RunPhase.paused;

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
    _metricsEngine = MetricsEngine();
    _gpxLog = RunGpxLog(await newRunGpxFile(DateTime.now()));
    _flushTimer = Timer.periodic(_gpxFlushInterval, (_) => _gpxLog?.flush());

    await WakelockPlus.enable();

    state = const LiveRunAcquiring();
    _subscription = service.stream.listen(_onSample);
  }

  void pause() {
    if (_phase != RunPhase.tracking) return;
    _previousPoint = null;
    _emitActive(RunPhase.paused, speedMps: null, accuracyMeters: null);
  }

  void resume() {
    if (_phase != RunPhase.paused) return;
    _previousPoint = null;
    _metricsEngine?.resetSegmentAnchor();
    _gpxLog?.startNewSegment();
    _emitActive(RunPhase.tracking, speedMps: null, accuracyMeters: null);
  }

  Future<void> stop() async {
    final metrics = _metricsEngine?.metrics ?? LiveMetrics.zero;
    await _disposeRun();
    state = LiveRunFinished(metrics: metrics);
  }

  Future<void> startNewRun() async {
    state = const LiveRunIdle();
    await start();
  }

  Future<void> _disposeRun() async {
    await _subscription?.cancel();
    _subscription = null;
    _flushTimer?.cancel();
    _flushTimer = null;
    await _gpxLog?.finalizeAndFlush();
    _gpxLog = null;
    await WakelockPlus.disable();
  }

  void _onSample(LocationSample sample) {
    if (_phase == RunPhase.paused) return;

    final point = TrackPoint.fromSample(sample);
    final speed = sample.speedMps ?? _fallbackSpeed(point);
    _previousPoint = point;

    _metricsEngine?.addPoint(point);
    _gpxLog?.addPoint(point);

    _emitActive(RunPhase.tracking, speedMps: speed, accuracyMeters: sample.accuracyMeters);
  }

  double? _fallbackSpeed(TrackPoint point) {
    final previous = _previousPoint;
    if (previous == null) return null;
    return speedMpsBetween(previous, point);
  }

  void _emitActive(
    RunPhase phase, {
    required double? speedMps,
    required double? accuracyMeters,
  }) {
    final previousAccuracy =
        state is LiveRunActive ? (state as LiveRunActive).accuracyMeters : 0.0;

    state = LiveRunActive(
      phase: phase,
      speedMps: speedMps,
      accuracyMeters: accuracyMeters ?? previousAccuracy,
      metrics: _metricsEngine?.metrics ?? LiveMetrics.zero,
    );
  }
}
