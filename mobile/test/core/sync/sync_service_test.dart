import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/api_exception.dart';
import 'package:simple_activity_tracker/core/api/dto/analysis_dto.dart';
import 'package:simple_activity_tracker/core/auth/auth_service.dart';
import 'package:simple_activity_tracker/core/sync/sync_service.dart';
import 'package:simple_activity_tracker/core/version/api_compat.dart';
import 'package:simple_activity_tracker/domain/models/run_record.dart';
import 'package:simple_activity_tracker/domain/models/run_summary.dart';
import 'package:simple_activity_tracker/domain/models/sync_status.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';

import '../../fakes/fake_api_client.dart';
import '../../fakes/fake_connectivity_monitor.dart';
import '../../fakes/fake_run_store.dart';

RunRecord _record({
  String clientRunId = 'run-1',
  DateTime? startedAt,
  SyncStatus syncStatus = const SyncStatusPending(),
}) {
  final started = startedAt ?? DateTime.utc(2026, 1, 1, 7, 0, 0);
  return RunRecord(
    clientRunId: clientRunId,
    gpxPath: '/documents/runs/run_$clientRunId.gpx',
    activityMode: ActivityMode.running,
    summary: RunSummary(
      clientRunId: clientRunId,
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
    syncStatus: syncStatus,
  );
}

Future<AuthService> _signedInAuthService(FakeApiClient api) async {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform({});
  final service = AuthService(
    apiClient: api,
    storage: const FlutterSecureStorage(),
  );
  await service.setServerUrl('https://runner.example.com');
  await service.signIn(
    email: 'runner@example.com',
    password: 'x',
    deviceName: 'Pixel',
  );
  return service;
}

Future<AuthService> _signedOutAuthService() async {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform({});
  return AuthService(
    apiClient: FakeApiClient(),
    storage: const FlutterSecureStorage(),
  );
}

void main() {
  test('runFinished uploads a pending record and fetches analysis', () async {
    final api = FakeApiClient()
      ..getAnalysisHandler =
          ({required baseUrl, required token, required serverRunId}) async =>
              const AnalysisDto(
                status: 'done',
                result: {'distance_meters': 5012.0},
              );
    final store = FakeRunStore()..seed(_record());
    final auth = await _signedInAuthService(api);
    final connectivity = FakeConnectivityMonitor();
    final service = SyncService(
      apiClient: api,
      runStore: store,
      authService: auth,
      connectivity: connectivity,
    );
    addTearDown(service.dispose);
    addTearDown(connectivity.dispose);

    service.runFinished();
    await pumpEventQueue();

    final records = await store.listAll();
    expect(records.single.syncStatus, isA<SyncStatusUploaded>());
    expect(records.single.analysisResult?['distance_meters'], 5012.0);
    expect(api.uploadCallCount, 1);
  });

  test(
    'a retryable failure (network) marks the record failed(retryable: true)',
    () async {
      final api = FakeApiClient()
        ..uploadRunHandler = ({
          required baseUrl,
          required token,
          required summary,
          required gpxFile,
        }) async => throw const ApiNetworkException('offline');
      final store = FakeRunStore()..seed(_record());
      final auth = await _signedInAuthService(api);
      final connectivity = FakeConnectivityMonitor();
      final service = SyncService(
        apiClient: api,
        runStore: store,
        authService: auth,
        connectivity: connectivity,
      );
      addTearDown(service.dispose);
      addTearDown(connectivity.dispose);

      service.runFinished();
      await pumpEventQueue();

      final status =
          (await store.listAll()).single.syncStatus as SyncStatusFailed;
      expect(status.retryable, isTrue);
      expect(status.attempts, 1);
    },
  );

  test('a permanent rejection (413) is not retried automatically', () async {
    final api = FakeApiClient()
      ..uploadRunHandler = ({
        required baseUrl,
        required token,
        required summary,
        required gpxFile,
      }) async => throw const ApiRejectedException('too big', statusCode: 413);
    final store = FakeRunStore()..seed(_record());
    final auth = await _signedInAuthService(api);
    final connectivity = FakeConnectivityMonitor();
    final service = SyncService(
      apiClient: api,
      runStore: store,
      authService: auth,
      connectivity: connectivity,
    );
    addTearDown(service.dispose);
    addTearDown(connectivity.dispose);

    service.runFinished();
    await pumpEventQueue();
    expect(api.uploadCallCount, 1);

    // Another automatic trigger must not retry a non-retryable failure.
    service.onAppResumed();
    await pumpEventQueue();
    expect(api.uploadCallCount, 1);
  });

  test(
    'retryNow retries a permanently-failed record on explicit user action',
    () async {
      var shouldFail = true;
      final api = FakeApiClient()
        ..uploadRunHandler =
            ({
              required baseUrl,
              required token,
              required summary,
              required gpxFile,
            }) async {
              if (shouldFail) {
                throw const ApiRejectedException('too big', statusCode: 413);
              }
              return FakeApiClient().uploadRun(
                baseUrl: baseUrl,
                token: token,
                summary: summary,
                gpxFile: gpxFile,
                serverApiLevel: kAppApiLevel,
              );
            };
      final store = FakeRunStore()..seed(_record());
      final auth = await _signedInAuthService(api);
      final connectivity = FakeConnectivityMonitor();
      final service = SyncService(
        apiClient: api,
        runStore: store,
        authService: auth,
        connectivity: connectivity,
      );
      addTearDown(service.dispose);
      addTearDown(connectivity.dispose);

      service.runFinished();
      await pumpEventQueue();
      expect(
        (await store.listAll()).single.syncStatus,
        isA<SyncStatusFailed>(),
      );

      shouldFail = false;
      await service.retryNow();

      expect(
        (await store.listAll()).single.syncStatus,
        isA<SyncStatusUploaded>(),
      );
    },
  );

  test(
    'a 401 marks the auth service signed-out and keeps the record pending',
    () async {
      final api = FakeApiClient()
        ..uploadRunHandler = ({
          required baseUrl,
          required token,
          required summary,
          required gpxFile,
        }) async => throw const ApiUnauthorizedException('token revoked');
      final store = FakeRunStore()..seed(_record());
      final auth = await _signedInAuthService(api);
      final connectivity = FakeConnectivityMonitor();
      final service = SyncService(
        apiClient: api,
        runStore: store,
        authService: auth,
        connectivity: connectivity,
      );
      addTearDown(service.dispose);
      addTearDown(connectivity.dispose);

      service.runFinished();
      await pumpEventQueue();

      expect(
        (await store.listAll()).single.syncStatus,
        isA<SyncStatusPending>(),
      );
      expect((await auth.currentState()).isSignedIn, isFalse);
      expect(
        (await auth.currentState()).serverUrl,
        'https://runner.example.com',
      );
    },
  );

  test(
    'not signed in: the queue stays pending and nothing is uploaded',
    () async {
      final api = FakeApiClient();
      final store = FakeRunStore()..seed(_record());
      final auth = await _signedOutAuthService();
      final connectivity = FakeConnectivityMonitor();
      final service = SyncService(
        apiClient: api,
        runStore: store,
        authService: auth,
        connectivity: connectivity,
      );
      addTearDown(service.dispose);
      addTearDown(connectivity.dispose);

      service.runFinished();
      await pumpEventQueue();

      expect(api.uploadCallCount, 0);
      expect(
        (await store.listAll()).single.syncStatus,
        isA<SyncStatusPending>(),
      );
    },
  );

  test(
    'offline: the queue is left untouched until connectivity returns',
    () async {
      final api = FakeApiClient();
      final store = FakeRunStore()..seed(_record());
      final auth = await _signedInAuthService(api);
      final connectivity = FakeConnectivityMonitor(connected: false);
      final service = SyncService(
        apiClient: api,
        runStore: store,
        authService: auth,
        connectivity: connectivity,
      );
      addTearDown(service.dispose);
      addTearDown(connectivity.dispose);

      service.runFinished();
      await pumpEventQueue();
      expect(api.uploadCallCount, 0);

      connectivity.goOnline();
      await pumpEventQueue();
      expect(api.uploadCallCount, 1);
    },
  );

  test('backoff: a retryable failure is not retried again before its backoff window', () async {
    var now = DateTime.utc(2026, 1, 1, 8, 0, 0);
    final api = FakeApiClient()
      ..uploadRunHandler = ({
        required baseUrl,
        required token,
        required summary,
        required gpxFile,
      }) async => throw const ApiNetworkException('offline');
    final store = FakeRunStore()..seed(_record());
    final auth = await _signedInAuthService(api);
    final connectivity = FakeConnectivityMonitor();
    final service = SyncService(
      apiClient: api,
      runStore: store,
      authService: auth,
      connectivity: connectivity,
      now: () => now,
    );
    addTearDown(service.dispose);
    addTearDown(connectivity.dispose);

    service.runFinished();
    await pumpEventQueue();
    expect(api.uploadCallCount, 1);

    // Immediately re-triggering (well within the first 30s backoff step)
    // must not attempt again.
    now = now.add(const Duration(seconds: 5));
    service.onAppResumed();
    await pumpEventQueue();
    expect(api.uploadCallCount, 1);

    // Once the backoff window has elapsed, the same trigger retries.
    now = now.add(const Duration(seconds: 30));
    service.onAppResumed();
    await pumpEventQueue();
    expect(api.uploadCallCount, 2);
  });

  test(
    'a permanently-rejected record does not block later queued records',
    () async {
      // Regression: one activity with no GPS data at all (e.g. an indoor
      // run) gets rejected by the server with a 400. That must not jam
      // every other queued activity behind it forever.
      final api = FakeApiClient()
        ..uploadRunHandler = ({
          required baseUrl,
          required token,
          required summary,
          required gpxFile,
        }) async {
          if (summary.clientRunId == 'broken') {
            throw const ApiRejectedException('no GPS data', statusCode: 400);
          }
          return FakeApiClient().uploadRun(
            baseUrl: baseUrl,
            token: token,
            summary: summary,
            gpxFile: gpxFile,
            serverApiLevel: kAppApiLevel,
          );
        };
      final store = FakeRunStore()
        ..seed(
          _record(clientRunId: 'broken', startedAt: DateTime.utc(2026, 1, 1)),
        )
        ..seed(
          _record(clientRunId: 'healthy', startedAt: DateTime.utc(2026, 1, 2)),
        );
      final auth = await _signedInAuthService(api);
      final connectivity = FakeConnectivityMonitor();
      final service = SyncService(
        apiClient: api,
        runStore: store,
        authService: auth,
        connectivity: connectivity,
      );
      addTearDown(service.dispose);
      addTearDown(connectivity.dispose);

      service.runFinished();
      await pumpEventQueue();

      final records = {for (final r in await store.listAll()) r.clientRunId: r};
      expect(records['broken']!.syncStatus, isA<SyncStatusFailed>());
      expect(
        (records['broken']!.syncStatus as SyncStatusFailed).retryable,
        isFalse,
      );
      expect(records['healthy']!.syncStatus, isA<SyncStatusUploaded>());
    },
  );

  test('oldest-first: two pending records upload in startedAt order', () async {
    final api = FakeApiClient();
    final store = FakeRunStore()
      ..seed(_record(clientRunId: 'later', startedAt: DateTime.utc(2026, 1, 2)))
      ..seed(
        _record(clientRunId: 'earlier', startedAt: DateTime.utc(2026, 1, 1)),
      );
    final auth = await _signedInAuthService(api);
    final connectivity = FakeConnectivityMonitor();
    final service = SyncService(
      apiClient: api,
      runStore: store,
      authService: auth,
      connectivity: connectivity,
    );
    addTearDown(service.dispose);
    addTearDown(connectivity.dispose);

    service.runFinished();
    await pumpEventQueue();

    expect(api.uploadCalls.map((s) => s.clientRunId).toList(), [
      'earlier',
      'later',
    ]);
  });

  group('periodic retry (found via on-device testing: a same-medium '
      'network switch never fires onConnected at all)', () {
    test(
      'a periodic tick retries a failed record once its backoff window has '
      'passed, with no other trigger',
      () async {
        var shouldFail = true;
        final api = FakeApiClient()
          ..uploadRunHandler =
              ({
                required baseUrl,
                required token,
                required summary,
                required gpxFile,
              }) async {
                if (shouldFail) {
                  throw const ApiNetworkException('offline');
                }
                return FakeApiClient().uploadRun(
                  baseUrl: baseUrl,
                  token: token,
                  summary: summary,
                  gpxFile: gpxFile,
                  serverApiLevel: kAppApiLevel,
                );
              };
        final store = FakeRunStore()..seed(_record());
        final auth = await _signedInAuthService(api);
        final connectivity = FakeConnectivityMonitor();
        // A controllable clock: the first failure's backoff window
        // (_backoffSchedule[0] = 30s) is "passed" the moment the test
        // advances it, without a real 30-second wait.
        var clock = DateTime.utc(2026, 1, 1);
        final service = SyncService(
          apiClient: api,
          runStore: store,
          authService: auth,
          connectivity: connectivity,
          now: () => clock,
          periodicRetryInterval: const Duration(milliseconds: 20),
        );
        addTearDown(service.dispose);
        addTearDown(connectivity.dispose);

        service.runFinished();
        await pumpEventQueue();
        expect(api.uploadCallCount, 1);
        expect(
          (await store.listAll()).single.syncStatus,
          isA<SyncStatusFailed>(),
        );

        // Advance past the backoff window and let network access succeed,
        // then wait only for the periodic timer to tick — no connectivity
        // event, no app-resume, no retryNow. Without the periodic timer,
        // this record would never be retried again in this scenario (a
        // same-medium network switch that never fires `onConnected`).
        clock = clock.add(const Duration(seconds: 31));
        shouldFail = false;
        await Future<void>.delayed(const Duration(milliseconds: 100));

        expect(api.uploadCallCount, greaterThan(1));
        expect(
          (await store.listAll()).single.syncStatus,
          isA<SyncStatusUploaded>(),
        );
      },
    );
  });

  group('analysis retry (issue #97/#101 Slice C)', () {
    test(
      // Regression: found via real on-device testing before this shipped —
      // updateAnalysisResult() wrote the new analysis to disk, but nothing
      // told run_insights.dart's _runRecordProvider to re-fetch (it only
      // reacts to statusChanges, which _setStatus alone used to emit onto),
      // so the summary screen's "View full summary" link never appeared
      // until the app was relaunched. This must emit on statusChanges too.
      'emits on statusChanges once analysis completes, even though the '
      'sync status itself (already uploaded) does not change',
      () async {
        final api = FakeApiClient()
          ..getAnalysisHandler = ({required baseUrl, required token, required serverRunId}) async =>
              const AnalysisDto(status: 'done', result: {'distance_meters': 1234.0});
        final store = FakeRunStore()..seed(_record());
        final auth = await _signedInAuthService(api);
        final connectivity = FakeConnectivityMonitor();
        final service = SyncService(
          apiClient: api,
          runStore: store,
          authService: auth,
          connectivity: connectivity,
          delay: (_) async {},
        );
        addTearDown(service.dispose);
        addTearDown(connectivity.dispose);

        final events = <String>[];
        final subscription = service.statusChanges.listen(
          (event) => events.add(event.$1),
        );
        addTearDown(subscription.cancel);

        service.runFinished();
        await pumpEventQueue();

        // At least two events for this run: the upload's own status change
        // to `uploaded`, and a second one once analysis lands.
        expect(events.where((id) => id == 'run-1').length, greaterThanOrEqualTo(2));
      },
    );

    test(
      'retries a still-pending analysis and stores the result once done',
      () async {
        var callCount = 0;
        final api = FakeApiClient()
          ..getAnalysisHandler = ({required baseUrl, required token, required serverRunId}) async {
            callCount++;
            if (callCount < 3) {
              return const AnalysisDto(status: 'pending', result: null);
            }
            return const AnalysisDto(status: 'done', result: {'distance_meters': 1234.0});
          };
        final store = FakeRunStore()..seed(_record());
        final auth = await _signedInAuthService(api);
        final connectivity = FakeConnectivityMonitor();
        final service = SyncService(
          apiClient: api,
          runStore: store,
          authService: auth,
          connectivity: connectivity,
          delay: (_) async {},
        );
        addTearDown(service.dispose);
        addTearDown(connectivity.dispose);

        service.runFinished();
        await pumpEventQueue();

        expect(callCount, 3);
        final record = (await store.listAll()).single;
        expect(record.analysisResult?['distance_meters'], 1234.0);
        expect(record.analysisFailed, isFalse);
      },
    );

    test(
      'marks analysis failed once every retry is exhausted while still pending',
      () async {
        final api = FakeApiClient()
          ..getAnalysisHandler = ({required baseUrl, required token, required serverRunId}) async =>
              const AnalysisDto(status: 'pending', result: null);
        final store = FakeRunStore()..seed(_record());
        final auth = await _signedInAuthService(api);
        final connectivity = FakeConnectivityMonitor();
        final service = SyncService(
          apiClient: api,
          runStore: store,
          authService: auth,
          connectivity: connectivity,
          delay: (_) async {},
        );
        addTearDown(service.dispose);
        addTearDown(connectivity.dispose);

        service.runFinished();
        await pumpEventQueue();

        final record = (await store.listAll()).single;
        expect(record.analysisResult, isNull);
        expect(record.analysisFailed, isTrue);
        // 1 initial attempt + one per configured retry delay.
        expect(api.getAnalysisCallCount, greaterThan(1));
      },
    );

    test('marks analysis failed immediately when the server reports failed', () async {
      final api = FakeApiClient()
        ..getAnalysisHandler = ({required baseUrl, required token, required serverRunId}) async =>
            const AnalysisDto(status: 'failed', result: null);
      final store = FakeRunStore()..seed(_record());
      final auth = await _signedInAuthService(api);
      final connectivity = FakeConnectivityMonitor();
      final service = SyncService(
        apiClient: api,
        runStore: store,
        authService: auth,
        connectivity: connectivity,
        delay: (_) async {},
      );
      addTearDown(service.dispose);
      addTearDown(connectivity.dispose);

      service.runFinished();
      await pumpEventQueue();

      expect(api.getAnalysisCallCount, 1);
      final record = (await store.listAll()).single;
      expect(record.analysisFailed, isTrue);
    });

    test(
      'a transient network error while polling is retried, not given up on immediately',
      () async {
        var callCount = 0;
        final api = FakeApiClient()
          ..getAnalysisHandler = ({required baseUrl, required token, required serverRunId}) async {
            callCount++;
            if (callCount == 1) throw const ApiNetworkException('offline');
            return const AnalysisDto(status: 'done', result: {'distance_meters': 42.0});
          };
        final store = FakeRunStore()..seed(_record());
        final auth = await _signedInAuthService(api);
        final connectivity = FakeConnectivityMonitor();
        final service = SyncService(
          apiClient: api,
          runStore: store,
          authService: auth,
          connectivity: connectivity,
          delay: (_) async {},
        );
        addTearDown(service.dispose);
        addTearDown(connectivity.dispose);

        service.runFinished();
        await pumpEventQueue();

        expect(callCount, 2);
        final record = (await store.listAll()).single;
        expect(record.analysisResult?['distance_meters'], 42.0);
        expect(record.analysisFailed, isFalse);
      },
    );
  });
}
