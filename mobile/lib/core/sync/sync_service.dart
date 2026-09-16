import 'dart:async';
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/models/run_record.dart';
import '../../domain/models/sync_status.dart';
import '../api/api_client.dart';
import '../api/api_exception.dart';
import '../auth/auth_service.dart';
import 'connectivity.dart';
import 'file_run_store.dart';
import 'run_store.dart';

/// One SyncService per app run — constructed lazily on first read (e.g. by
/// LiveRunController at startup) and disposed with the provider.
final syncServiceProvider = Provider<SyncService>((ref) {
  final service = SyncService(
    apiClient: ref.read(apiClientProvider),
    runStore: ref.read(runStoreProvider),
    authService: ref.read(authServiceProvider),
    connectivity: ref.read(connectivityMonitorProvider),
  );
  ref.onDispose(service.dispose);
  return service;
});

/// In-session backoff between automatic retry attempts for one record —
/// docs/WEB-PLAN.md §6.3. Capped at the last entry; attempts beyond the
/// list length reuse it rather than growing further.
const _backoffSchedule = [
  Duration(seconds: 30),
  Duration(minutes: 1),
  Duration(minutes: 2),
  Duration(minutes: 5),
  Duration(minutes: 10),
];

/// How often a periodic pass re-checks the queue, independent of any
/// connectivity-change event. `ConnectivityMonitor.onConnected` only fires
/// on a none→some transition — switching between two networks that both
/// report "connected" the whole time (e.g. Wi-Fi to Wi-Fi, or a network the
/// phone hands off seamlessly) never fires it at all, so a failed upload
/// could otherwise sit stuck until some unrelated trigger (app resume, a new
/// run finishing) happened to come along. Found via real on-device testing:
/// switching networks produced no retry until this periodic tick was added.
const _periodicRetryInterval = Duration(minutes: 1);

/// Bounded retry for a still-`pending` analysis fetch right after upload
/// (issue #97/#101, Slice C) — short-lived (well under a minute total), so
/// the post-Stop summary screen's "View full summary" link has a real
/// chance to become available before the user has moved on, without
/// retrying indefinitely. Distinct from [_backoffSchedule], which is for
/// upload retries, not analysis polling.
const _analysisRetryDelays = [
  Duration(seconds: 2),
  Duration(seconds: 5),
  Duration(seconds: 10),
  Duration(seconds: 15),
];

/// Single-flight worker over the run queue: uploads pending/retryable
/// [RunRecord]s oldest-first, one at a time, then fetches analysis for
/// whatever just landed. Triggered by [runFinished], [onAppResumed],
/// connectivity regained, a periodic timer (see [_periodicRetryInterval]),
/// and [retryNow] — never runs two passes concurrently (a trigger arriving
/// mid-pass just requests one more pass after the current one finishes,
/// rather than overlapping).
class SyncService {
  final ApiClient _apiClient;
  final RunStore _runStore;
  final AuthService _authService;
  final ConnectivityMonitor _connectivity;
  final DateTime Function() _now;

  /// Overridable in tests so the analysis retry loop doesn't actually wait —
  /// production always uses a real [Future.delayed].
  final Future<void> Function(Duration) _delay;

  StreamSubscription<void>? _connectivitySubscription;
  Timer? _periodicRetryTimer;
  Future<void>? _inFlightPass;
  bool _rerunRequested = false;

  /// Attempt count and last-attempt time per record, kept in memory only —
  /// a persisted `attempts` on [SyncStatusFailed] survives app restarts
  /// (capping the schedule index), but re-litigating exactly *when* the
  /// last attempt happened after a restart isn't worth persisting: it's
  /// safe (if slightly eager) to just retry immediately in that case.
  final Map<String, int> _attemptCounts = {};
  final Map<String, DateTime> _lastAttemptTimes = {};

  final _statusController = StreamController<(String, SyncStatus)>.broadcast();

  /// Emits `(clientRunId, newStatus)` whenever a record's status changes —
  /// the UI (summary screen, a future run-list sync badge) subscribes to
  /// this rather than polling RunStore.
  Stream<(String, SyncStatus)> get statusChanges => _statusController.stream;

