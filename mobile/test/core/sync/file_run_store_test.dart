import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/sync/file_run_store.dart';
import 'package:simple_activity_tracker/domain/models/run_record.dart';
import 'package:simple_activity_tracker/domain/models/run_summary.dart';
import 'package:simple_activity_tracker/domain/models/sync_status.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';

RunRecord _record(
  String gpxPath, {
  DateTime? startedAt,
  SyncStatus? syncStatus,
}) {
  final started = startedAt ?? DateTime.utc(2026, 1, 1, 7, 0, 0);
  return RunRecord(
    clientRunId: 'run-${gpxPath.hashCode}',
    gpxPath: gpxPath,
    activityMode: ActivityMode.running,
    summary: RunSummary(
      clientRunId: 'run-${gpxPath.hashCode}',
      startedAt: started,
      endedAt: started.add(const Duration(minutes: 30)),
      activityMode: ActivityMode.running,
      movingSeconds: 1800,
      distanceMeters: 5000,
      avgSpeedMps: 2.78,
      splits: const [],
      sourcePlatform: 'android',
      sourceAppVersion: '1.0.0+1',
    ),
    syncStatus: syncStatus ?? const SyncStatusPending(),
  );
}

void main() {
  late Directory tempDir;

  setUp(() async {
    tempDir = await Directory.systemTemp.createTemp('file_run_store_test');
  });

  tearDown(() async {
    if (await tempDir.exists()) await tempDir.delete(recursive: true);
  });

  test('save then listAll round-trips a record', () async {
    final store = FileRunStore(runsDirPathOverride: tempDir.path);
    final record = _record('${tempDir.path}/run_a.gpx');

    await store.save(record);
    final all = await store.listAll();

    expect(all, hasLength(1));
    expect(all.single.clientRunId, record.clientRunId);
    expect(all.single.summary.distanceMeters, 5000);
  });

  test(
    'the sidecar sits next to the gpx file with a .json extension',
    () async {
      final store = FileRunStore(runsDirPathOverride: tempDir.path);
      final record = _record('${tempDir.path}/run_2026-01-01_070000.gpx');

      await store.save(record);

      expect(
        await File('${tempDir.path}/run_2026-01-01_070000.json').exists(),
        isTrue,
      );
    },
  );

  test(
    'listAll orders oldest-first by startedAt regardless of write order',
    () async {
      final store = FileRunStore(runsDirPathOverride: tempDir.path);
      await store.save(
        _record(
          '${tempDir.path}/later.gpx',
          startedAt: DateTime.utc(2026, 1, 2),
        ),
      );
      await store.save(
        _record(
          '${tempDir.path}/earlier.gpx',
          startedAt: DateTime.utc(2026, 1, 1),
        ),
      );

      final all = await store.listAll();

      expect(all.map((r) => r.gpxPath).toList(), [
        '${tempDir.path}/earlier.gpx',
        '${tempDir.path}/later.gpx',
      ]);
    },
  );

  test(
    'listPendingOrRetryable excludes uploaded and non-retryable-failed records',
    () async {
      final store = FileRunStore(runsDirPathOverride: tempDir.path);
      await store.save(_record('${tempDir.path}/pending.gpx'));
      await store.save(
        _record(
          '${tempDir.path}/uploaded.gpx',
          syncStatus: const SyncStatusUploaded(serverRunId: 's1'),
        ),
      );
      await store.save(
        _record(
          '${tempDir.path}/failed_permanent.gpx',
          syncStatus: const SyncStatusFailed(
            error: 'bad file',
            attempts: 1,
            retryable: false,
          ),
        ),
      );
      await store.save(
        _record(
          '${tempDir.path}/failed_retryable.gpx',
          syncStatus: const SyncStatusFailed(
            error: 'offline',
            attempts: 2,
            retryable: true,
          ),
        ),
      );

      final queue = await store.listPendingOrRetryable();

      expect(queue.map((r) => r.gpxPath.split('/').last).toSet(), {
        'pending.gpx',
        'failed_retryable.gpx',
      });
    },
  );

  test(
    'updateSyncStatus persists the new status for the matching record',
    () async {
      final store = FileRunStore(runsDirPathOverride: tempDir.path);
      final record = _record('${tempDir.path}/run_a.gpx');
      await store.save(record);

      await store.updateSyncStatus(
        record.clientRunId,
        const SyncStatusUploaded(serverRunId: 's1'),
      );

      final all = await store.listAll();
      expect((all.single.syncStatus as SyncStatusUploaded).serverRunId, 's1');
    },
  );

  test(
    'updateAnalysisResult persists the result for the matching record',
    () async {
      final store = FileRunStore(runsDirPathOverride: tempDir.path);
      final record = _record('${tempDir.path}/run_a.gpx');
      await store.save(record);

      await store.updateAnalysisResult(record.clientRunId, {
        'distance_meters': 5012.3,
      });

      final all = await store.listAll();
      expect(all.single.analysisResult?['distance_meters'], 5012.3);
    },
  );

  test('listAll skips a corrupt sidecar rather than throwing', () async {
    final store = FileRunStore(runsDirPathOverride: tempDir.path);
    await store.save(_record('${tempDir.path}/good.gpx'));
    await File('${tempDir.path}/corrupt.json').writeAsString('{not valid json');

    final all = await store.listAll();

    expect(all, hasLength(1));
    expect(all.single.gpxPath, '${tempDir.path}/good.gpx');
  });

  test(
    'clearFailed deletes only failed records, sidecar and gpx included',
    () async {
      final store = FileRunStore(runsDirPathOverride: tempDir.path);
      await store.save(_record('${tempDir.path}/pending.gpx'));
      await store.save(
        _record(
          '${tempDir.path}/failed_permanent.gpx',
          syncStatus: const SyncStatusFailed(
            error: 'no GPS data',
            attempts: 1,
            retryable: false,
          ),
        ),
      );
      await store.save(
        _record(
          '${tempDir.path}/failed_retryable.gpx',
          syncStatus: const SyncStatusFailed(
            error: 'offline',
            attempts: 2,
            retryable: true,
          ),
        ),
      );
      // The GPX files themselves aren't written by save() (that's
      // RunGpxLog's job) — create stand-ins so clearFailed's file deletion
      // is actually exercised.
      for (final name in ['pending', 'failed_permanent', 'failed_retryable']) {
        await File('${tempDir.path}/$name.gpx').writeAsString('<gpx/>');
      }

      final cleared = await store.clearFailed();

      expect(cleared, 2);
      final remaining = await store.listAll();
      expect(remaining.map((r) => r.gpxPath.split('/').last).toSet(), {
        'pending.gpx',
      });
      expect(await File('${tempDir.path}/pending.gpx').exists(), isTrue);
      expect(await File('${tempDir.path}/pending.json').exists(), isTrue);
      expect(
        await File('${tempDir.path}/failed_permanent.gpx').exists(),
        isFalse,
      );
      expect(
        await File('${tempDir.path}/failed_permanent.json').exists(),
        isFalse,
      );
      expect(
        await File('${tempDir.path}/failed_retryable.gpx').exists(),
        isFalse,
      );
      expect(
        await File('${tempDir.path}/failed_retryable.json').exists(),
        isFalse,
      );
    },
  );

  test('clearFailed is a no-op when nothing has failed', () async {
    final store = FileRunStore(runsDirPathOverride: tempDir.path);
    await store.save(_record('${tempDir.path}/pending.gpx'));

    expect(await store.clearFailed(), 0);
    expect(await store.listAll(), hasLength(1));
  });

  test('listAll returns an empty list for a fresh runs directory', () async {
    // _runsDir() creates the directory on demand, so this also covers the
    // "didn't exist yet" case â€” it exists but is empty by the time listAll
    // reads it.
    final store = FileRunStore(
      runsDirPathOverride: '${tempDir.path}/does_not_exist',
    );

    expect(await store.listAll(), isEmpty);
  });
}
