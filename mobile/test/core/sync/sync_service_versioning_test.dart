import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/api_exception.dart';
import 'package:simple_activity_tracker/core/api/dto/server_info_dto.dart';
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

/// SyncService's side of docs/VERSIONING.md §3: shape uploads to the
/// server's level, pause when out of range, and re-queue what an older
/// server rejected once it's been updated.

RunRecord _record({
  String clientRunId = 'run-1',
  SyncStatus syncStatus = const SyncStatusPending(),
}) {
  final started = DateTime.utc(2026, 1, 1, 7);
  return RunRecord(
    clientRunId: clientRunId,
    gpxPath: '/documents/runs/run_$clientRunId.gpx',
    activityMode: ActivityMode.walking,
    summary: RunSummary(
      clientRunId: clientRunId,
      startedAt: started,
      endedAt: started.add(const Duration(minutes: 30)),
      activityMode: ActivityMode.walking,
      movingSeconds: 1800,
      distanceMeters: 3000,
      avgSpeedMps: 1.67,
      splits: const [],
      sourcePlatform: 'android',
      sourceAppVersion: '1.3.0+60',
    ),
    syncStatus: syncStatus,
  );
}

Future<SyncService> _service(FakeApiClient api, FakeRunStore store) async {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform({});
  final auth = AuthService(apiClient: api, storage: const FlutterSecureStorage());
  await auth.setServerUrl('https://runner.example.com');
  await auth.signIn(email: 'runner@example.com', password: 'x', deviceName: 'Pixel');
  final connectivity = FakeConnectivityMonitor();
  final service = SyncService(
    apiClient: api,
    runStore: store,
    authService: auth,
    connectivity: connectivity,
  );
  addTearDown(service.dispose);
  addTearDown(connectivity.dispose);
  return service;
}

Future<ServerInfoDto> Function({required String baseUrl, required String token}) _serverAt(
  int apiLevel, {
  int minAppApiLevel = 0,
}) =>
    ({required baseUrl, required token}) async =>
        ServerInfoDto(version: 'x', apiLevel: apiLevel, minAppApiLevel: minAppApiLevel);

void main() {
  test('uploads are shaped for the level the server reports', () async {
    final api = FakeApiClient()..getServerInfoHandler = _serverAt(kAppApiLevel);
    final service = await _service(api, FakeRunStore()..seed(_record()));

    service.runFinished();
    await pumpEventQueue();

    expect(api.uploadApiLevels, [kAppApiLevel]);
  });

  test('a legacy server gets level 0 uploads', () async {
    final api = FakeApiClient()
      ..getServerInfoHandler = ({required baseUrl, required token}) async =>
          ServerInfoDto.legacy;
    final service = await _service(api, FakeRunStore()..seed(_record()));

    service.runFinished();
    await pumpEventQueue();

    expect(api.uploadApiLevels, [0]);
  });

  test('server info is fetched once per pass, not per record', () async {
    final api = FakeApiClient();
    final store = FakeRunStore()
      ..seed(_record(clientRunId: 'a'))
      ..seed(_record(clientRunId: 'b'));
    final service = await _service(api, store);

    service.runFinished();
    await pumpEventQueue();

    expect(api.uploadCallCount, 2);
    expect(api.getServerInfoCallCount, 1);
  });

  test('an app too old for the server pauses uploads, leaving them pending', () async {
    final api = FakeApiClient()
      ..getServerInfoHandler = _serverAt(kAppApiLevel + 3, minAppApiLevel: kAppApiLevel + 1);
    final store = FakeRunStore()..seed(_record());
    final service = await _service(api, store);

    service.runFinished();
    await pumpEventQueue();

    expect(api.uploadCallCount, 0);
    expect((await store.listAll()).single.syncStatus, isA<SyncStatusPending>());
  });

  test('an unreachable server marks due records failed(retryable)', () async {
    final api = FakeApiClient()
      ..getServerInfoHandler = ({required baseUrl, required token}) async =>
          throw const ApiNetworkException('offline');
    final store = FakeRunStore()..seed(_record());
    final service = await _service(api, store);

    service.runFinished();
    await pumpEventQueue();

    expect(api.uploadCallCount, 0);
    final status = (await store.listAll()).single.syncStatus as SyncStatusFailed;
    expect(status.retryable, isTrue);
    expect(status.error, 'offline');
  });

  test('a rejection by an older server says so and records its level', () async {
    final api = FakeApiClient()
      ..getServerInfoHandler = (({required baseUrl, required token}) async =>
          ServerInfoDto.legacy)
      ..uploadRunHandler = ({
        required baseUrl,
        required token,
        required summary,
        required gpxFile,
      }) async => throw const ApiRejectedException('unknown activity_type', statusCode: 400);
    final store = FakeRunStore()..seed(_record());
    final service = await _service(api, store);

    service.runFinished();
    await pumpEventQueue();

    final status = (await store.listAll()).single.syncStatus as SyncStatusFailed;
    expect(status.retryable, isFalse);
    expect(status.rejectedAtServerApiLevel, 0);
    expect(status.error, contains('older than this app'));
  });

  test('a rejected record is re-queued once the server is updated', () async {
    final api = FakeApiClient()..getServerInfoHandler = _serverAt(1);
    final store = FakeRunStore()
      ..seed(
        _record(
          syncStatus: const SyncStatusFailed(
            error: 'rejected',
            attempts: 1,
            retryable: false,
            rejectedAtServerApiLevel: 0,
          ),
        ),
      );
    final service = await _service(api, store);

    service.onAppResumed();
    await pumpEventQueue();

    expect(api.uploadCallCount, 1);
    expect((await store.listAll()).single.syncStatus, isA<SyncStatusUploaded>());
  });

  test('a rejection at the current level is not retried automatically', () async {
    final api = FakeApiClient()..getServerInfoHandler = _serverAt(1);
    final store = FakeRunStore()
      ..seed(
        _record(
          syncStatus: const SyncStatusFailed(
            error: 'rejected',
            attempts: 1,
            retryable: false,
            rejectedAtServerApiLevel: 1,
          ),
        ),
      );
    final service = await _service(api, store);

    service.onAppResumed();
    await pumpEventQueue();

    expect(api.uploadCallCount, 0);
  });

  test('rejectedAtServerApiLevel survives the sidecar round trip', () {
    const status = SyncStatusFailed(
      error: 'e',
      attempts: 2,
      retryable: false,
      rejectedAtServerApiLevel: 0,
    );
    final restored = SyncStatus.fromJson(status.toJson()) as SyncStatusFailed;
    expect(restored.rejectedAtServerApiLevel, 0);

    // Sidecars written before #141 have no such key.
    final legacy = SyncStatus.fromJson({
      'type': 'failed',
      'error': 'e',
      'attempts': 1,
      'retryable': false,
    }) as SyncStatusFailed;
    expect(legacy.rejectedAtServerApiLevel, isNull);
  });
}
