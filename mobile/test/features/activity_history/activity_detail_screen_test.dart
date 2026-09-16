import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/api_client.dart';
import 'package:simple_activity_tracker/core/api/dto/analysis_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/run_dto.dart';
import 'package:simple_activity_tracker/core/auth/auth_state.dart';
import 'package:simple_activity_tracker/core/auth/auth_state_controller.dart';
import 'package:simple_activity_tracker/features/activity_history/activity_detail_screen.dart';

import '../../fakes/fake_api_client.dart';

class _SignedInAuthController extends AuthStateController {
  @override
  Future<AuthState> build() async =>
      const AuthState(serverUrl: 'https://example.com', token: 't', email: 'runner@example.com');
}

Widget _wrap(FakeApiClient fakeApiClient, {required String activityId}) => ProviderScope(
  overrides: [
    apiClientProvider.overrideWithValue(fakeApiClient),
    authStateControllerProvider.overrideWith(_SignedInAuthController.new),
  ],
  child: MaterialApp(home: ActivityDetailScreen(activityId: activityId)),
);

RunDto _run({required AnalysisDto analysis}) => RunDto(
  id: 'run-1',
  clientRunId: 'client-1',
  startedAt: DateTime.utc(2026, 1, 1, 7),
  endedAt: DateTime.utc(2026, 1, 1, 7, 30),
  activityType: 'running',
  title: 'Morning run',
  notes: null,
  deviceName: 'Pixel 8',
  clientSummary: const {},
  sourcePlatform: 'android',
  sourceAppVersion: '1.0.0+1',
  analysis: analysis,
  tags: const [],
  splitPlan: null,
);

void main() {
  testWidgets('shows a loading indicator while fetching', (tester) async {
    final fake = FakeApiClient()
      ..getActivityHandler = ({
        required baseUrl,
        required token,
        required serverRunId,
      }) => Completer<RunDto>().future;

    await tester.pumpWidget(_wrap(fake, activityId: 'run-1'));

    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });

  testWidgets('shows an error message when the fetch fails', (tester) async {
    final fake = FakeApiClient()
      ..getActivityHandler = ({
        required baseUrl,
        required token,
        required serverRunId,
      }) => Future.error(StateError('boom'));

    await tester.pumpWidget(_wrap(fake, activityId: 'run-1'));
    await tester.pumpAndSettle();

    expect(find.textContaining('Could not load activity'), findsOneWidget);
  });

  testWidgets('shows "Analysis pending" while the server has not finished', (tester) async {
    final fake = FakeApiClient()
      ..getActivityHandler = ({required baseUrl, required token, required serverRunId}) async =>
          _run(analysis: const AnalysisDto(status: 'pending', result: null));

    await tester.pumpWidget(_wrap(fake, activityId: 'run-1'));
    await tester.pumpAndSettle();

    expect(find.text('Analysis pending'), findsOneWidget);
  });

  testWidgets('shows headline stats and splits once analysis is done', (tester) async {
    final fake = FakeApiClient()
      ..getActivityHandler = ({required baseUrl, required token, required serverRunId}) async =>
          _run(
            analysis: const AnalysisDto(
              status: 'done',
              result: {
                'distance_meters': 5000.0,
                'moving_seconds': 1500.0,
                'avg_moving_speed_mps': 3.33,
                'split_type': 'distance_km',
                'split_targets_as': null,
                'splits': [
                  {
                    'index': 1,
                    'distance_m': 1000.0,
                    'duration_seconds': 300.0,
                    'avg_speed_mps': 3.33,
                    'target_speed_mps': null,
                    'verdict': null,
                  },
                ],
              },
            ),
          );

    await tester.pumpWidget(_wrap(fake, activityId: 'run-1'));
    await tester.pumpAndSettle();

    expect(find.text('Morning run'), findsOneWidget);
    // Regression: a titled activity used to hide its date entirely, since
    // the title fully replaced the timestamp fallback text.
    expect(find.textContaining('2026'), findsOneWidget);
    expect(find.textContaining('Distance: 5.00 km'), findsOneWidget);
    expect(find.text('Splits'), findsOneWidget);
    expect(find.text('#1'), findsOneWidget);
  });

  testWidgets(
    'shows best-effort times (regression: dropped when this screen '
    'replaced the old inline Insights section)',
    (tester) async {
      final fake = FakeApiClient()
        ..getActivityHandler = ({required baseUrl, required token, required serverRunId}) async =>
            _run(
              analysis: const AnalysisDto(
                status: 'done',
                result: {
                  'distance_meters': 5000.0,
                  'moving_seconds': 1500.0,
                  'avg_moving_speed_mps': 3.33,
                  'split_type': 'distance_km',
                  'split_targets_as': null,
                  'splits': <Map<String, dynamic>>[],
                  'best_efforts': [
                    {'distance_meters': 1000.0, 'duration_seconds': 298.0, 'avg_speed_mps': 3.36},
                    {'distance_meters': 5000.0, 'duration_seconds': 1490.0, 'avg_speed_mps': 3.36},
                  ],
                },
              ),
            );

      await tester.pumpWidget(_wrap(fake, activityId: 'run-1'));
      await tester.pumpAndSettle();

      expect(find.textContaining('Best 1 km:'), findsOneWidget);
      expect(find.textContaining('Best 5 km:'), findsOneWidget);
    },
  );
}
