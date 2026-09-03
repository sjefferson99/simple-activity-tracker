import 'dart:async';
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:uuid/uuid.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../../core/files/run_export_service.dart';
import '../../core/files/run_file_paths.dart';
import '../../core/files/run_gpx_log.dart';
import '../../core/location/geolocator_location_service.dart';
import '../../core/location/location_permission_state.dart';
import '../../core/location/location_sample.dart';
import '../../core/location/location_service.dart';
import '../../core/sync/file_run_store.dart';
import '../../core/sync/sync_service.dart';
import '../../core/tracking/activity_mode_controller.dart';
import '../../domain/geo_math.dart';
import '../../domain/models/live_metrics.dart';
import '../../domain/models/run_record.dart';
import '../../domain/models/run_summary.dart';
import '../../domain/models/sync_status.dart';
import '../../domain/models/track_point.dart';
import '../../domain/tracking/activity_mode.dart';
import '../../domain/tracking/metrics_engine.dart';
import '../../domain/tracking/run_phase.dart';
import 'live_run_state.dart';

const _gpxFlushInterval = Duration(seconds: 5);

String get _sourcePlatform {
  if (Platform.isAndroid) return 'android';
  if (Platform.isIOS) return 'ios';
  return 'unknown';
}

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
  File? _currentGpxFile;
  final RunExportService _exportService = RunExportService();

  String? _clientRunId;
  DateTime? _startedAt;
  ActivityMode? _activityMode;
  String? _cachedAppVersion;

  // Bumped every time a run starts. stop() closes over the token for the
  // run it's finishing, so a slow export that resolves after the user has
  // already started (and possibly finished) another run can tell it no
  // longer owns `state` and must not touch it — `state is LiveRunFinished`
  // alone isn't enough, since the *next* run reaching Finished first would
  // otherwise look like a valid target for the *previous* run's result.
  int _runToken = 0;

  @override
  LiveRunState build() {
    // onDispose cannot await, so the final flush here is best-effort: the
    // synchronous part (stopping the stream and timer) always completes,
    // but the last few seconds of track may be lost if the provider is torn
    // down mid-run. Stopping via the UI goes through stop(), which awaits
    // properly — this path only covers app teardown.
    ref.onDispose(() {
      unawaited(_disposeRun());
    });
    return const LiveRunIdle();
  }

  RunPhase? get _phase => switch (state) {
    LiveRunActive(:final phase) => phase,
    _ => null,
  };

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

    // Tear down any run still in flight before allocating a new one. start()
    // is re-entrant — state stays LiveRunIdle across every await below, so a
    // double-tapped Start (or startNewRun() without a stop()) gets this far
    // twice. Each resource has to go, not just the subscription: a stacked
    // listener double-counts every fix (service.stream opens a fresh platform
    // stream per access rather than sharing one), an orphaned flush timer
    // keeps firing into whatever run is current for the app's lifetime, and a
    // dropped RunGpxLog loses its unflushed tail and never finalizes.
    await _disposeRun();
    _runToken++;

    _clientRunId = const Uuid().v4();
    _startedAt = DateTime.now().toUtc();

    _previousPoint = null;
    // Fixed for the run's duration — read once here, not from a live
    // `ref.watch`, so switching the home screen toggle mid-run (which the UI
    // already disables, but this is the actual guarantee) can't change which
    // plausibility thresholds an in-progress run is judged against. The same
    // captured value is reused at stop() for the RunRecord/RunSummary, since
    // the toggle may have moved on by then.
    _activityMode = ref.read(activityModeControllerProvider);
    _metricsEngine = MetricsEngine(mode: _activityMode!);
    _currentGpxFile = await newRunGpxFile(DateTime.now());
    _gpxLog = RunGpxLog(_currentGpxFile!);
    // A periodic flush that fails is not fatal: every flush rewrites the
    // whole track, so the next one recovers whatever this one missed.
    // Swallow it here rather than letting it surface as an unhandled error.
    _flushTimer = Timer.periodic(
      _gpxFlushInterval,
      (_) => _gpxLog?.flush().catchError((_) {}),
    );

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
    final gpxFile = _currentGpxFile;
    final clientRunId = _clientRunId;
    final startedAt = _startedAt;
    final activityMode = _activityMode;
    final finishedRunToken = _runToken;
    await _disposeRun();

    // Sidecar write happens before the state switch (docs/WEB-PLAN.md §6.3)
    // — it's a small local JSON write, not a network call, so this doesn't
    // delay the summary screen the way waiting on SyncService would.
    if (gpxFile != null &&
        clientRunId != null &&
        startedAt != null &&
        activityMode != null) {
      final summary = RunSummary.fromMetrics(
        clientRunId: clientRunId,
        startedAt: startedAt,
        endedAt: DateTime.now().toUtc(),
        activityMode: activityMode,
        metrics: metrics,
        sourcePlatform: _sourcePlatform,
        sourceAppVersion: await _appVersion(),
      );
      await ref
          .read(runStoreProvider)
          .save(
            RunRecord(
              clientRunId: clientRunId,
              gpxPath: gpxFile.path,
              activityMode: activityMode,
              summary: summary,
              syncStatus: const SyncStatusPending(),
            ),
          );
    }
    _clientRunId = null;
    _startedAt = null;
    _activityMode = null;

    state = LiveRunFinished(
      metrics: metrics,
      activityMode: activityMode ?? ActivityMode.running,
      clientRunId: clientRunId,
    );
    // Fire-and-forget — a slow or failed upload must never delay the
    // summary screen, which is already showing by this point.
    ref.read(syncServiceProvider).runFinished();

    // Export after the state switch, not before — a slow or failed copy
    // must never delay showing the run summary. exportedTo starts null and
    // fills in once the copy lands. `state is LiveRunFinished` alone isn't
    // enough of a guard: if the user starts and finishes another run before
    // this export resolves, that run's state is *also* LiveRunFinished, and
    // this run's stale result would be misattributed to it. The token check
    // catches that — it only fires if _runToken hasn't moved on since.
    if (gpxFile != null) {
      final exportedTo = await _exportService.exportToPublicStorage(gpxFile);
      if (exportedTo != null &&
          _runToken == finishedRunToken &&
          state is LiveRunFinished) {
        state = (state as LiveRunFinished).copyWith(exportedTo: exportedTo);
      }
    }
  }

  Future<void> startNewRun() async {
    state = const LiveRunIdle();
    await start();
  }

  /// Returns to the idle/home screen from [LiveRunFinished] without starting
  /// a new run — unlike [startNewRun], which immediately begins GPS
  /// acquisition. All of a finished run's resources (subscription, GPX log,
  /// wakelock) are already torn down by [stop] before that state is reached,
  /// so this is just a state reset, not cleanup. Lets the user change the
  /// activity mode before their next run, which the home screen only offers
  /// outside an active/finished run.
  void goToIdle() {
    if (state is! LiveRunFinished) return;
    state = const LiveRunIdle();
  }

  Future<void> _disposeRun() async {
    // Cancel the timer first and synchronously, so no new flush can start
    // after teardown begins (matters on the un-awaited onDispose path).
    _flushTimer?.cancel();
    _flushTimer = null;
    await _subscription?.cancel();
    _subscription = null;

    // The wakelock must be released even if the final write fails, or the
    // screen stays forced on for the rest of the app's life.
    try {
      await _gpxLog?.finalizeAndFlush();
    } finally {
      _gpxLog = null;
      _currentGpxFile = null;
      await WakelockPlus.disable();
    }
  }

  void _onSample(LocationSample sample) {
    if (_phase == RunPhase.paused) return;

    final point = TrackPoint.fromSample(sample);
    final speed = sample.speedMps ?? _fallbackSpeed(point);
    _previousPoint = point;

    // The engine discards low-accuracy fixes so they can't inflate distance,
    // but the GPX deliberately keeps every fix — the file is the raw track,
    // and filtering is a display/metrics concern a viewer can redo itself.
    _metricsEngine?.addPoint(point);
    _gpxLog?.addPoint(point);

    _emitActive(
      RunPhase.tracking,
      speedMps: speed,
      accuracyMeters: sample.accuracyMeters,
    );
  }

  /// `1.0.0+1` — matches pubspec's version+build format, and the shape the
  /// server expects for RunSummary.source.app_version (docs/WEB-PLAN.md
  /// §5.3). Cached: it can't change while the app is running.
  Future<String> _appVersion() async {
    final cached = _cachedAppVersion;
    if (cached != null) return cached;
    final info = await PackageInfo.fromPlatform();
    final version = '${info.version}+${info.buildNumber}';
    _cachedAppVersion = version;
    return version;
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
    final previousAccuracy = state is LiveRunActive
        ? (state as LiveRunActive).accuracyMeters
        : 0.0;

    state = LiveRunActive(
      phase: phase,
      speedMps: speedMps,
      accuracyMeters: accuracyMeters ?? previousAccuracy,
      metrics: _metricsEngine?.metrics ?? LiveMetrics.zero,
      // Fixed for the run's whole duration (see start()); _activityMode is
      // only ever null before a run has started, at which point nothing
      // reaches LiveRunActive.
      activityMode: _activityMode ?? ActivityMode.running,
    );
  }
}
