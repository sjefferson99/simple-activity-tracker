import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/models/live_metrics.dart';
import '../../domain/models/track_point.dart';
import '../../domain/tracking/activity_mode.dart';
import '../../domain/tracking/split_plan.dart';
import '../api/api_client.dart';
import '../api/api_exception.dart';
import '../api/dto/live_dto.dart';
import '../auth/auth_service.dart';
import '../auth/auth_state.dart';
import '../version/api_compat.dart';
import 'connectivity.dart';
import 'live_sharing_store.dart';
import 'live_upload_settings.dart';

/// One per app run, like SyncService. Follows the Live upload setting: a
/// change mid-run starts or stops uploading at once.
final liveUploadServiceProvider = Provider<LiveUploadService>((ref) {
  final service = LiveUploadService(
    apiClient: ref.read(apiClientProvider),
    authService: ref.read(authServiceProvider),
    connectivity: ref.read(connectivityMonitorProvider),
    sharingStore: ref.read(liveSharingStoreProvider),
    enabled: ref.read(liveUploadEnabledProvider),
  );
  ref.listen<bool>(liveUploadEnabledProvider, (_, enabled) => service.setEnabled(enabled));
  ref.onDispose(service.dispose);
  return service;
});

/// The live run's latest upload status, for the run screen's badge.
final liveUploadStatusProvider = StreamProvider<LiveUploadStatus>((ref) async* {
  final service = ref.watch(liveUploadServiceProvider);
  yield service.status;
  yield* service.statusChanges;
});

/// How often a running activity is uploaded (issue #130: about once a
/// minute). Pause, resume and stop also send straight away.
const _defaultInterval = Duration(minutes: 1);

/// The server's per-request cap (LIVE_POINTS_MAX_PER_REQUEST).
const _maxPointsPerRequest = 2000;

enum LiveUploadPhase {
  /// No run in progress.
  idle,

  /// The Live upload setting is off.
  off,

  /// Can't upload this run at all: signed out, or the server is older than
  /// live tracking (API level < [ApiLevels.liveTracking]).
  unavailable,

  /// Trying, but the last attempt didn't get through (no signal, server
  /// unreachable). The points are kept and sent once it does.
  waiting,

  /// Everything recorded so far is on the server.
  upToDate,

  /// The run has already been saved as an activity on the server, so the
  /// server takes no more points for it.
  closed,
}

class LiveUploadStatus {
  final LiveUploadPhase phase;
  final DateTime? lastSuccessAt;

  const LiveUploadStatus(this.phase, {this.lastSuccessAt});

  static const idle = LiveUploadStatus(LiveUploadPhase.idle);
}

class _LiveRun {
  final String clientRunId;
  final ActivityMode activityMode;
  final DateTime startedAt;
  final SplitPlan splitPlan;
  final List<LivePointDto> points = [];
  int segment = 0;
  String state = 'active';
  LiveMetrics? metrics;
  double? currentSpeedMps;

  /// Points before this index are on the server.
  int acknowledged = 0;
  bool sessionCreated = false;

  /// The run ended on the phone; the final state still has to reach the
  /// server (retried on the timer until it does).
  bool finished = false;
  bool finishSent = false;

  _LiveRun({
    required this.clientRunId,
    required this.activityMode,
    required this.startedAt,
    required this.splitPlan,
  });
}

/// Uploads the activity being recorded to the server as it happens (issue
/// #130 phase C, docs/LIVE-TRACKING-PLAN.md §2.3/§2.5): a backup in case the
/// phone dies mid-route, and what lets chosen users follow along.
///
/// The local GPX (RunGpxLog) stays the record and the final upload is
/// unchanged; this is a separate, best-effort stream of the same points. It
/// keeps the run's points in memory and the index the server has
/// acknowledged, so nothing is ever split on disk: a retried batch is a
/// no-op server-side, a gap makes the server say where to resend from, and
/// turning Live upload on mid-run simply starts from index 0.
///
/// Only runs against a server at [ApiLevels.liveTracking] or above
/// (docs/VERSIONING.md §3.2); on an older server it does nothing at all.
/// Single-flight like SyncService: a trigger during a pass asks for one more
/// pass rather than overlapping.
class LiveUploadService {
  final ApiClient _apiClient;
  final AuthService _authService;
  final ConnectivityMonitor _connectivity;
  final LiveSharingStore _sharingStore;
  final DateTime Function() _now;
  final Duration? _interval;

  bool _enabled;
  _LiveRun? _run;
  Timer? _timer;
  int? _serverApiLevel;
  Future<void>? _inFlightPass;
  bool _rerunRequested = false;
  LiveUploadStatus _status = LiveUploadStatus.idle;
  final _statusController = StreamController<LiveUploadStatus>.broadcast();

