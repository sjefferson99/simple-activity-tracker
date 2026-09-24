import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/files/run_gpx_log.dart';
import 'package:simple_activity_tracker/domain/models/track_point.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';

/// The GPX the app uploads is a contract too (docs/VERSIONING.md §6): the
/// server reads the `sat:` extensions for splits, targets and per-point
/// speed/accuracy, and openapi.json can't describe any of it. These golden
/// files are written by the real [RunGpxLog]; each comes with an
/// `.expected.json` stating what the app *means* by it, which
/// server/tests/test_gpx_contract.py checks the server's parser extracts.
///
/// Rewrite after a deliberate change:
/// `flutter test --dart-define=UPDATE_CONTRACT=true test/core/files/gpx_contract_test.dart`
/// — but an existing extension's value format must never change (older
/// servers would misread it); new meaning needs a new extension name.
const _updateContract = bool.fromEnvironment('UPDATE_CONTRACT');

final _contractDir = Directory('../contract/gpx');

final _cases = <String, SplitPlan>{
  'custom-plan': const SplitPlan(
    base: SplitPreference.defaultPreference,
    customSplits: [
      PlannedSplit(size: 400, targetSpeedMps: 3.5),
      PlannedSplit(size: 200),
      PlannedSplit(size: 400, targetSpeedMps: 3.25),
    ],
  ),
  'rolling-target': const SplitPlan(
    base: SplitPreference.defaultPreference,
    rollingTargetSpeedMps: 3.0,
    targetsAsPace: false,
  ),
};

/// 12 fixes, 10 s apart, ~30 m apart heading north — a steady 3 m/s jog.
List<TrackPoint> _points() => [
  for (var i = 0; i < 12; i++)
    TrackPoint(
      latitude: 51.5 + i * 0.00027,
      longitude: -0.1,
      elevationMeters: 20.0 + i,
      timestamp: DateTime.utc(2026, 9, 24, 7, 0, i * 10),
      accuracyMeters: 4,
      speedMps: 3,
      hasSpeed: true,
    ),
];

Map<String, dynamic> _expected(SplitPlan plan, List<TrackPoint> points) => {
  'split_type': plan.base.gpxSplitType,
  'split_value': plan.base.value,
  'rolling_target_mps': plan.isCustom ? null : plan.rollingTargetSpeedMps,
  'custom_splits': [
    for (final split in plan.customSplits) [split.size, split.targetSpeedMps],
  ],
  'targets_as': plan.targetsAsPace ? 'pace' : 'speed',
  'point_count': points.length,
  'first_point': {
    'accuracy_m': points.first.accuracyMeters,
    'speed_mps': points.first.speedMps,
  },
};

String _normalise(String text) => text.replaceAll('\r\n', '\n');

void main() {
  late Directory tempDir;

  setUp(() async => tempDir = await Directory.systemTemp.createTemp('gpx_contract'));
  tearDown(() => tempDir.delete(recursive: true));

  for (final MapEntry(key: name, value: plan) in _cases.entries) {
    test('$name.gpx matches what the app writes', () async {
      final written = File('${tempDir.path}/$name.gpx');
      final log = RunGpxLog(written, plan, ActivityMode.running);
      final points = _points();
      for (final point in points) {
        log.addPoint(point);
      }
      await log.finalizeAndFlush();

      final golden = File('${_contractDir.path}/$name.gpx');
      final expected = File('${_contractDir.path}/$name.expected.json');
      if (_updateContract) {
        _contractDir.createSync(recursive: true);
        golden.writeAsStringSync(_normalise(written.readAsStringSync()));
        expected.writeAsStringSync(
          '${const JsonEncoder.withIndent('  ').convert(_expected(plan, points))}\n',
        );
      }

      expect(
        golden.existsSync() && expected.existsSync(),
        isTrue,
        reason: 'Missing ${golden.path} — regenerate with --dart-define=UPDATE_CONTRACT=true',
      );
      expect(
        _normalise(written.readAsStringSync()),
        _normalise(golden.readAsStringSync()),
        reason:
            'The GPX the app writes changed. Existing sat: extension formats must not '
            'change (docs/VERSIONING.md §5); if this is a new extension, regenerate '
            'with --dart-define=UPDATE_CONTRACT=true.',
      );
      expect(_expected(plan, points), jsonDecode(expected.readAsStringSync()));
    });
  }
}
