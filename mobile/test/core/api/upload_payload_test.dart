import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/upload_payload.dart';
import 'package:simple_activity_tracker/core/version/api_compat.dart';
import 'package:simple_activity_tracker/domain/models/run_summary.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';

/// Rewrite the golden files instead of comparing against them:
/// `flutter test --dart-define=UPDATE_CONTRACT=true test/core/api/upload_payload_test.dart`
const _updateContract = bool.fromEnvironment('UPDATE_CONTRACT');

/// Shared with server/tests/test_api_contract.py — docs/VERSIONING.md §6.
final _contractDir = Directory('../contract/upload-summary');

/// Frozen: the only fields servers up to v1.2.4 (API level 0) accept — any
/// other field fails the whole upload there. Never add to these sets; a new
/// field belongs to a new API level instead.
const _level0Fields = {
  'client_activity_id',
  'started_at',
  'ended_at',
  'activity_type',
  'moving_seconds',
  'distance_meters',
  'avg_speed_mps',
  'splits',
  'source',
};
const _level0SplitFields = {'index', 'duration_seconds', 'avg_speed_mps', 'distance_m'};
const _level0SourceFields = {'platform', 'app_version'};

/// Every optional field populated, so each level's gating is exercised.
final _summary = RunSummary(
  clientRunId: 'c0a1e9d2-0000-4000-8000-00000000c0de',
  startedAt: DateTime.utc(2026, 9, 24, 7),
  endedAt: DateTime.utc(2026, 9, 24, 7, 16, 30),
  activityMode: ActivityMode.running,
  movingSeconds: 900,
  distanceMeters: 3000,
  avgSpeedMps: 3.33,
  maxSpeedMps: 4.2,
  elevationGainMeters: 12.5,
  splits: const [
    RunSummarySplit(
      index: 1,
      durationSeconds: 300,
      avgSpeedMps: 3.33,
      distanceMeters: 1000,
      targetSpeedMps: 3.4,
    ),
  ],
  sourcePlatform: 'android',
  sourceAppVersion: '1.3.0+60',
);

void main() {
  for (var level = 0; level <= kAppApiLevel; level++) {
    test('api-level-$level.json matches what the app sends a level $level server', () {
      final file = File('${_contractDir.path}/api-level-$level.json');
      final payload = buildUploadSummaryJson(_summary, serverApiLevel: level);
      if (_updateContract) {
        file.writeAsStringSync('${const JsonEncoder.withIndent('  ').convert(payload)}\n');
      }
      expect(
        file.existsSync(),
        isTrue,
        reason: 'Missing ${file.path} — regenerate with --dart-define=UPDATE_CONTRACT=true',
      );
      expect(
        payload,
        jsonDecode(file.readAsStringSync()),
        reason:
            'The upload payload for API level $level changed. If that was deliberate, '
            'regenerate the golden file (--dart-define=UPDATE_CONTRACT=true) and make '
            'sure the change is gated on a new API level (docs/VERSIONING.md §3.1).',
      );
    });
  }

  test('a level 0 server only ever receives the fields it accepts', () {
    final payload = buildUploadSummaryJson(_summary, serverApiLevel: 0);
    expect(_level0Fields.containsAll(payload.keys), isTrue, reason: '${payload.keys}');
    for (final split in payload['splits'] as List<dynamic>) {
      expect(_level0SplitFields.containsAll((split as Map).keys), isTrue, reason: '$split');
    }
    expect(_level0SourceFields.containsAll((payload['source'] as Map).keys), isTrue);
  });

  test('the current level sends the full summary', () {
    expect(buildUploadSummaryJson(_summary, serverApiLevel: kAppApiLevel), _summary.toJson());
  });

  test('a server newer than the app gets the full summary too', () {
    expect(
      buildUploadSummaryJson(_summary, serverApiLevel: kAppApiLevel + 5),
      _summary.toJson(),
    );
  });

  test('shaping never modifies the summary itself', () {
    final before = jsonEncode(_summary.toJson());
    buildUploadSummaryJson(_summary, serverApiLevel: 0);
    expect(jsonEncode(_summary.toJson()), before);
  });
}
