import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/units/units.dart';
import 'package:simple_activity_tracker/domain/models/run_record.dart';
import 'package:simple_activity_tracker/domain/models/run_record_summary.dart';
import 'package:simple_activity_tracker/domain/models/run_summary.dart';
import 'package:simple_activity_tracker/domain/models/sync_status.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';

RunRecord _recordWith({
  List<RunSummarySplit> splits = const [],
  double? maxSpeedMps,
  double elevationGainMeters = 0,
}) => RunRecord(
  clientRunId: '11111111-1111-1111-1111-111111111111',
  gpxPath: '/documents/runs/run.gpx',
  activityMode: ActivityMode.running,
  summary: RunSummary(
    clientRunId: '11111111-1111-1111-1111-111111111111',
    startedAt: DateTime.utc(2026, 1, 1, 7, 0, 0),
    endedAt: DateTime.utc(2026, 1, 1, 7, 16, 30),
    activityMode: ActivityMode.running,
    movingSeconds: 900,
    distanceMeters: 3000,
    avgSpeedMps: 3.33,
    maxSpeedMps: maxSpeedMps,
    elevationGainMeters: elevationGainMeters,
    splits: splits,
    sourcePlatform: 'android',
    sourceAppVersion: '1.0.0+1',
  ),
  syncStatus: const SyncStatusPending(),
);

void main() {
  test('maps completed splits including their targets', () {
    final record = _recordWith(
      splits: const [
        RunSummarySplit(
          index: 1,
          durationSeconds: 300,
          avgSpeedMps: 3.33,
          distanceMeters: 1000,
          targetSpeedMps: 3.5,
        ),
        RunSummarySplit(
          index: 2,
          durationSeconds: 310,
          avgSpeedMps: 3.2,
          distanceMeters: 1000,
        ),
      ],
    );

    final reopened = reopenedRunSummaryFrom(record);

    expect(reopened.metrics.completedSplits, hasLength(2));
    expect(reopened.metrics.completedSplits[0].targetSpeedMps, 3.5);
    expect(reopened.metrics.completedSplits[1].targetSpeedMps, isNull);
    expect(
      reopened.metrics.completedSplits[0].duration,
      const Duration(seconds: 300),
    );
  });

  test('carries maxSpeedMps and elevationGainMeters straight through', () {
    final record = _recordWith(maxSpeedMps: 5.5, elevationGainMeters: 42.0);

    final reopened = reopenedRunSummaryFrom(record);

    expect(reopened.metrics.maxSpeedMps, 5.5);
    expect(reopened.metrics.elevationGainMeters, 42.0);
  });

  test('elapsed and elapsedWallClock both use movingSeconds', () {
    final record = _recordWith();

    final reopened = reopenedRunSummaryFrom(record);

    expect(reopened.metrics.elapsed, const Duration(seconds: 900));
    expect(reopened.metrics.elapsedWallClock, const Duration(seconds: 900));
  });

  test('currentSplit is a placeholder with no target, one past the last completed', () {
    final record = _recordWith(
      splits: const [
        RunSummarySplit(
          index: 1,
          durationSeconds: 300,
          avgSpeedMps: 3.33,
          distanceMeters: 1000,
        ),
      ],
    );

    final reopened = reopenedRunSummaryFrom(record);

    expect(reopened.metrics.currentSplit.index, 2);
    expect(reopened.metrics.currentSplit.targetSpeedMps, isNull);
    expect(reopened.metrics.currentSplitElapsed, Duration.zero);
    expect(reopened.metrics.currentSplitDistanceMeters, 0);
  });

  test('infers mi when the first split is ~1 mile', () {
    final record = _recordWith(
      splits: const [
        RunSummarySplit(
          index: 1,
          durationSeconds: 300,
          avgSpeedMps: 3.33,
          distanceMeters: 1609.344,
        ),
      ],
    );

    expect(reopenedRunSummaryFrom(record).distanceUnit, DistanceUnit.mi);
  });

  test('infers km when the first split is ~1 km', () {
    final record = _recordWith(
      splits: const [
        RunSummarySplit(
          index: 1,
          durationSeconds: 300,
          avgSpeedMps: 3.33,
          distanceMeters: 1000,
        ),
      ],
    );

    expect(reopenedRunSummaryFrom(record).distanceUnit, DistanceUnit.km);
  });

  test('defaults to km with no splits to infer from', () {
    final record = _recordWith();

    expect(reopenedRunSummaryFrom(record).distanceUnit, DistanceUnit.km);
  });

  test('defaults to km for a split size matching neither unit (time-based split)', () {
    final record = _recordWith(
      splits: const [
        RunSummarySplit(
          index: 1,
          durationSeconds: 300,
          avgSpeedMps: 2.8,
          distanceMeters: 840,
        ),
      ],
    );

    expect(reopenedRunSummaryFrom(record).distanceUnit, DistanceUnit.km);
  });
}
