import 'package:flutter_test/flutter_test.dart';
import 'package:simple_runner/domain/models/run_record.dart';
import 'package:simple_runner/domain/models/run_summary.dart';
import 'package:simple_runner/domain/models/sync_status.dart';

RunSummary _summary() => RunSummary(
      clientRunId: '11111111-1111-1111-1111-111111111111',
      startedAt: DateTime.utc(2026, 1, 1, 7, 0, 0),
      endedAt: DateTime.utc(2026, 1, 1, 7, 16, 30),
      movingSeconds: 900,
      distanceMeters: 3000,
      avgSpeedMps: 3.33,
      splits: const [],
      sourcePlatform: 'android',
      sourceAppVersion: '1.0.0+1',
    );

void main() {
  test('round-trips through JSON, including a null analysisResult', () {
    final record = RunRecord(
      clientRunId: '11111111-1111-1111-1111-111111111111',
      gpxPath: '/documents/runs/run_2026-01-01_070000.gpx',
      summary: _summary(),
      syncStatus: const SyncStatusPending(),
    );

    final result = RunRecord.fromJson(record.toJson());

    expect(result.clientRunId, record.clientRunId);
    expect(result.gpxPath, record.gpxPath);
    expect(result.summary.toJson(), record.summary.toJson());
    expect(result.syncStatus, isA<SyncStatusPending>());
    expect(result.analysisResult, isNull);
  });

  test('round-trips a cached analysisResult', () {
    final record = RunRecord(
      clientRunId: 'abc',
      gpxPath: '/documents/runs/run.gpx',
      summary: _summary(),
      syncStatus: const SyncStatusUploaded(serverRunId: 'server-1'),
      analysisResult: const {'distance_meters': 3017.6, 'splits': []},
    );

    final result = RunRecord.fromJson(record.toJson());

    expect(result.analysisResult, record.analysisResult);
    expect((result.syncStatus as SyncStatusUploaded).serverRunId, 'server-1');
  });

  test('copyWith replaces only the given fields', () {
    final record = RunRecord(
      clientRunId: 'abc',
      gpxPath: '/documents/runs/run.gpx',
      summary: _summary(),
      syncStatus: const SyncStatusPending(),
    );

    final updated = record.copyWith(
      syncStatus: const SyncStatusUploaded(serverRunId: 'server-2'),
    );

    expect(updated.clientRunId, record.clientRunId);
    expect(updated.gpxPath, record.gpxPath);
    expect((updated.syncStatus as SyncStatusUploaded).serverRunId, 'server-2');
    expect(updated.analysisResult, isNull);
  });
}
