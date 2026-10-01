import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/api_exception.dart';
import 'package:simple_activity_tracker/core/api/dto/live_dto.dart';
import 'package:simple_activity_tracker/core/auth/auth_state.dart';
import 'package:simple_activity_tracker/core/sync/live_sharing_store.dart';

import '../../fakes/fake_api_client.dart';

const _auth = AuthState(serverUrl: 'https://runner.example.com', token: 't');

class _SlowApi extends FakeApiClient {
  Future<void> Function()? beforeReply;

  @override
  Future<MySharesDto> putLiveSharing({
    required String baseUrl,
    required String token,
    required LiveSharingRequestDto request,
  }) async {
    await beforeReply?.call();
    return super.putLiveSharing(baseUrl: baseUrl, token: token, request: request);
  }
}

LiveSharingStore _store() {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform({});
  return LiveSharingStore(storage: const FlutterSecureStorage());
}

void main() {
  test('a queued change is sent once and the snapshot follows it', () async {
    final store = _store();
    final api = FakeApiClient();
    await store.setPending(
      const LiveSharingRequestDto(liveSharingPaused: false, liveViewerIds: {'u-ann'}),
    );
    expect((await store.snapshot()).liveViewerIds, {'u-ann'});

    await store.flush(api, _auth);
    await store.flush(api, _auth);
    expect(api.liveSharingCalls, hasLength(1));
    expect(await store.pending(), isNull);
    expect((await store.snapshot()).watchingCount, 1);
  });

  test('a network failure keeps the change queued', () async {
    final store = _store();
    final api = FakeApiClient()..liveFailure = const ApiNetworkException('offline');
    await store.setPending(
      const LiveSharingRequestDto(liveSharingPaused: true, liveViewerIds: {}),
    );
    await expectLater(store.flush(api, _auth), throwsA(isA<ApiNetworkException>()));
    expect(await store.pending(), isNotNull);
  });

  test('a rejected change is dropped: it could never succeed as-is', () async {
    final store = _store();
    final api = FakeApiClient()
      ..liveFailure = const ApiRejectedException('unknown user', statusCode: 400);
    await store.setPending(
      const LiveSharingRequestDto(liveSharingPaused: false, liveViewerIds: {'gone'}),
    );
    await expectLater(store.flush(api, _auth), throwsA(isA<ApiRejectedException>()));
    expect(await store.pending(), isNull);
  });

  test('a newer change made while one is in flight stays queued', () async {
    final store = _store();
    final api = _SlowApi();
    const first = LiveSharingRequestDto(liveSharingPaused: false, liveViewerIds: {'u-ann'});
    const second = LiveSharingRequestDto(liveSharingPaused: true, liveViewerIds: {'u-ann'});
    await store.setPending(first);
    api.beforeReply = () => store.setPending(second);

    await store.flush(api, _auth);
    expect(await store.pending(), second);
  });

  test('nobody is watching while paused', () {
    const snapshot = LiveSharingSnapshot(paused: true, users: {}, liveViewerIds: {'a', 'b'});
    expect(snapshot.watchingCount, 0);
  });
}
