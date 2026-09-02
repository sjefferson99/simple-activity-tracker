import 'package:simple_runner/core/sync/run_store.dart';
import 'package:simple_runner/domain/models/run_record.dart';
import 'package:simple_runner/domain/models/sync_status.dart';

/// In-memory [RunStore] for tests — avoids real file I/O so SyncService
/// tests can run fast and control exactly what's in the queue.
class FakeRunStore implements RunStore {
  final Map<String, RunRecord> _records = {};

  void seed(RunRecord record) => _records[record.clientRunId] = record;

  @override
  Future<void> save(RunRecord record) async {
    _records[record.clientRunId] = record;
  }

  @override
  Future<List<RunRecord>> listAll() async {
    final records = _records.values.toList()
      ..sort((a, b) => a.summary.startedAt.compareTo(b.summary.startedAt));
    return records;
  }

  @override
  Future<List<RunRecord>> listPendingOrRetryable() async {
    final all = await listAll();
    return all.where((record) {
      final status = record.syncStatus;
      return status is SyncStatusPending ||
          (status is SyncStatusFailed && status.retryable);
    }).toList();
  }

  @override
  Future<void> updateSyncStatus(String clientRunId, SyncStatus status) async {
    final record = _records[clientRunId];
    if (record == null) return;
    _records[clientRunId] = record.copyWith(syncStatus: status);
  }

  @override
  Future<void> updateAnalysisResult(
    String clientRunId,
    Map<String, dynamic> analysisResult,
  ) async {
    final record = _records[clientRunId];
    if (record == null) return;
    _records[clientRunId] = record.copyWith(analysisResult: analysisResult);
  }
}
