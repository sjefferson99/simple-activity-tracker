import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/api_exception.dart';
import 'package:simple_activity_tracker/core/api/dto/live_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/server_info_dto.dart';
import 'package:simple_activity_tracker/core/auth/auth_service.dart';
import 'package:simple_activity_tracker/core/sync/live_sharing_store.dart';
import 'package:simple_activity_tracker/core/sync/live_upload_service.dart';
import 'package:simple_activity_tracker/domain/models/live_metrics.dart';
import 'package:simple_activity_tracker/domain/models/track_point.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';

import '../../fakes/fake_api_client.dart';
import '../../fakes/fake_connectivity_monitor.dart';

const _runId = '13013013-0130-0130-0130-130130130130';

TrackPoint _point(int i) => TrackPoint(
  latitude: 51.5 + i * 0.0001,
  longitude: -0.12,
  elevationMeters: 20,
  timestamp: DateTime.utc(2026, 1, 1, 7).add(Duration(seconds: i)),
  accuracyMeters: 5,
  speedMps: 3,
  hasSpeed: true,
);

class _Harness {
  final FakeApiClient api;
  final FakeConnectivityMonitor connectivity;
  final AuthService auth;
  final LiveSharingStore store;
  final LiveUploadService service;

  _Harness(this.api, this.connectivity, this.auth, this.store, this.service);

  /// Points the fake server holds for the run.
  int get stored => api.liveStoredPoints[_runId] ?? -1;

  void start({ActivityMode mode = ActivityMode.running}) => service.startRun(
    clientRunId: _runId,
    activityMode: mode,
    startedAt: DateTime.utc(2026, 1, 1, 7),
    splitPlan: SplitPlan.defaultPlan,
  );

  void addPoints(int from, int count) {
    for (var i = from; i < from + count; i++) {
      service.addPoint(_point(i));
    }
  }
}

Future<_Harness> _harness({
  bool signedIn = true,
  bool enabled = true,
  bool connected = true,
  int serverApiLevel = 2,
}) async {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform({});
  final api = FakeApiClient()
    ..getServerInfoHandler = ({required baseUrl, required token}) async =>
        ServerInfoDto(version: '1.4.0', apiLevel: serverApiLevel, minAppApiLevel: 0);
  final auth = AuthService(apiClient: api, storage: const FlutterSecureStorage());
  if (signedIn) {
    await auth.setServerUrl('https://runner.example.com');
    await auth.signIn(email: 'runner@example.com', password: 'x', deviceName: 'Pixel');
  }
  final connectivity = FakeConnectivityMonitor(connected: connected);
  final store = LiveSharingStore(storage: const FlutterSecureStorage());
  final service = LiveUploadService(
    apiClient: api,
    authService: auth,
    connectivity: connectivity,
    sharingStore: store,
    enabled: enabled,
    interval: null,
  );
  addTearDown(service.dispose);
  return _Harness(api, connectivity, auth, store, service);
}

/// Lets the fire-and-forget pass that startRun/pause/resume kick off finish.
Future<void> _settle(_Harness h) async {
  await h.service.sendNow();
  await h.service.sendNow();
}

