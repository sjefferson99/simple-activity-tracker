import 'dart:convert';
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import '../../domain/models/run_record.dart';
import '../../domain/models/sync_status.dart';
import 'run_store.dart';

final runStoreProvider = Provider<RunStore>((ref) => FileRunStore());

/// Stores each [RunRecord] as a JSON sidecar next to its GPX file — same
/// directory, same filename stem, `.json` instead of `.gpx` — so the two are
/// trivially paired without a separate index file. Writes use the same
/// write-temp-then-rename pattern as [RunGpxLog] for crash safety.
class FileRunStore implements RunStore {
  /// Overrides the runs directory (tests only) — production code always
  /// uses the real one under the app's documents directory, resolved via
  /// path_provider, which needs a platform channel unavailable in plain
  /// `flutter_test`.
  final String? _runsDirPathOverride;

  FileRunStore({String? runsDirPathOverride}) : _runsDirPathOverride = runsDirPathOverride;

  String _sidecarPathFor(String gpxPath) =>
      '${gpxPath.substring(0, gpxPath.length - '.gpx'.length)}.json';

  Future<Directory> _runsDir() async {
    final path = _runsDirPathOverride ??
        '${(await getApplicationDocumentsDirectory()).path}/runs';
    final dir = Directory(path);
    await dir.create(recursive: true);
    return dir;
  }

  @override
  Future<void> save(RunRecord record) async {
    final file = File(_sidecarPathFor(record.gpxPath));
    final tempFile = File('${file.path}.tmp');
    await tempFile.writeAsString(jsonEncode(record.toJson()), flush: true);
    await tempFile.rename(file.path);
  }

  @override
  Future<List<RunRecord>> listAll() async {
    final dir = await _runsDir();
    if (!await dir.exists()) return [];

    final records = <RunRecord>[];
    await for (final entity in dir.list()) {
      if (entity is! File || !entity.path.endsWith('.json')) continue;
      try {
        final json = jsonDecode(await entity.readAsString()) as Map<String, dynamic>;
        records.add(RunRecord.fromJson(json));
      } on Object {
        // A corrupt or half-written sidecar must not take down the whole
        // queue — skip it rather than throwing, the same tolerance
        // RunGpxLog's atomic rename is designed to make rare in the first
        // place.
        continue;
      }
    }
    records.sort((a, b) => a.summary.startedAt.compareTo(b.summary.startedAt));
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
    final record = await _findByClientRunId(clientRunId);
    if (record == null) return;
    await save(record.copyWith(syncStatus: status));
  }

  @override
  Future<void> updateAnalysisResult(
    String clientRunId,
    Map<String, dynamic> analysisResult,
  ) async {
    final record = await _findByClientRunId(clientRunId);
    if (record == null) return;
    await save(record.copyWith(analysisResult: analysisResult));
  }

  Future<RunRecord?> _findByClientRunId(String clientRunId) async {
    final all = await listAll();
    for (final record in all) {
      if (record.clientRunId == clientRunId) return record;
    }
    return null;
  }
}
