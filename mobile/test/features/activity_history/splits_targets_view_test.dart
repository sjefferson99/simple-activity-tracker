import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/features/activity_history/splits_targets_view.dart';

Map<String, dynamic> _split({
  required int index,
  double distanceM = 1000,
  double durationS = 300,
  double? avgSpeedMps = 3.33,
  double? targetSpeedMps,
  String? verdict,
}) => {
  'index': index,
  'distance_m': distanceM,
  'duration_seconds': durationS,
  'avg_speed_mps': avgSpeedMps,
  'target_speed_mps': targetSpeedMps,
  'verdict': verdict,
};

Future<void> _pump(WidgetTester tester, Map<String, dynamic> analysisResult) async {
  await tester.pumpWidget(
    MaterialApp(
      home: Scaffold(body: SplitsTargetsView(analysisResult: analysisResult)),
    ),
  );
}

void main() {
  testWidgets('renders nothing when there are no splits', (tester) async {
    await _pump(tester, {'splits': <Map<String, dynamic>>[]});

    expect(find.text('Splits'), findsNothing);
  });

  testWidgets('renders splits with no target column when none have a target', (tester) async {
    await _pump(tester, {
      'split_type': 'distance_km',
      'split_targets_as': null,
      'splits': [_split(index: 1), _split(index: 2)],
    });

    expect(find.text('Splits'), findsOneWidget);
    expect(find.text('#1'), findsOneWidget);
    expect(find.text('#2'), findsOneWidget);
    // No delta text ("on target" / an arrow) should appear without a target.
    expect(find.textContaining('on target'), findsNothing);
  });

  testWidgets('shows a delta for an on-target split', (tester) async {
    await _pump(tester, {
      'split_type': 'distance_km',
      'split_targets_as': 'speed',
      'splits': [
        _split(index: 1, avgSpeedMps: 3.33, targetSpeedMps: 3.33, verdict: 'on_target'),
      ],
    });

    expect(find.textContaining('on target'), findsOneWidget);
  });

  testWidgets('shows a slow-down delta for a too-fast split', (tester) async {
    await _pump(tester, {
      'split_type': 'distance_km',
      'split_targets_as': 'speed',
      'splits': [
        _split(index: 1, avgSpeedMps: 4.0, targetSpeedMps: 3.0, verdict: 'too_fast'),
      ],
    });

    expect(find.textContaining('fast'), findsOneWidget);
  });

  testWidgets('shows a speed-up delta for a too-slow split', (tester) async {
    await _pump(tester, {
      'split_type': 'distance_km',
      'split_targets_as': 'speed',
      'splits': [
        _split(index: 1, avgSpeedMps: 2.0, targetSpeedMps: 3.0, verdict: 'too_slow'),
      ],
    });

    expect(find.textContaining('slow'), findsOneWidget);
  });

  testWidgets('formats pace when split_targets_as is pace', (tester) async {
    await _pump(tester, {
      'split_type': 'distance_km',
      'split_targets_as': 'pace',
      'splits': [
        _split(index: 1, avgSpeedMps: 3.33, targetSpeedMps: 3.33, verdict: 'on_target'),
      ],
    });

    expect(find.textContaining('/km'), findsOneWidget);
  });

  testWidgets('formats miles when split_type is distance_mi', (tester) async {
    await _pump(tester, {
      'split_type': 'distance_mi',
      'split_targets_as': null,
      'splits': [_split(index: 1, distanceM: 1609.344)],
    });

    expect(find.textContaining('mi'), findsWidgets);
  });
}
