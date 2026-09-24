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

import '../../fakes/fake_api_client.dart';
import '../../fakes/fake_connectivity_monitor.dart';
import '../../fakes/fake_run_store.dart';

class _SignedOutAuthController extends AuthStateController {
  @override
  Future<AuthState> build() async => const AuthState();
}

RunRecord _record({
  List<RunSummarySplit> splits = const [],
  double? maxSpeedMps,
  double elevationGainMeters = 0,
  ActivityMode activityMode = ActivityMode.running,
}) {
  final started = DateTime.utc(2026, 1, 1, 7);
  return RunRecord(
    clientRunId: 'run-1',
    gpxPath: '/documents/runs/run_run-1.gpx',
    activityMode: activityMode,
    summary: RunSummary(
      clientRunId: 'run-1',
      startedAt: started,
      endedAt: started.add(const Duration(minutes: 30)),
      activityMode: activityMode,
      movingSeconds: 1800,
      distanceMeters: 5000,
      avgSpeedMps: 2.78,
      maxSpeedMps: maxSpeedMps,
      elevationGainMeters: elevationGainMeters,
      splits: splits,
      sourcePlatform: 'android',
      sourceAppVersion: '1.0.0+1',
    ),
    syncStatus: const SyncStatusPending(),
  );
}

Widget _wrap(RunRecord record, FakeRunStore store) {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform({});
  final api = FakeApiClient();
  final connectivity = FakeConnectivityMonitor();
  return ProviderScope(
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
    child: MaterialApp(home: ReopenedRunScreen(record: record)),
  );
}

void main() {
  testWidgets('renders distance, avg, and completed splits with their targets', (tester) async {
    final record = _record(
      splits: const [
        RunSummarySplit(
          index: 1,
          durationSeconds: 300,
          avgSpeedMps: 3.33,
          distanceMeters: 1000,
          targetSpeedMps: 3.5,
        ),
      ],
      maxSpeedMps: 5.5,
      elevationGainMeters: 42.0,
    );
    final store = FakeRunStore()..seed(record);

    await tester.pumpWidget(_wrap(record, store));
    await tester.pumpAndSettle();

    expect(find.text('Distance'), findsOneWidget);
    expect(find.text('Avg'), findsOneWidget);
    expect(find.textContaining('Splits (1)'), findsOneWidget);
  });

  testWidgets('shows the sync status line for the record', (tester) async {
    final record = _record();
    final store = FakeRunStore()..seed(record);

    await tester.pumpWidget(_wrap(record, store));
    await tester.pumpAndSettle();

    expect(find.text('Sign in to upload'), findsOneWidget);
  });

  testWidgets('Close pops the screen', (tester) async {
    final record = _record();
    final store = FakeRunStore()..seed(record);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          runStoreProvider.overrideWithValue(store),
          authStateControllerProvider.overrideWith(_SignedOutAuthController.new),
        ],
        child: MaterialApp(
          home: Builder(
            builder: (context) => ElevatedButton(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => ReopenedRunScreen(record: record)),
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(find.byType(ReopenedRunScreen), findsOneWidget);

    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();
    expect(find.byType(ReopenedRunScreen), findsNothing);
  });

  testWidgets('Delete confirms, then removes the record and pops', (tester) async {
    final record = _record();
    final store = FakeRunStore()..seed(record);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          runStoreProvider.overrideWithValue(store),
          authStateControllerProvider.overrideWith(_SignedOutAuthController.new),
        ],
        child: MaterialApp(
          home: Builder(
            builder: (context) => ElevatedButton(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => ReopenedRunScreen(record: record)),
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();
    expect(find.text('Delete this activity?'), findsOneWidget);

    await tester.tap(find.widgetWithText(FilledButton, 'Delete'));
    await tester.pumpAndSettle();

    expect(find.byType(ReopenedRunScreen), findsNothing);
    expect(await store.listAll(), isEmpty);
  });

  testWidgets('cycling mode hides the splits panel', (tester) async {
    final record = _record(activityMode: ActivityMode.cycling);
    final store = FakeRunStore()..seed(record);

    await tester.pumpWidget(_wrap(record, store));
    await tester.pumpAndSettle();

    expect(find.textContaining('Splits ('), findsNothing);
    expect(find.text('Max speed'), findsOneWidget);
  });
}
