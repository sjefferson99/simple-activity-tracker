import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:simple_runner/domain/models/live_metrics.dart';
import 'package:simple_runner/domain/models/run_summary.dart';
import 'package:simple_runner/domain/models/split.dart';

void main() {
  // Mirrors server/tests/conftest.py's make_summary() — the server has no
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
    expect(summary.movingSeconds, 900.0);
    expect(summary.distanceMeters, 3000.0);
    expect(summary.avgSpeedMps, 3.33);
    expect(summary.splits, hasLength(1));
    expect(summary.splits.first.index, 1);
    expect(summary.splits.first.durationSeconds, 300.0);
    expect(summary.splits.first.avgSpeedMps, 3.33);
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
      currentSpeedMps: null,
      avgSpeedMps: 3.33,
      completedSplits: const [
        Split(index: 1, duration: Duration(seconds: 300), avgSpeedMps: 3.33),
      ],
      currentSplitElapsed: Duration.zero,
      currentSplitDistanceMeters: 0,
    );

    final summary = RunSummary.fromMetrics(
      clientRunId: '11111111-1111-1111-1111-111111111111',
      startedAt: DateTime.utc(2026, 1, 1, 7, 0, 0),
      endedAt: DateTime.utc(2026, 1, 1, 7, 16, 30),
      metrics: metrics,
      sourcePlatform: 'android',
      sourceAppVersion: '1.0.0+1',
    );

    expect(summary.toJson(), fixture);
  });

  test('toJson serializes local timestamps as UTC', () {
    final summary = RunSummary.fromMetrics(
      clientRunId: 'abc',
      startedAt: DateTime(2026, 6, 1, 10, 0, 0), // local time, no offset
      endedAt: DateTime(2026, 6, 1, 10, 30, 0),
      metrics: LiveMetrics.zero,
      sourcePlatform: 'android',
      sourceAppVersion: '1.0.0+1',
    );

    final json = summary.toJson();
    expect(json['started_at'], endsWith('Z'));
    expect(json['ended_at'], endsWith('Z'));
  });
}
