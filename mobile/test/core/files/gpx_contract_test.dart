import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/files/run_gpx_log.dart';
import 'package:simple_activity_tracker/domain/models/track_point.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';
import 'package:simple_activity_tracker/domain/tracking/run_clock.dart';
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

/// Name, plan and the barometer reading on every fix (null: none, as on a
/// phone without one).
typedef _Case = ({SplitPlan plan, double? pressureHpa});

final _cases = <String, _Case>{
  'custom-plan': (
    plan: const SplitPlan(
      base: SplitPreference.defaultPreference,
      customSplits: [
        PlannedSplit(size: 400, targetSpeedMps: 3.5),
        PlannedSplit(size: 200),
        PlannedSplit(size: 400, targetSpeedMps: 3.25),
      ],
    ),
    pressureHpa: null,
  ),
  'rolling-target': (
    plan: const SplitPlan(
      base: SplitPreference.defaultPreference,
      rollingTargetSpeedMps: 3.0,
      targetsAsPace: false,
    ),
    pressureHpa: null,
  ),
  'barometer': (plan: SplitPlan.defaultPlan, pressureHpa: 1013.25),
};

/// When each case's run clock ran (`sat:clock_spans`, issue #161): Start 8 s
/// before the first fix, Stop 2 s after the last; custom-plan also pauses
/// for 6 s between the 6th and 7th fixes (a new track segment on resume).
DateTime _at(int minute, int second) =>
    DateTime.utc(2026, 9, 24, 7, minute, second);
final _startedAt = DateTime.utc(2026, 9, 24, 6, 59, 52);
final _stoppedAt = _at(1, 52);
final _pauses = <String, List<(DateTime, DateTime)>>{
  'custom-plan': [(_at(0, 52), _at(0, 58))],
  'rolling-target': [],
  'barometer': [],
};

/// 12 fixes, 10 s apart, ~30 m apart heading north — a steady 3 m/s jog.
List<TrackPoint> _points(double? pressureHpa) => [
  for (var i = 0; i < 12; i++)
    TrackPoint(
      latitude: 51.5 + i * 0.00027,
      longitude: -0.1,
      elevationMeters: 20.0 + i,
      timestamp: DateTime.utc(2026, 9, 24, 7, 0, i * 10),
      accuracyMeters: 4,
      speedMps: 3,
      hasSpeed: true,
      pressureHpa: pressureHpa,
      // The tuning diagnostics come with the barometer case only, so the
      // other goldens keep showing a phone that logs none of them.
      pressureSdHpa: pressureHpa == null ? null : 0.0123,
      verticalAccuracyMeters: pressureHpa == null ? null : 3.5,
      motionRmsMps2: pressureHpa == null ? null : 4.567,
      cadenceHz: pressureHpa == null ? null : 2.83,
    ),
];

List<List<String>> _expectedSpans(String name) {
  final bounds = [
    _startedAt,
    for (final (pause, resume) in _pauses[name]!) ...[pause, resume],
    _stoppedAt,
  ];
  return [
    for (var i = 0; i < bounds.length; i += 2)
      [bounds[i].toIso8601String(), bounds[i + 1].toIso8601String()],
  ];
}

Map<String, dynamic> _expected(
  String name,
  SplitPlan plan,
  List<TrackPoint> points,
) => {
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
    if (points.first.pressureHpa != null)
      'pressure_hpa': points.first.pressureHpa,
  },
  'clock_spans': _expectedSpans(name),
};

String _normalise(String text) => text.replaceAll('\r\n', '\n');

void main() {
  late Directory tempDir;

  setUp(() async => tempDir = await Directory.systemTemp.createTemp('gpx_contract'));
  tearDown(() => tempDir.delete(recursive: true));

  for (final MapEntry(key: name, value: (:plan, :pressureHpa))
      in _cases.entries) {
    test('$name.gpx matches what the app writes', () async {
      final written = File('${tempDir.path}/$name.gpx');
      final clock = RunClock(startedAt: _startedAt);
      final log = RunGpxLog(written, plan, ActivityMode.running, clock: clock);
      final points = _points(pressureHpa);
      final pauses = [..._pauses[name]!];
      for (final point in points) {
        if (pauses.isNotEmpty && point.timestamp.isAfter(pauses.first.$2)) {
          final (pause, resume) = pauses.removeAt(0);
          clock.pause(pause);
          clock.resume(resume);
          log.startNewSegment();
        }
        log.addPoint(point);
      }
      clock.pause(_stoppedAt);
      await log.finalizeAndFlush();

      final golden = File('${_contractDir.path}/$name.gpx');
      final expected = File('${_contractDir.path}/$name.expected.json');
      if (_updateContract) {
        _contractDir.createSync(recursive: true);
        golden.writeAsStringSync(_normalise(written.readAsStringSync()));
        expected.writeAsStringSync(
          '${const JsonEncoder.withIndent('  ').convert(_expected(name, plan, points))}\n',
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
      expect(
        _expected(name, plan, points),
        jsonDecode(expected.readAsStringSync()),
      );
    });
  }
}
