import 'dart:async';
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meta/meta.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:uuid/uuid.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

import '../../core/audio/split_audio_announcer.dart';
import '../../core/audio/split_audio_service.dart';
import '../../core/audio/split_audio_settings_controller.dart';
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
import '../../core/tracking/split_plan_controller.dart';
import '../../core/units/units.dart' show DistanceUnit, SpeedUnit;
import '../../domain/models/live_metrics.dart';
import '../../domain/models/run_record.dart';
import '../../domain/models/run_summary.dart';
import '../../domain/models/sync_status.dart';
import '../../domain/models/track_point.dart';
import '../../domain/tracking/activity_mode.dart';
import '../../domain/tracking/metrics_engine.dart';
import '../../domain/tracking/display_speed_window.dart';
import '../../domain/tracking/run_clock.dart';
import '../../domain/tracking/run_phase.dart';
import '../../domain/tracking/split_audio_cue.dart';
import '../../domain/tracking/split_audio_settings.dart';
import '../../domain/tracking/split_plan.dart';
import 'live_run_state.dart';

const _gpxFlushInterval = Duration(seconds: 5);

/// How long to wait for a first GPS fix before LiveRunAcquiring surfaces a
/// message instead of spinning silently forever (#49) — GPS may never get a
/// fix at all (indoors, hardware issue, or a Wi-Fi-off provider stall).
const _acquiringTimeout = Duration(seconds: 20);

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
  /// Overridable only by tests, which need a much shorter wait than the real
  /// 20s to exercise the acquiring-timeout path without a slow test run.
  @visibleForTesting
  Duration acquiringTimeout = _acquiringTimeout;

  /// How often the Time tile is refreshed while tracking, independent of
  /// GPS fixes. Overridable only by tests.
  @visibleForTesting
  Duration tickInterval = const Duration(seconds: 1);

  StreamSubscription<LocationSample>? _subscription;
  final DisplaySpeedWindow _displaySpeedWindow = DisplaySpeedWindow();
  MetricsEngine? _metricsEngine;
  RunClock? _runClock;
  RunGpxLog? _gpxLog;
  Timer? _flushTimer;
  Timer? _acquiringTimeoutTimer;
  Timer? _tickTimer;
  File? _currentGpxFile;
  final RunExportService _exportService = RunExportService();

  String? _clientRunId;
  DateTime? _startedAt;
  ActivityMode? _activityMode;
  SplitPlan? _splitPlan;
  String? _cachedAppVersion;

  // Split audio cues (issue #125): the previous tick's metrics, diffed
  // against the current tick's inside _emitActive to detect a split-change
  // or verdict-change transition. Reset to null at the start of every run so
  // a cue can never fire comparing across two different runs.
  LiveMetrics? _previousMetricsForAudio;
  SplitAudioSettings? _audioSettings;

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
    _runClock = RunClock(startedAt: _startedAt!);

    _displaySpeedWindow.reset();
    // Fixed for the run's duration — read once here, not from a live
    // `ref.watch`, so switching the home screen toggle mid-run (which the UI
    // already disables, but this is the actual guarantee) can't change which
    // plausibility thresholds an in-progress run is judged against. The same
    // captured value is reused at stop() for the RunRecord/RunSummary, since
    // the toggle may have moved on by then.
    _activityMode = ref.read(activityModeControllerProvider);
    _splitPlan = ref.read(splitPlanControllerProvider);
    // Fixed for the run's duration, same rationale as _activityMode/
    // _splitPlan above — a mid-run settings change on the Splits screen
    // (already possible while paused) can't retroactively change what an
    // in-progress run announces. Unlike _activityMode/_splitPlan, this
    // specifically awaits the controller's load first (ensureLoaded) rather
    // than a bare ref.read — a stale-default race here means "silently no
    // audio for the whole run" rather than a merely-outdated-but-reasonable
    // fallback, and was a real on-device bug on a cold app launch's first
    // Start tap (see SplitAudioSettingsController's own doc).
    await ref.read(splitAudioSettingsControllerProvider.notifier).ensureLoaded();
    _audioSettings = ref.read(splitAudioSettingsControllerProvider);
    _previousMetricsForAudio = null;
    _playActivityStartedCue();
    _metricsEngine = MetricsEngine(
      mode: _activityMode!,
      splitPlan: _splitPlan!,
    );
    _currentGpxFile = await newRunGpxFile(DateTime.now());
    _gpxLog = RunGpxLog(_currentGpxFile!, _splitPlan!, _activityMode!);
    // A periodic flush that fails is not fatal: every flush rewrites the
    // whole track, so the next one recovers whatever this one missed.
    // Swallow it here rather than letting it surface as an unhandled error.
    _flushTimer = Timer.periodic(
      _gpxFlushInterval,
      (_) => _gpxLog?.flush().catchError((_) {}),
    );

    await WakelockPlus.enable();

    state = const LiveRunAcquiring();
    _acquiringTimeoutTimer = Timer(acquiringTimeout, _onAcquiringTimeout);
    _subscription = service.stream.listen(_onSample);
    // The Time tile must keep counting when no fix is accepted — or none
    // arrives at all — so it can't ride on the sample stream alone.
    _tickTimer = Timer.periodic(tickInterval, (_) => _onTick());
  }

  void _onTick() {
    // Nothing to refresh while acquiring (no tiles yet) or paused (the clock
    // is frozen, so a re-emit would be a no-op).
    if (_phase != RunPhase.tracking) return;
    final current = state as LiveRunActive;
    _emitActive(
      RunPhase.tracking,
      speedMps: current.speedMps,
      accuracyMeters: current.accuracyMeters,
    );
  }

  void _onAcquiringTimeout() {
    // The subscription may have delivered a fix in the same event-loop turn
    // the timer fires, or the run may already have been stopped/cancelled —
    // only touch state if it's still genuinely waiting.
    if (state is! LiveRunAcquiring) return;
    state = const LiveRunAcquiring(timedOut: true);
  }

  void pause() {
    if (_phase != RunPhase.tracking) return;
    _displaySpeedWindow.reset();
    _runClock?.pause(DateTime.now().toUtc());
    _emitActive(RunPhase.paused, speedMps: null, accuracyMeters: null);
  }

  void resume() {
    if (_phase != RunPhase.paused) return;
    _displaySpeedWindow.reset();
    _runClock?.resume(DateTime.now().toUtc());
    _metricsEngine?.resetSegmentAnchor();
    _gpxLog?.startNewSegment();
    _emitActive(RunPhase.tracking, speedMps: null, accuracyMeters: null);
  }

  Future<void> stop() async {
    final metrics = _currentMetrics();
    final gpxFile = _currentGpxFile;
    final clientRunId = _clientRunId;
    final startedAt = _startedAt;
    final activityMode = _activityMode;
    final distanceUnit =
        _splitPlan?.base.effectiveDistanceUnit ?? DistanceUnit.km;
    final prefersPace = _splitPlan?.targetsAsPace ?? true;
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
    _runClock = null;
    _activityMode = null;
    _splitPlan = null;
    _audioSettings = null;
    _previousMetricsForAudio = null;

    state = LiveRunFinished(
      metrics: metrics,
      activityMode: activityMode ?? ActivityMode.running,
      distanceUnit: distanceUnit,
      prefersPace: prefersPace,
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
    // Cancel the timers first and synchronously, so no new flush/timeout can
    // fire after teardown begins (matters on the un-awaited onDispose path).
    _flushTimer?.cancel();
    _flushTimer = null;
    _acquiringTimeoutTimer?.cancel();
    _acquiringTimeoutTimer = null;
    _tickTimer?.cancel();
    _tickTimer = null;
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

    // The first fix has arrived — the acquiring timeout no longer applies,
    // whether or not it already fired.
    _acquiringTimeoutTimer?.cancel();
    _acquiringTimeoutTimer = null;

    final point = TrackPoint.fromSample(sample);

    // The engine discards low-accuracy fixes so they can't inflate distance,
    // but the GPX deliberately keeps every fix — the file is the raw track,
    // and filtering is a display/metrics concern a viewer can redo itself.
    _metricsEngine?.addPoint(point);
    _gpxLog?.addPoint(point);

    // Display-only, position-derived speed (issue #50 follow-up): a
    // measured test found the GPS chip's own speed field reading ~13% low
    // throughout, while position-derived distance/pace matched a stopwatch
    // almost exactly — see DisplaySpeedWindow's doc. Windowed over the last
    // ~3s so it's steady enough to aim a split at, without depending on the
    // chip's speed field at all. The engine's own distance/average/split
    // math is unaffected — it never used chip speed for its own numbers.
    final windowedSpeed = _displaySpeedWindow.addPoint(point);

    _emitActive(
      RunPhase.tracking,
      speedMps: windowedSpeed,
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

  /// The engine's point-driven metrics with the wall-clock Time stamped in.
  LiveMetrics _currentMetrics() {
    final base = _metricsEngine?.metrics ?? LiveMetrics.zero;
    final clock = _runClock;
    if (clock == null) return base;
    return base.copyWith(
      elapsedWallClock: clock.elapsed(DateTime.now().toUtc()),
    );
  }

  void _emitActive(
    RunPhase phase, {
    required double? speedMps,
    required double? accuracyMeters,
  }) {
    final previousAccuracy = state is LiveRunActive
        ? (state as LiveRunActive).accuracyMeters
        : 0.0;

    final metrics = _currentMetrics();
    state = LiveRunActive(
      phase: phase,
      speedMps: speedMps,
      accuracyMeters: accuracyMeters ?? previousAccuracy,
      metrics: metrics,
      // Fixed for the run's whole duration (see start()); _activityMode is
      // only ever null before a run has started, at which point nothing
      // reaches LiveRunActive.
      activityMode: _activityMode ?? ActivityMode.running,
      distanceUnit: _splitPlan?.base.effectiveDistanceUnit ?? DistanceUnit.km,
      prefersPace: _splitPlan?.targetsAsPace ?? true,
    );

    // Only while genuinely tracking (not paused/acquiring) — matches the
    // fact that _onSample already returns early on pause and _onTick only
    // fires during RunPhase.tracking, but stated explicitly here too since
    // this method is the shared path for both and a future third caller
    // must not accidentally start firing cues during a pause.
    if (phase == RunPhase.tracking) {
      _processAudioCue(metrics);
    }
    _previousMetricsForAudio = metrics;
  }

  /// A beep and/or "Starting activity" TTS the moment Start is tapped (issue
  /// #125 follow-up) — fires immediately, independent of GPS/acquiring
  /// state, so the user can confirm their audio/volume/routing works
  /// *before* relying on it during the run. Split-changed/verdict cues may
  /// not fire for a while (or at all indoors with no GPS — see the real bug
  /// this was added after), so waiting for any of that would defeat the
  /// point. There is no separate master toggle (removed 2026-09-21) — the
  /// beep plays if either beep sub-toggle is on ([SplitAudioSettings.anyBeepEnabled]),
  /// the TTS speaks if either speech sub-toggle is on
  /// ([SplitAudioSettings.anySpeechEnabled]), independently, so the start
  /// cue previews exactly whichever pieces are actually going to fire
  /// during the run. Only for a mode that supports splits (cycling has no
  /// split concept — D3).
  void _playActivityStartedCue() {
    final settings = _audioSettings;
    if (settings == null || !settings.anyEnabled) return;
    if (_activityMode?.supportsSplits != true) return;

    final audio = ref.read(splitAudioServiceProvider);
    if (settings.anyBeepEnabled) unawaited(audio.playActivityStarted());
    if (settings.anySpeechEnabled) unawaited(audio.speak('Starting activity.'));
  }

  /// Detects and plays a split audio cue (issue #125) for this tick, if any
  /// — see domain/tracking/split_audio_cue.dart for the transition logic
  /// this is built on. No-ops entirely for cycling (no split concept there,
  /// same visibility boundary as the split tiles — see
  /// ActivityMode.supportsSplits) or with every audio toggle off.
  void _processAudioCue(LiveMetrics metrics) {
    final settings = _audioSettings;
    if (settings == null || !settings.anyEnabled) return;
    if (_activityMode?.supportsSplits != true) return;

    final cue = detectSplitAudioCue(
      previous: _previousMetricsForAudio,
      current: metrics,
    );
    if (cue == null) return;

    final audio = ref.read(splitAudioServiceProvider);
    switch (cue.kind) {
      case SplitAudioCueKind.splitChanged:
        if (settings.beepOnSplitChange) unawaited(audio.playSplitChanged());
        if (settings.announceSplitStats) {
          final phrase = splitStatsAnnouncement(cue, _announcementUnit);
          if (phrase != null) unawaited(audio.speak(phrase));
        }
      case SplitAudioCueKind.verdict:
        if (settings.beepOnVerdictChange) {
          unawaited(audio.playVerdict(cue.verdict!));
        }
        if (settings.announceVerdictCorrection) {
          final phrase = splitVerdictAnnouncement(cue, _announcementUnit);
          if (phrase != null) unawaited(audio.speak(phrase));
        }
    }
  }

  /// The unit spoken announcements use pace vs speed in — the run's
  /// pace-or-speed preference (same source as the split tiles' target
  /// display), not whatever the live screen's speed/pace toggle happens to
  /// be showing at this instant. That toggle is purely local UI state the
  /// controller doesn't know about (see `_SpeedUnitNotifier` in
  /// live_run_screen.dart) — using it here would make spoken audio follow a
  /// tap on an unrelated tile, which reads as arbitrary rather than a
  /// deliberate setting.
  SpeedUnit get _announcementUnit {
    final distanceUnit = _splitPlan?.base.effectiveDistanceUnit ?? DistanceUnit.km;
    final speedFirst = SpeedUnit.initialFor(distanceUnit);
    return (_splitPlan?.targetsAsPace ?? true) ? speedFirst.toggled : speedFirst;
  }
}
