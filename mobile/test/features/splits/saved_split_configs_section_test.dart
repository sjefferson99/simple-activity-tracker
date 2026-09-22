import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/api_client.dart';
import 'package:simple_activity_tracker/core/api/api_exception.dart';
import 'package:simple_activity_tracker/core/api/dto/split_config_dto.dart';
import 'package:simple_activity_tracker/core/auth/auth_state.dart';
import 'package:simple_activity_tracker/core/auth/auth_state_controller.dart';
import 'package:simple_activity_tracker/core/tracking/split_plan_controller.dart';
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';
import 'package:simple_activity_tracker/features/splits/splits_screen.dart';

import '../../fakes/fake_api_client.dart';

class _SignedOutAuthController extends AuthStateController {
  @override
  Future<AuthState> build() async => AuthState.empty;
}

class _SignedInAuthController extends AuthStateController {
  @override
  Future<AuthState> build() async => const AuthState(
    serverUrl: 'https://example.com',
    token: 't',
    email: 'runner@example.com',
  );
}

SplitConfigDto _config(
  String name, {
  double? rollingTargetMps = 2.5,
  SplitKind kind = SplitKind.distanceKm,
}) => SplitConfigDto(
  id: name,
  name: name,
  plan: SplitPlan(
    base: SplitPreference(kind: kind, value: 1),
    rollingTargetSpeedMps: rollingTargetMps,
  ),
  createdAt: DateTime.utc(2026),
  updatedAt: DateTime.utc(2026),
);