  LiveUploadService({
    required ApiClient apiClient,
    required AuthService authService,
    required ConnectivityMonitor connectivity,
    required LiveSharingStore sharingStore,
    bool enabled = true,
    DateTime Function()? now,
    // Null disables the timer — tests drive passes with [sendNow].
    Duration? interval = _defaultInterval,
  }) : _apiClient = apiClient,
       _authService = authService,
       _connectivity = connectivity,
       _sharingStore = sharingStore,
       _enabled = enabled,
       _now = now ?? DateTime.now,
       _interval = interval;

  LiveUploadStatus get status => _status;
  Stream<LiveUploadStatus> get statusChanges => _statusController.stream;
  bool get enabled => _enabled;

  void dispose() {
    _timer?.cancel();
    _statusController.close();
  }

  void _setStatus(LiveUploadPhase phase) {
    final lastSuccessAt = phase == LiveUploadPhase.upToDate ? _now() : _status.lastSuccessAt;
    _status = LiveUploadStatus(phase, lastSuccessAt: lastSuccessAt);
    if (!_statusController.isClosed) _statusController.add(_status);
  }

  /// The Live upload setting changed. Takes effect immediately, mid-run
  /// included: off stops uploading (the points stay in memory); on uploads
  /// everything recorded so far, then keeps going.
  void setEnabled(bool enabled) {
    if (enabled == _enabled) return;
    _enabled = enabled;
    if (_run == null) return;
    if (!enabled) {
      _timer?.cancel();
      _timer = null;
      _setStatus(LiveUploadPhase.off);
    } else {
      _startTimer();
      unawaited(sendNow());
    }
  }

  void startRun({
    required String clientRunId,
    required ActivityMode activityMode,
    required DateTime startedAt,
    required SplitPlan splitPlan,
  }) {
    _timer?.cancel();
    _timer = null;
    _serverApiLevel = null;
    _run = _LiveRun(
      clientRunId: clientRunId,
      activityMode: activityMode,
      startedAt: startedAt,
      splitPlan: splitPlan,
    );
    if (!_enabled) {
      _setStatus(LiveUploadPhase.off);
      return;
    }
    _setStatus(LiveUploadPhase.waiting);
    _startTimer();
    unawaited(sendNow());
  }

  /// Every fix the GPX gets, the server gets too: the same raw track.
  void addPoint(TrackPoint point) {
    final run = _run;
    if (run == null || run.finished) return;
    run.points.add(LivePointDto(point, run.segment));
  }

  /// The phone's current numbers, sent with the next batch.
  void updateMetrics(LiveMetrics metrics, {double? currentSpeedMps}) {
    final run = _run;
    if (run == null || run.finished) return;
    run.metrics = metrics;
    run.currentSpeedMps = currentSpeedMps;
  }

  void pause() {
    final run = _run;
    if (run == null || run.finished) return;
    run.state = 'paused';
    unawaited(sendNow());
  }

  /// A resume starts a new segment, so the live map doesn't draw a straight
  /// line across the paused gap.
  void resume() {
    final run = _run;
    if (run == null || run.finished) return;
    run.state = 'active';
    run.segment++;
    unawaited(sendNow());
  }

  /// The run was stopped. Sends the rest of the points and the finished
  /// state; if that can't get through now, the timer keeps trying until it
  /// does or the next run starts (the final activity upload also closes the
  /// session server-side, whichever comes first).
  Future<void> finishRun(LiveMetrics metrics) async {
    final run = _run;
    if (run == null) return;
    run.metrics = metrics;
    run.currentSpeedMps = null;
    run.state = 'finished';
    run.finished = true;
    await sendNow();
  }

  /// The run was deleted on the phone before it was ever saved on the
  /// server: remove its live session too. Best effort; the server drops
  /// unsaved sessions after 30 days anyway.
  Future<void> discardRun(String clientRunId) async {
    if (_run?.clientRunId == clientRunId) {
      _timer?.cancel();
      _timer = null;
      _run = null;
      _setStatus(LiveUploadPhase.idle);
    }
    final auth = await _authService.currentState();
    if (!auth.isSignedIn || !auth.hasServerUrl) return;
    try {
      final level = await _apiLevel(auth);
      if (level == null || level < ApiLevels.liveTracking) return;
      await _apiClient.deleteLiveSession(
        baseUrl: auth.serverUrl!,
        token: auth.token!,
        clientActivityId: clientRunId,
      );
    } on ApiException {
      // Best effort — see doc comment.
    }
  }

  void _startTimer() {
    final interval = _interval;
    if (interval == null || _timer != null) return;
    _timer = Timer.periodic(interval, (_) => unawaited(sendNow()));
  }

  void _stopAfterFinish() {
    _timer?.cancel();
    _timer = null;
  }

  /// Runs one upload pass now (single-flight).
  Future<void> sendNow() {
    if (_inFlightPass != null) {
      _rerunRequested = true;
      return _inFlightPass!;
    }
    final pass = _pass();
    _inFlightPass = pass;
    pass.whenComplete(() {
      _inFlightPass = null;
      if (_rerunRequested) {
        _rerunRequested = false;
        unawaited(sendNow());
      }
    });
    return pass;
  }

