import '../../domain/models/run_record.dart';
import '../../domain/models/sync_status.dart';

/// Persists [RunRecord]s across app restarts. Implemented as a JSON sidecar
/// per run next to its GPX file (see [FileRunStore]) — deliberately not a
/// database, matching the app's existing crash-safe write-temp-then-rename
/// pattern rather than adding a new dependency (docs/WEB-PLAN.md §1).
abstract class RunStore {
  Future<void> save(RunRecord record);

  Future<List<RunRecord>> listAll();

  /// Convenience for SyncService: records whose upload isn't finished —
  /// `pending`, or `failed` with `retryable: true`. Ordered oldest-first by
  /// `summary.startedAt` (a directory listing has no reliable order of its
  /// own), so a queue of several runs uploads in the order they happened.
  Future<List<RunRecord>> listPendingOrRetryable();

  Future<void> updateSyncStatus(String clientRunId, SyncStatus status);

  Future<void> updateAnalysisResult(String clientRunId, Map<String, dynamic> analysisResult);

  /// Deletes every record currently in [SyncStatusFailed], regardless of
  /// [SyncStatusFailed.retryable] — an explicit "give up on these" action
  /// for a record that can never succeed (e.g. no GPS data at all), so it
  /// stops cluttering the queue without requiring a full app reinstall.
  /// Records still pending/uploading/uploaded are untouched. Returns the
  /// number of records removed.
  Future<int> clearFailed();
}
