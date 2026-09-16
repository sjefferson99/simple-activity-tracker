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
import 'package:simple_activity_tracker/features/activity_history/activity_detail_screen.dart';
import 'package:simple_activity_tracker/features/live_run/run_insights.dart';

import '../../fakes/fake_api_client.dart';
import '../../fakes/fake_connectivity_monitor.dart';
import '../../fakes/fake_run_store.dart';

class _SignedInAuthController extends AuthStateController {
  @override
  Future<AuthState> build() async =>
      const AuthState(serverUrl: 'https://example.com', token: 't', email: 'runner@example.com');
}

RunRecord _uploadedRecord({
  Map<String, dynamic>? analysisResult,
  bool analysisFailed = false,
}) {
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
    syncStatus: const SyncStatusUploaded(serverRunId: 'server-1'),
    analysisResult: analysisResult,
    analysisFailed: analysisFailed,
  );
}

Widget _wrap(FakeRunStore store) {
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
          // No periodic timer in this widget test — it's never disposed
          // (this override outlives the ProviderScope), so a real Timer.periodic
          // here would trip flutter_test's pending-timer check.
          periodicRetryInterval: null,
        ),
      ),
      authStateControllerProvider.overrideWith(_SignedInAuthController.new),
    ],
    child: const MaterialApp(home: Scaffold(body: RunSyncSection(clientRunId: 'run-1'))),
  );
}

void main() {
  testWidgets('shows "Analysis not available yet" while pending', (tester) async {
    final store = FakeRunStore()..seed(_uploadedRecord());

    await tester.pumpWidget(_wrap(store));
    await tester.pumpAndSettle();

    expect(find.text('Analysis not available yet'), findsOneWidget);
  });

  testWidgets('shows "Analysis failed" once retries are exhausted', (tester) async {
    final store = FakeRunStore()..seed(_uploadedRecord(analysisFailed: true));

    await tester.pumpWidget(_wrap(store));
    await tester.pumpAndSettle();

    expect(find.text('Analysis failed'), findsOneWidget);
  });

  testWidgets(
    'shows a "View full summary" link once analysis is done, navigating to the detail screen',
    (tester) async {
      final store = FakeRunStore()
        ..seed(_uploadedRecord(analysisResult: {'distance_meters': 5000.0}));

      await tester.pumpWidget(_wrap(store));
      await tester.pumpAndSettle();

      expect(find.text('View full summary'), findsOneWidget);
      expect(find.text('Analysis not available yet'), findsNothing);
      expect(find.text('Analysis failed'), findsNothing);

      await tester.tap(find.text('View full summary'));
      await tester.pumpAndSettle();

      expect(find.byType(ActivityDetailScreen), findsOneWidget);
    },
  );
}