  Future<void> _pass() async {
    final run = _run;
    if (run == null || !_enabled) return;
    if (_status.phase == LiveUploadPhase.closed) return;
    final auth = await _authService.currentState();
    if (!auth.isSignedIn || !auth.hasServerUrl) {
      _setStatus(LiveUploadPhase.unavailable);
      return;
    }
    if (!await _connectivity.isConnected) {
      _setStatus(LiveUploadPhase.waiting);
      return;
    }

    try {
      final level = await _apiLevel(auth);
      if (level == null) {
        _setStatus(LiveUploadPhase.waiting);
        return;
      }
      if (level < ApiLevels.liveTracking) {
        _setStatus(LiveUploadPhase.unavailable);
        _stopAfterFinish();
        return;
      }

      // A sharing change made offline goes first, so "Don't live share"
      // tapped with no signal applies before the next point does.
      try {
        await _sharingStore.flush(_apiClient, auth);
      } on ApiRejectedException {
        // Dropped by the store (can never succeed as-is); not a reason to
        // hold back the run itself.
      }

      if (!_enabled || !identical(_run, run)) return;
      if (!run.sessionCreated) {
        final created = await _apiClient.putLiveSession(
          baseUrl: auth.serverUrl!,
          token: auth.token!,
          clientActivityId: run.clientRunId,
          request: LiveSessionRequestDto(
            activityMode: run.activityMode,
            startedAt: run.startedAt,
            splitPlan: run.splitPlan,
          ),
        );
        run.sessionCreated = true;
        run.acknowledged = created.nextIndex.clamp(0, run.points.length);
      }

      await _sendPoints(run, auth);
      if (identical(_run, run) && _enabled) {
        _setStatus(LiveUploadPhase.upToDate);
        if (run.finished && run.finishSent) _stopAfterFinish();
      }
    } on ApiRejectedException catch (e) {
      if (e.statusCode == 410) {
        // Already saved as an activity: stop uploading this run.
        _stopAfterFinish();
        _setStatus(LiveUploadPhase.closed);
      } else if (e.statusCode == 404) {
        // The server has no such session (deleted from the web, or purged):
        // create it again on the next pass, from wherever it says.
        run.sessionCreated = false;
        _setStatus(LiveUploadPhase.waiting);
      } else {
        _setStatus(LiveUploadPhase.waiting);
      }
    } on ApiUnauthorizedException {
      // SyncService owns signing the user out; just stop trying.
      _setStatus(LiveUploadPhase.unavailable);
    } on ApiException {
      _setStatus(LiveUploadPhase.waiting);
    }
  }

  /// Sends everything from the acknowledged index, in batches, then the
  /// latest metrics/state even when no new point arrived (a pause, a stop).
  Future<void> _sendPoints(_LiveRun run, AuthState auth) async {
    var sentStateOnly = false;
    while (true) {
      // Live upload switched off (or a new run started) while this pass was
      // in flight: stop before the next request, not after the whole pass.
      if (!_enabled || !identical(_run, run)) return;
      final from = run.acknowledged;
      final end = (from + _maxPointsPerRequest).clamp(from, run.points.length);
      final batch = run.points.sublist(from, end);
      if (batch.isEmpty && sentStateOnly) return;
      // Captured before the call: a stop that lands while this batch is in
      // flight must still be sent on the next pass.
      final finishing = run.finished;
      final result = await _apiClient.postLivePoints(
        baseUrl: auth.serverUrl!,
        token: auth.token!,
        clientActivityId: run.clientRunId,
        request: LivePointsRequestDto(
          fromIndex: from,
          points: batch,
          state: run.state,
          metrics: run.metrics,
          currentSpeedMps: run.currentSpeedMps,
        ),
      );
      run.acknowledged = result.nextIndex.clamp(0, run.points.length);
      if (finishing && run.acknowledged >= run.points.length) run.finishSent = true;
      if (batch.isEmpty) return;
      sentStateOnly = run.acknowledged >= run.points.length;
      // The server didn't move forward (shouldn't happen): try again on the
      // next pass rather than looping.
      if (run.acknowledged <= from && result.nextIndex >= from) return;
    }
  }

  /// The server's API level, fetched once per run. Null if it couldn't be
  /// fetched right now (the pass waits and tries again).
  Future<int?> _apiLevel(AuthState auth) async {
    final cached = _serverApiLevel;
    if (cached != null) return cached;
    try {
      final info = await _apiClient.getServerInfo(baseUrl: auth.serverUrl!, token: auth.token!);
      return _serverApiLevel = info.apiLevel;
    } on ApiUnauthorizedException {
      rethrow;
    } on ApiException {
      return null;
    }
  }
}
