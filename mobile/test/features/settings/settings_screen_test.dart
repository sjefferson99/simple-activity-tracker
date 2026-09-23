import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/auth/auth_service.dart';
import 'package:simple_activity_tracker/core/auth/auth_state.dart';
import 'package:simple_activity_tracker/core/auth/auth_state_controller.dart';
import 'package:simple_activity_tracker/core/sync/file_run_store.dart';
import 'package:simple_activity_tracker/core/sync/sync_service.dart';
import 'package:simple_activity_tracker/domain/models/run_record.dart';
import 'package:simple_activity_tracker/domain/models/run_summary.dart';
import 'package:simple_activity_tracker/domain/models/sync_status.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';
import 'package:simple_activity_tracker/features/live_run/reopened_run_screen.dart';
import 'package:simple_activity_tracker/features/settings/settings_screen.dart';

import '../../fakes/fake_api_client.dart';
import '../../fakes/fake_connectivity_monitor.dart';
import '../../fakes/fake_run_store.dart';

class _SignedOutAuthController extends AuthStateController {
  @override
  Future<AuthState> build() async => const AuthState();
}

RunRecord _record() {
  final started = DateTime.utc(2026, 1, 1, 7);
  return RunRecord(
    clientRunId: 'run-1',
    gpxPath: '/documents/runs/run_run-1.gpx',
    activityMode: ActivityMode.running,
    summary: RunSummary(
      clientRunId: 'run-1',
      startedAt: started,
      endedAt: started.add(const Duration(minutes: 30)),
      activityMode: ActivityMode.running,
      movingSeconds: 1800,
      distanceMeters: 5000,
      avgSpeedMps: 2.78,
      splits: const [],
      sourcePlatform: 'android',
      sourceAppVersion: '1.0.0+1',
    ),
    syncStatus: const SyncStatusPending(),
  );
}

void main() {
  testWidgets('tapping an activity row reopens its finished summary', (tester) async {
    FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform({});
    final api = FakeApiClient();
    final connectivity = FakeConnectivityMonitor();
    final store = FakeRunStore()..seed(_record());

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          runStoreProvider.overrideWithValue(store),
          syncServiceProvider.overrideWithValue(
            SyncService(
              apiClient: api,
              runStore: store,
              authService: AuthService(apiClient: api, storage: const FlutterSecureStorage()),
              connectivity: connectivity,
              periodicRetryInterval: null,
            ),
          ),
          authStateControllerProvider.overrideWith(_SignedOutAuthController.new),
        ],
        child: const MaterialApp(home: SettingsScreen()),
      ),
    );
    await tester.pumpAndSettle();
    // The Activities section sits below the sign-in form, past the initial
    // viewport — ListView's Sliver machinery only builds Elements for
    // children it's actually laid out, even for the plain non-lazy
    // constructor, so the row has to be scrolled into view before it can be
    // found/tapped.
    await tester.scrollUntilVisible(
      find.text('Activities'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();

    expect(find.text('Run • 5.00 km'), findsOneWidget);

    await tester.tap(find.text('Run • 5.00 km'));
    await tester.pumpAndSettle();

    expect(find.byType(ReopenedRunScreen), findsOneWidget);
  });

  testWidgets(
    'deleting from the reopened screen removes the row from the activity list '
    '(regression: reported as "closes the page but doesn\'t delete")',
    (tester) async {
      FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform({});
      final api = FakeApiClient();
      final connectivity = FakeConnectivityMonitor();
      final store = FakeRunStore()..seed(_record());

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            runStoreProvider.overrideWithValue(store),
            syncServiceProvider.overrideWithValue(
              SyncService(
                apiClient: api,
                runStore: store,
                authService: AuthService(apiClient: api, storage: const FlutterSecureStorage()),
                connectivity: connectivity,
                periodicRetryInterval: null,
              ),
            ),
            authStateControllerProvider.overrideWith(_SignedOutAuthController.new),
          ],
          child: const MaterialApp(home: SettingsScreen()),
        ),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('Activities'),
        300,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.pumpAndSettle();

      await tester.tap(find.text('Run • 5.00 km'));
      await tester.pumpAndSettle();
      expect(find.byType(ReopenedRunScreen), findsOneWidget);

      await tester.tap(find.text('Delete'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Delete'));
      await tester.pumpAndSettle();

      // Back on Settings — the row must be gone, not just the reopened
      // screen closed. Before the fix, _syncQueueProvider (private to
      // settings_screen.dart) was never invalidated by a delete performed
      // from ReopenedRunScreen (a different file), so the stale list kept
      // showing the just-deleted row until Settings was reopened.
      expect(find.byType(ReopenedRunScreen), findsNothing);
      expect(find.text('Run • 5.00 km'), findsNothing);
      expect(find.text('No activities recorded yet.'), findsOneWidget);
      expect(await store.listAll(), isEmpty);
    },
  );
}