  SyncService({
    required ApiClient apiClient,
    required RunStore runStore,
    required AuthService authService,
    required ConnectivityMonitor connectivity,
    DateTime Function()? now,
    Future<void> Function(Duration)? delay,
    // Null disables the periodic timer entirely — used by tests, which
    // don't want a real-time repeating timer running in the background
    // (and would otherwise need to explicitly cancel one on every test to
    // avoid a "Timer still pending" failure). Production always passes the
    // real interval via the default.
    Duration? periodicRetryInterval = _periodicRetryInterval,
  })  : _apiClient = apiClient,
        _runStore = runStore,
        _authService = authService,
        _connectivity = connectivity,
        _now = now ?? DateTime.now,
        _delay = delay ?? ((duration) => Future<void>.delayed(duration)) {
    _connectivitySubscription = _connectivity.onConnected.listen((_) => _runPass());
    if (periodicRetryInterval != null) {
      _periodicRetryTimer = Timer.periodic(periodicRetryInterval, (_) => _runPass());
    }
  }

  void dispose() {
    _connectivitySubscription?.cancel();
    _periodicRetryTimer?.cancel();
    _statusController.close();
  }

  /// Call right after a run's [RunRecord] sidecar is written (before the
  /// controller's state switches to Finished — see LiveRunController).
  void runFinished() => _runPass();

  void onAppResumed() => _runPass();

  /// User tapped "Retry now" in Settings: unlike the automatic triggers,
  /// this resets *every* failed record — including one marked
  /// non-retryable (e.g. a rejected file) — back to pending and attempts
  /// it again. It's an explicit user action, so it's allowed to try things
  /// the automatic backoff wouldn't (the user may have fixed whatever was
  /// wrong, or an admin re-enabled their account). Returns once the
  /// resulting pass finishes, so the UI can show a brief loading state.
  Future<void> retryNow() async {
    for (final record in await _runStore.listAll()) {
      if (record.syncStatus is SyncStatusFailed) {
        await _setStatus(record.clientRunId, const SyncStatusPending());
      }
    }
    await _runPass();
  }

  Future<void> _setStatus(String clientRunId, SyncStatus status) async {
    await _runStore.updateSyncStatus(clientRunId, status);
    _statusController.add((clientRunId, status));
  }

  /// Re-broadcasts [clientRunId]'s current sync status on [statusChanges] —
  /// used when a record's analysis result/failure changes without its sync
  /// status itself changing (it's already `uploaded`), so `_runRecordProvider`
  /// (run_insights.dart) actually re-fetches and the summary screen's link
  /// updates. Without this, `updateAnalysisResult`/`markAnalysisFailed` wrote
  /// to disk correctly but nothing ever told the UI to re-read it, so the
  /// "View full summary" link never appeared until the app was relaunched —
  /// a real bug found via on-device testing before this was ever pushed.
  Future<void> _notifyRecordChanged(String clientRunId) async {
    final records = await _runStore.listAll();
    for (final record in records) {
      if (record.clientRunId == clientRunId) {
        _statusController.add((clientRunId, record.syncStatus));
        return;
      }
    }
  }

  /// Runs one pass over the queue. If a pass is already running, this
  /// request is remembered and a fresh pass starts as soon as the current
  /// one finishes — so a burst of triggers (connectivity flapping, resume
  /// right after a run finishes) never overlaps two uploads of the same
  /// record.
  Future<void> _runPass() {
    if (_inFlightPass != null) {
      _rerunRequested = true;
      return _inFlightPass!;
    }
    final pass = _drainQueue();
    _inFlightPass = pass;
    pass.whenComplete(() {
      _inFlightPass = null;
      if (_rerunRequested) {
        _rerunRequested = false;
        _runPass();
      }
    });
    return pass;
  }

  Future<void> _drainQueue() async {
    final queue = await _runStore.listPendingOrRetryable();
    for (final record in queue) {
      if (!await _connectivity.isConnected) return;

      final due = _dueAt(record);
      if (due != null && _now().isBefore(due)) {
        // Not a `return`: oldest-first is about upload order, not
        // eligibility — a not-yet-due retryable record must not block a
        // later one (e.g. freshly pending) that's ready now.
        continue;
      }

      if (!await _attemptUpload(record)) return;
      // A successful upload always continues to the next record. A failed
      // one also continues rather than stopping the pass — the record just
      // moved to `failed` (retryable or not) and simply won't be picked up
      // again until its backoff/never, so nothing is gained by giving up on
      // the rest of the queue too. One broken record (e.g. a GPX with no GPS
      // points at all) must not block every other queued activity behind it.
    }
  }