void main() {
  test('uploads the run as it goes and only sends what is new', () async {
    final h = await _harness();
    h.start();
    await _settle(h);
    expect(h.api.livePutCalls, hasLength(1));
    expect(h.api.livePutCalls.single.toJson()['activity_type'], 'running');
    expect(h.service.status.phase, LiveUploadPhase.upToDate);

    h.addPoints(0, 5);
    h.service.updateMetrics(LiveMetrics.zero, currentSpeedMps: 3.2);
    await h.service.sendNow();
    expect(h.stored, 5);
    final first = h.api.livePointCalls.last;
    expect(first.fromIndex, 0);
    expect(first.points, hasLength(5));
    expect(first.toJson()['metrics']['current_speed_mps'], 3.2);

    h.addPoints(5, 3);
    await h.service.sendNow();
    expect(h.api.livePointCalls.last.fromIndex, 5);
    expect(h.api.livePointCalls.last.points, hasLength(3));
    expect(h.stored, 8);
  });

  test('nothing is sent while the setting is off; turning it on mid-run backfills', () async {
    final h = await _harness(enabled: false);
    h.start();
    h.addPoints(0, 40);
    await _settle(h);
    expect(h.api.liveCallLog, isEmpty);
    expect(h.service.status.phase, LiveUploadPhase.off);

    h.service.setEnabled(true);
    await _settle(h);
    expect(h.stored, 40);
    expect(h.api.livePointCalls.first.fromIndex, 0);

    h.service.setEnabled(false);
    h.addPoints(40, 10);
    await _settle(h);
    expect(h.stored, 40, reason: 'turning it off stops uploads at once');
    expect(h.service.status.phase, LiveUploadPhase.off);
  });

  test('offline: waits, keeps the points, sends them all when back', () async {
    final h = await _harness(connected: false);
    h.start();
    h.addPoints(0, 10);
    await _settle(h);
    expect(h.api.liveCallLog, isEmpty);
    expect(h.service.status.phase, LiveUploadPhase.waiting);

    h.connectivity.goOnline();
    await h.service.sendNow();
    expect(h.stored, 10);
  });

  test('a network failure mid-run is retried from the same index', () async {
    final h = await _harness();
    h.start();
    await _settle(h);
    h.addPoints(0, 4);
    h.api.liveFailure = const ApiNetworkException('no signal');
    await h.service.sendNow();
    expect(h.service.status.phase, LiveUploadPhase.waiting);

    h.api.liveFailure = null;
    h.addPoints(4, 2);
    await h.service.sendNow();
    expect(h.stored, 6);
    expect(h.api.livePointCalls.last.fromIndex, 0);
  });

  test('a server older than live tracking is never sent anything', () async {
    final h = await _harness(serverApiLevel: 1);
    h.start();
    h.addPoints(0, 5);
    await _settle(h);
    expect(h.api.liveCallLog, isEmpty);
    expect(h.service.status.phase, LiveUploadPhase.unavailable);
  });

  test('signed out: does nothing', () async {
    final h = await _harness(signedIn: false);
    h.start();
    h.addPoints(0, 5);
    await _settle(h);
    expect(h.api.liveCallLog, isEmpty);
    expect(h.service.status.phase, LiveUploadPhase.unavailable);
  });

  test('a sharing change queued offline reaches the server before any point', () async {
    final h = await _harness(connected: false);
    await h.store.setPending(
      const LiveSharingRequestDto(liveSharingPaused: true, liveViewerIds: {'u-ann'}),
    );
    h.start();
    h.addPoints(0, 3);
    await _settle(h);

    h.connectivity.goOnline();
    await h.service.sendNow();
    expect(h.api.liveCallLog.first, 'putLiveSharing');
    expect(h.api.liveCallLog.indexOf('putLiveSharing'), lessThan(h.api.liveCallLog.indexOf('postLivePoints')));
    expect(h.api.liveSharingCalls.single.liveSharingPaused, isTrue);
    expect(await h.store.pending(), isNull);
  });

  test('if the queued sharing change fails, no points go either', () async {
    final h = await _harness();
    await h.store.setPending(
      const LiveSharingRequestDto(liveSharingPaused: true, liveViewerIds: {}),
    );
    h.api.liveFailure = const ApiTimeoutException('slow');
    h.start();
    h.addPoints(0, 3);
    await _settle(h);
    expect(h.api.liveCallLog, everyElement('putLiveSharing'));
    expect(await h.store.pending(), isNotNull);
  });

  test('pause and resume send the state and start a new segment', () async {
    final h = await _harness();
    h.start();
    h.addPoints(0, 2);
    await _settle(h);

    h.service.pause();
    await _settle(h);
    expect(h.api.livePointCalls.last.state, 'paused');
    expect(h.api.liveStates[_runId], 'paused');

    h.service.resume();
    h.addPoints(2, 2);
    await _settle(h);
    final last = h.api.livePointCalls.last.toJson();
    expect(last['state'], 'active');
    expect([for (final p in last['points'] as List) p['segment']], everyElement(1));
  });

  test('finishing sends the rest and the finished state, retrying until it lands', () async {
    final h = await _harness();
    h.start();
    h.addPoints(0, 3);
    await _settle(h);

    h.addPoints(3, 2);
    h.api.liveFailure = const ApiNetworkException('no signal');
    await h.service.finishRun(LiveMetrics.zero);
    expect(h.api.liveStates[_runId], isNot('finished'));

    h.api.liveFailure = null;
    await h.service.sendNow();
    expect(h.stored, 5);
    expect(h.api.liveStates[_runId], 'finished');

    // Points after the finish aren't taken.
    h.addPoints(5, 1);
    await h.service.sendNow();
    expect(h.stored, 5);
    expect(h.api.liveStates[_runId], 'finished');
  });

  test('once the activity is saved (410) it stops uploading that run', () async {
    final h = await _harness();
    h.start();
    await _settle(h);
    h.api.closedLiveSessions.add(_runId);
    h.addPoints(0, 2);
    await h.service.sendNow();
    expect(h.service.status.phase, LiveUploadPhase.closed);

    final calls = h.api.liveCallLog.length;
    h.addPoints(2, 2);
    await h.service.sendNow();
    expect(h.api.liveCallLog.length, calls);
  });

  test('a session the server lost (404) is created again and refilled', () async {
    final h = await _harness();
    h.start();
    h.addPoints(0, 3);
    await _settle(h);
    expect(h.stored, 3);

    h.api.liveStoredPoints.remove(_runId); // deleted on the web, or purged
    h.addPoints(3, 1);
    await h.service.sendNow(); // 404 -> marks the session for re-creation
    await h.service.sendNow();
    expect(h.api.livePutCalls, hasLength(2));
    expect(h.stored, 4);
  });

  test('the server saying it has fewer points rewinds to resend them', () async {
    final h = await _harness();
    h.start();
    h.addPoints(0, 6);
    await _settle(h);
    expect(h.stored, 6);

    h.api.liveStoredPoints[_runId] = 2; // e.g. restored from a backup
    h.addPoints(6, 2);
    await h.service.sendNow();
    expect(h.stored, 8);
  });

  test('long backlogs go in batches of at most 2000 points', () async {
    final h = await _harness(enabled: false);
    h.start();
    h.addPoints(0, 4500);
    h.service.setEnabled(true);
    await _settle(h);
    expect(h.stored, 4500);
    final sizes = [for (final call in h.api.livePointCalls) call.points.length];
    expect(sizes.where((n) => n > 0), [2000, 2000, 500]);
  });

  test('a cycling run sends no split plan', () async {
    final h = await _harness();
    h.start(mode: ActivityMode.cycling);
    await _settle(h);
    expect(h.api.livePutCalls.single.toJson().containsKey('split_plan'), isFalse);
  });

  test('discarding a run deletes its live session', () async {
    final h = await _harness();
    h.start();
    h.addPoints(0, 2);
    await _settle(h);
    await h.service.discardRun(_runId);
    expect(h.api.liveDeleteCalls, [_runId]);
    expect(h.service.status.phase, LiveUploadPhase.idle);
  });

  test('discarding on an older server sends nothing', () async {
    final h = await _harness(serverApiLevel: 1);
    await h.service.discardRun(_runId);
    expect(h.api.liveCallLog, isEmpty);
  });

  test("over the server's point cap (413) it stops instead of retrying forever", () async {
    final h = await _harness();
    h.start();
    await _settle(h);
    h.api.liveFailure = const ApiRejectedException('too many points', statusCode: 413);
    h.addPoints(0, 2);
    await h.service.sendNow();
    expect(h.service.status.phase, LiveUploadPhase.unavailable);
  });
}
