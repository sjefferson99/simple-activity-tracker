import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/models/current_split_info.dart';
import 'package:simple_activity_tracker/domain/models/live_metrics.dart';
import 'package:simple_activity_tracker/domain/models/run_summary.dart';
import 'package:simple_activity_tracker/domain/models/split.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';

void main() {
  // Mirrors server/tests/conftest.py's make_summary() â€” the server has no
  // OpenAPI example for this shape (it's parsed from a raw JSON form field,
  // not a typed request body), so its own test fixture is the closest thing
  // to a canonical example.
  final fixture = jsonDecode(
    File('test/fixtures/run_summary_sample.json').readAsStringSync(),
  ) as Map<String, dynamic>;

  test('fromJson parses the server fixture', () {
    final summary = RunSummary.fromJson(fixture);

    expect(summary.clientRunId, '11111111-1111-1111-1111-111111111111');
    expect(summary.startedAt, DateTime.utc(2026, 1, 1, 7, 0, 0));
    expect(summary.endedAt, DateTime.utc(2026, 1, 1, 7, 16, 30));
    expect(summary.activityMode, ActivityMode.running);
    expect(summary.movingSeconds, 900.0);
    expect(summary.distanceMeters, 3000.0);
    expect(summary.avgSpeedMps, 3.33);
    expect(summary.maxSpeedMps, 4.5);
    expect(summary.elevationGainMeters, 12.5);
    expect(summary.splits, hasLength(1));
    expect(summary.splits.first.index, 1);
    expect(summary.splits.first.durationSeconds, 300.0);
    expect(summary.splits.first.avgSpeedMps, 3.33);
    expect(summary.splits.first.distanceMeters, 1000.0);
    expect(summary.splits.first.targetSpeedMps, 3.5);
    expect(summary.sourcePlatform, 'android');
    expect(summary.sourceAppVersion, '1.0.0+1');
  });

  test('toJson round-trips through fromJson against the server fixture', () {
    final summary = RunSummary.fromJson(fixture);
    final roundTripped = RunSummary.fromJson(summary.toJson());

    expect(roundTripped.toJson(), summary.toJson());
    expect(summary.toJson(), fixture);
  });

  test('fromMetrics builds a RunSummary matching the wire format', () {
    final metrics = LiveMetrics(
      elapsed: const Duration(seconds: 900),
      distanceMeters: 3000.0,
      avgSpeedMps: 3.33,
      maxSpeedMps: 4.5,
      elevationGainMeters: 12.5,
      completedSplits: const [
        Split(
          index: 1,
          duration: Duration(seconds: 300),
          avgSpeedMps: 3.33,
          distanceMeters: 1000.0,
          targetSpeedMps: 3.5,
        ),
      ],
      currentSplitElapsed: Duration.zero,
      currentSplitDistanceMeters: 0,
      currentSplit: const CurrentSplitInfo(
        index: 2,
        plannedCount: null,
        sizeKind: SplitSizeKind.distanceMeters,
        size: 1000,
        targetSpeedMps: null,
      ),
    );

    final summary = RunSummary.fromMetrics(
      clientRunId: '11111111-1111-1111-1111-111111111111',
      startedAt: DateTime.utc(2026, 1, 1, 7, 0, 0),
      endedAt: DateTime.utc(2026, 1, 1, 7, 16, 30),
      activityMode: ActivityMode.running,
      metrics: metrics,
      sourcePlatform: 'android',
      sourceAppVersion: '1.0.0+1',
    );

    expect(summary.toJson(), fixture);
  });

  test(
    'fromJson defaults distanceMeters to 1000.0 for an old sidecar with no distance_m',
    () {
      final oldShape = Map<String, dynamic>.from(fixture);
      oldShape['splits'] = [
        {'index': 1, 'duration_seconds': 300.0, 'avg_speed_mps': 3.33},
      ];

      final summary = RunSummary.fromJson(oldShape);
      expect(summary.splits.first.distanceMeters, 1000.0);
    },
  );

  test(
    'fromJson defaults maxSpeedMps/elevationGainMeters/targetSpeedMps for '
    'an old sidecar written before #106',
    () {
      final oldShape = Map<String, dynamic>.from(fixture)
        ..remove('max_speed_mps')
        ..remove('elevation_gain_meters');
      oldShape['splits'] = [
        {
          'index': 1,
          'duration_seconds': 300.0,
          'avg_speed_mps': 3.33,
          'distance_m': 1000.0,
        },
      ];

      final summary = RunSummary.fromJson(oldShape);
      expect(summary.maxSpeedMps, isNull);
      expect(summary.elevationGainMeters, 0);
      expect(summary.splits.first.targetSpeedMps, isNull);
    },
  );

  test('toJson serializes local timestamps as UTC', () {
    final summary = RunSummary.fromMetrics(
      clientRunId: 'abc',
      startedAt: DateTime(2026, 6, 1, 10, 0, 0), // local time, no offset
      endedAt: DateTime(2026, 6, 1, 10, 30, 0),
      activityMode: ActivityMode.running,
      metrics: LiveMetrics.zero,
      sourcePlatform: 'android',
      sourceAppVersion: '1.0.0+1',
    );

    final json = summary.toJson();
    expect(json['started_at'], endsWith('Z'));
    expect(json['ended_at'], endsWith('Z'));
  });
}