  DateTime? _dueAt(RunRecord record) {
    final status = record.syncStatus;
    if (status is! SyncStatusFailed) return null;
    final lastAttemptAt = _lastAttemptTimes[record.clientRunId];
    if (lastAttemptAt == null) return null;
    final index = (status.attempts - 1).clamp(0, _backoffSchedule.length - 1);
    return lastAttemptAt.add(_backoffSchedule[index]);
  }

  /// Returns false only when the pass as a whole should stop (not signed in
  /// / no server configured — every other queued record would fail the same
  /// way right now, so there's no point trying them). Returns true for every
  /// other outcome, including a recorded failure: a broken record (retryable
  /// or not) is done with for this pass either way, and must not block the
  /// rest of the queue from being attempted.
  Future<bool> _attemptUpload(RunRecord record) async {
    await _setStatus(record.clientRunId, const SyncStatusUploading());
    _lastAttemptTimes[record.clientRunId] = _now();

    final auth = await _authService.currentState();
    if (!auth.isSignedIn || !auth.hasServerUrl) {
      // Leave the record pending (not failed) — retrying immediately would
      // just fail the same way for every other queued record too.
      await _setStatus(record.clientRunId, const SyncStatusPending());
      return false;
    }

    try {
      final runDto = await _apiClient.uploadRun(
        baseUrl: auth.serverUrl!,
        token: auth.token!,
        summary: record.summary,
        gpxFile: File(record.gpxPath),
      );
      await _setStatus(record.clientRunId, SyncStatusUploaded(serverRunId: runDto.id));
      _attemptCounts.remove(record.clientRunId);
      _lastAttemptTimes.remove(record.clientRunId);

      unawaited(_fetchAnalysis(record.clientRunId, auth.serverUrl!, auth.token!, runDto.id));
      return true;
    } on ApiUnauthorizedException {
      await _authService.markSignedOutDueToAuthFailure();
      await _setStatus(record.clientRunId, const SyncStatusPending());
      // Every other queued record would also fail with the same 401 right
      // now, so stop the pass rather than churning through the rest of the
      // queue for nothing.
      return false;
    } on ApiRejectedException catch (e) {
      final attempts = _bumpAttempts(record.clientRunId);
      await _setStatus(
        record.clientRunId,
        SyncStatusFailed(error: e.message, attempts: attempts, retryable: false),
      );
      return true;
    } on ApiException catch (e) {
      // network / timeout / 5xx / 429 — retryable.
      final attempts = _bumpAttempts(record.clientRunId);
      await _setStatus(
        record.clientRunId,
        SyncStatusFailed(error: e.message, attempts: attempts, retryable: true),
      );
      return true;
    }
  }

  int _bumpAttempts(String clientRunId) {
    final attempts = (_attemptCounts[clientRunId] ?? 0) + 1;
    _attemptCounts[clientRunId] = attempts;
    return attempts;
  }

  /// Fetches analysis right after a successful upload, retrying a short,
  /// bounded number of times (issue #97/#101, Slice C) while it's still
  /// `pending` — a slow server would otherwise leave the summary screen's
  /// "View full summary" link stuck on "not available" past the single
  /// attempt this used to make. Gives up (marking [RunStore.markAnalysisFailed])
  /// only once every attempt is exhausted with no result — the upload itself
  /// already succeeded either way and is never at risk here.
  Future<void> _fetchAnalysis(
    String clientRunId,
    String baseUrl,
    String token,
    String serverRunId,
  ) async {
    for (var attempt = 0; attempt <= _analysisRetryDelays.length; attempt++) {
      try {
        final analysis = await _apiClient.getAnalysis(
          baseUrl: baseUrl,
          token: token,
          serverRunId: serverRunId,
        );
        if (analysis.isDone && analysis.result != null) {
          await _runStore.updateAnalysisResult(clientRunId, analysis.result!);
          await _notifyRecordChanged(clientRunId);
          return;
        }
        if (analysis.isFailed) {
          await _runStore.markAnalysisFailed(clientRunId);
          await _notifyRecordChanged(clientRunId);
          return;
        }
        // Still pending — wait and try again, unless this was the last attempt.
      } on ApiException {
        // Best-effort — the upload itself already succeeded and is not at
        // risk. Keep retrying on the same schedule rather than giving up on
        // the first transient network hiccup.
      }
      if (attempt < _analysisRetryDelays.length) {
        await _delay(_analysisRetryDelays[attempt]);
      }
    }
    // Exhausted every retry with no done/failed result — treat as failed so
    // the UI can stop showing "not available yet" forever.
    await _runStore.markAnalysisFailed(clientRunId);
    await _notifyRecordChanged(clientRunId);
  }
}
