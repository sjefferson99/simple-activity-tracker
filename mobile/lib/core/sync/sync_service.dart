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

/// Single-flight worker over the run queue: uploads pending/retryable
/// [RunRecord]s oldest-first, one at a time, then fetches analysis for
/// whatever just landed. Triggered by [runFinished], [onAppResumed],
/// connectivity regained, and [retryNow] — never runs two passes
/// concurrently (a trigger arriving mid-pass just requests one more pass
/// after the current one finishes, rather than overlapping).
class SyncService {
  final ApiClient _apiClient;
  final RunStore _runStore;
  final AuthService _authService;
  final ConnectivityMonitor _connectivity;
  final DateTime Function() _now;

  StreamSubscription<void>? _connectivitySubscription;
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
  })  : _apiClient = apiClient,
        _runStore = runStore,
        _authService = authService,
        _connectivity = connectivity,
        _now = now ?? DateTime.now {
    _connectivitySubscription = _connectivity.onConnected.listen((_) => _runPass());
  }

  void dispose() {
    _connectivitySubscription?.cancel();
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
    while (true) {
      final queue = await _runStore.listPendingOrRetryable();
      if (queue.isEmpty) return;
      if (!await _connectivity.isConnected) return;

      final record = queue.first;
      final due = _dueAt(record);
      if (due != null && _now().isBefore(due)) {
        // Oldest-first also means nothing later in the queue is any more
        // due than this one — no point scanning further this pass.
        return;
      }

      final succeeded = await _attemptUpload(record);
      if (!succeeded) return; // stop the pass on the first non-terminal outcome
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

  /// Returns true if the record reached a terminal state this attempt
  /// (uploaded) — false covers every other outcome (still-retryable
  /// failure, permanent rejection, or not signed in), each of which stops
  /// the pass rather than moving on to the next queued record.
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
      return false;
    } on ApiRejectedException catch (e) {
      final attempts = _bumpAttempts(record.clientRunId);
      await _setStatus(
        record.clientRunId,
        SyncStatusFailed(error: e.message, attempts: attempts, retryable: false),
      );
      return false;
    } on ApiException catch (e) {
      // network / timeout / 5xx / 429 — retryable.
      final attempts = _bumpAttempts(record.clientRunId);
      await _setStatus(
        record.clientRunId,
        SyncStatusFailed(error: e.message, attempts: attempts, retryable: true),
      );
      return false;
    }
  }

  int _bumpAttempts(String clientRunId) {
    final attempts = (_attemptCounts[clientRunId] ?? 0) + 1;
    _attemptCounts[clientRunId] = attempts;
    return attempts;
  }

  Future<void> _fetchAnalysis(
    String clientRunId,
    String baseUrl,
    String token,
    String serverRunId,
  ) async {
    try {
      final analysis = await _apiClient.getAnalysis(
        baseUrl: baseUrl,
        token: token,
        serverRunId: serverRunId,
      );
      if (analysis.isDone && analysis.result != null) {
        await _runStore.updateAnalysisResult(clientRunId, analysis.result!);
      }
      // pending: shown as "Analysis pending" in the UI, not retried — §6.3.
    } on ApiException {
      // Best-effort — the upload itself already succeeded and is not at risk.
    }
  }
}