Future<void> _pumpSignedIn(
  WidgetTester tester,
  FakeApiClient fakeApiClient,
) async {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform({});
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        authStateControllerProvider.overrideWith(_SignedInAuthController.new),
        apiClientProvider.overrideWithValue(fakeApiClient),
      ],
      child: const MaterialApp(home: SplitsScreen()),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'pulling down on the Splits screen reloads saved configs from the server',
    (tester) async {
      var listCallCount = 0;
      final fake = FakeApiClient()
        ..listSplitConfigsHandler = ({required baseUrl, required token}) async {
          listCallCount++;
          return listCallCount == 1
              ? [_config('First')]
              : [_config('Second', rollingTargetMps: null)];
        };
      await _pumpSignedIn(tester, fake);

      expect(listCallCount, 1);
      expect(find.text('First'), findsOneWidget);

      // Pull-to-refresh: a downward fling on the ListView, same gesture
      // RefreshIndicator's own tests use to trigger it in widget tests.
      await tester.fling(find.byType(ListView), const Offset(0, 300), 1000);
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));
      await tester.pumpAndSettle();

      expect(listCallCount, 2);
      expect(find.text('Second'), findsOneWidget);
      expect(find.text('First'), findsNothing);
    },
  );

  testWidgets('signed out shows a sign-in prompt, not the picker', (
    tester,
  ) async {
    FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(
      {},
    );
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authStateControllerProvider.overrideWith(
            _SignedOutAuthController.new,
          ),
          apiClientProvider.overrideWithValue(FakeApiClient()),
        ],
        child: const MaterialApp(home: SplitsScreen()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Sign in to load or save split configs'), findsOneWidget);
    expect(find.text('Save as…'), findsNothing);
  });

  testWidgets('signed in with no saved configs shows the empty state', (
    tester,
  ) async {
    final fake = FakeApiClient()
      ..listSplitConfigsHandler = ({required baseUrl, required token}) async =>
          [];
    await _pumpSignedIn(tester, fake);

    expect(find.textContaining('No saved configs yet'), findsOneWidget);
    expect(find.text('Save as…'), findsOneWidget);
  });

  testWidgets('lists saved configs with a summary line', (tester) async {
    final fake = FakeApiClient()
      ..listSplitConfigsHandler = ({required baseUrl, required token}) async =>
          [_config('5k tempo'), _config('Easy run', rollingTargetMps: null)];
    await _pumpSignedIn(tester, fake);

    expect(find.text('5k tempo'), findsOneWidget);
    expect(find.text('Easy run'), findsOneWidget);
    expect(
      find.textContaining('Rolling, every 1 km with a target'),
      findsOneWidget,
    );
    expect(find.textContaining('Rolling, every 1 km'), findsWidgets);
  });

  testWidgets('a custom plan is summarized by split count', (tester) async {
    final fake = FakeApiClient()
      ..listSplitConfigsHandler = ({required baseUrl, required token}) async =>
          [
            SplitConfigDto(
              id: 'c1',
              name: 'Intervals',
              plan: const SplitPlan(
                base: SplitPreference(kind: SplitKind.timeMin, value: 1),
                customSplits: [
                  PlannedSplit(size: 90, targetSpeedMps: 4),
                  PlannedSplit(size: 60),
                ],
              ),
              createdAt: DateTime.utc(2026),
              updatedAt: DateTime.utc(2026),
            ),
          ];
    await _pumpSignedIn(tester, fake);

    expect(find.text('Custom, 2 splits'), findsOneWidget);
  });

  testWidgets('tapping a saved config loads it into the current plan', (
    tester,
  ) async {
    final fake = FakeApiClient()
      ..listSplitConfigsHandler = ({required baseUrl, required token}) async =>
          [
            _config(
              '5k tempo',
              kind: SplitKind.distanceMi,
              rollingTargetMps: 3.0,
            ),
          ];
    await _pumpSignedIn(tester, fake);

    final container = ProviderScope.containerOf(
      tester.element(find.byType(SplitsScreen)),
    );
    expect(
      container.read(splitPlanControllerProvider).base.kind,
      SplitKind.distanceKm, // default, before loading
    );

    await tester.tap(find.text('5k tempo'));
    await tester.pumpAndSettle();

    final loaded = container.read(splitPlanControllerProvider);
    expect(loaded.base.kind, SplitKind.distanceMi);
    expect(loaded.rollingTargetSpeedMps, 3.0);
    expect(find.textContaining('Loaded "5k tempo"'), findsOneWidget);
  });

  testWidgets('shows an error with retry when the list fails to load', (
    tester,
  ) async {
    final fake = FakeApiClient()
      ..listSplitConfigsHandler = ({required baseUrl, required token}) async =>
          throw const ApiServerException('boom', statusCode: 500);
    await _pumpSignedIn(tester, fake);

    expect(find.textContaining('Could not load saved configs'), findsOneWidget);
    expect(find.byIcon(Icons.refresh), findsOneWidget);
  });

  testWidgets('Save as... saves the current plan under the entered name', (
    tester,
  ) async {
    final fake = FakeApiClient()
      ..listSplitConfigsHandler = ({required baseUrl, required token}) async =>
          [];
    await _pumpSignedIn(tester, fake);

    await tester.tap(find.text('Save as…'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.descendant(
        of: find.byType(AlertDialog),
        matching: find.byType(TextField),
      ),
      'My plan',
    );
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();

    expect(fake.saveSplitConfigCalls, hasLength(1));
    expect(fake.saveSplitConfigCalls.single.name, 'My plan');
    expect(fake.saveSplitConfigCalls.single.overwrite, isFalse);
    expect(find.textContaining('Saved "My plan"'), findsOneWidget);
  });

  testWidgets(
    'a name conflict offers to replace, and retries with overwrite on confirm',
    (tester) async {
      final fake = FakeApiClient()
        ..listSplitConfigsHandler = ({
          required baseUrl,
          required token,
        }) async => [];
      var calls = 0;
      fake.saveSplitConfigHandler =
          ({required baseUrl, required token, required request}) async {
            calls++;
            if (!request.overwrite) {
              throw const ApiRejectedException(
                "A split config named 'My plan' already exists.",
                statusCode: 409,
              );
            }
            final now = DateTime.utc(2026);
            return SplitConfigDto(
              id: 'c1',
              name: request.name,
              plan: request.plan,
              createdAt: now,
              updatedAt: now,
            );
          };
      await _pumpSignedIn(tester, fake);

      await tester.tap(find.text('Save as…'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.byType(TextField),
        ),
        'My plan',
      );
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();

      expect(find.text('Config already exists'), findsOneWidget);
      await tester.tap(find.text('Replace'));
      await tester.pumpAndSettle();

      expect(calls, 2);
      expect(fake.saveSplitConfigCalls.last.overwrite, isTrue);
      expect(find.textContaining('Saved "My plan"'), findsOneWidget);
    },
  );

  testWidgets('cancelling the replace confirmation does not retry the save', (
    tester,
  ) async {
    final fake = FakeApiClient()
      ..listSplitConfigsHandler = ({required baseUrl, required token}) async =>
          [];
    fake.saveSplitConfigHandler =
        ({required baseUrl, required token, required request}) async {
          throw const ApiRejectedException(
            "A split config named 'My plan' already exists.",
            statusCode: 409,
          );
        };
    await _pumpSignedIn(tester, fake);

    await tester.tap(find.text('Save as…'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.descendant(
        of: find.byType(AlertDialog),
        matching: find.byType(TextField),
      ),
      'My plan',
    );
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Cancel').last);
    await tester.pumpAndSettle();

    expect(fake.saveSplitConfigCalls, hasLength(1));
    expect(find.textContaining('Saved "My plan"'), findsNothing);
  });
}
