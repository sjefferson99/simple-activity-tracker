import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/api_client.dart';
import 'package:simple_activity_tracker/core/api/api_exception.dart';
import 'package:simple_activity_tracker/core/api/dto/live_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/server_info_dto.dart';
import 'package:simple_activity_tracker/core/auth/auth_state.dart';
import 'package:simple_activity_tracker/core/auth/auth_state_controller.dart';
import 'package:simple_activity_tracker/core/sync/live_sharing_store.dart';
import 'package:simple_activity_tracker/core/sync/live_upload_settings.dart';
import 'package:simple_activity_tracker/features/settings/live_tracking_section.dart';

import '../../fakes/fake_api_client.dart';

class _SignedInAuthController extends AuthStateController {
  @override
  Future<AuthState> build() async =>
      const AuthState(serverUrl: 'https://runner.example.com', token: 't', email: 'a@b.c');
}

class _SignedOutAuthController extends AuthStateController {
  @override
  Future<AuthState> build() async => const AuthState();
}

class _Setup {
  final FakeApiClient api;
  final LiveSharingStore store;

  _Setup(this.api, this.store);
}

Future<_Setup> _pump(
  WidgetTester tester, {
  bool signedIn = true,
  int serverApiLevel = 2,
  FakeApiClient? api,
  Map<String, String> storage = const {},
}) async {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform({...storage});
  final fakeApi = (api ?? FakeApiClient())
    ..getServerInfoHandler = ({required baseUrl, required token}) async =>
        ServerInfoDto(version: '1.4.0', apiLevel: serverApiLevel, minAppApiLevel: 0);
  final store = LiveSharingStore(storage: const FlutterSecureStorage());
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        apiClientProvider.overrideWithValue(fakeApi),
        liveSharingStoreProvider.overrideWithValue(store),
        authStateControllerProvider.overrideWith(
          signedIn ? _SignedInAuthController.new : _SignedOutAuthController.new,
        ),
      ],
      child: const MaterialApp(
        home: Scaffold(body: SingleChildScrollView(child: LiveTrackingSection())),
      ),
    ),
  );
  await tester.pumpAndSettle();
  return _Setup(fakeApi, store);
}

Finder _checkbox(String name) =>
    find.descendant(of: find.widgetWithText(CheckboxListTile, name), matching: find.byType(Checkbox));

void main() {
  testWidgets('lists every user; ticking one shares live with them at once', (tester) async {
    final setup = await _pump(tester);
    expect(find.text('Live upload'), findsOneWidget);
    expect(find.text('Ann'), findsOneWidget);
    expect(find.text('Bob'), findsOneWidget);
    expect(tester.widget<Checkbox>(_checkbox('Ann')).value, isFalse);

    await tester.tap(find.text('Ann'));
    await tester.pumpAndSettle();
    expect(setup.api.liveSharingCalls.single.liveViewerIds, {'u-ann'});
    expect(tester.widget<Checkbox>(_checkbox('Ann')).value, isTrue);
    expect(await setup.store.pending(), isNull);
    expect(find.textContaining('Saved on this phone'), findsNothing);
  });

  testWidgets("Don't live share keeps the list", (tester) async {
    final api = FakeApiClient()
      ..myShares = const MySharesDto(
        liveSharingPaused: false,
        shares: [
          ShareDto(viewerId: 'u-bob', displayName: 'Bob', canViewLive: true, canViewHistory: true),
        ],
      );
    final setup = await _pump(tester, api: api);
    expect(tester.widget<Checkbox>(_checkbox('Bob')).value, isTrue);

    await tester.tap(find.text("Don't live share"));
    await tester.pumpAndSettle();
    final sent = setup.api.liveSharingCalls.single;
    expect(sent.liveSharingPaused, isTrue);
    expect(sent.liveViewerIds, {'u-bob'});
    expect(find.textContaining('Nobody can watch you live'), findsOneWidget);
  });

  testWidgets('offline: shows the last known setting and queues changes', (tester) async {
    final api = FakeApiClient()..liveFailure = const ApiNetworkException('offline');
    final setup = await _pump(
      tester,
      api: api,
      storage: {
        'live_sharing_cache':
            '{"paused":false,"users":{"u-ann":"Ann"},"live_viewer_ids":[]}',
      },
    );
    expect(find.text('Offline: showing your last known settings.'), findsOneWidget);
    expect(find.text('Ann'), findsOneWidget);

    await tester.tap(find.text('Ann'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Saved on this phone'), findsOneWidget);
    expect((await setup.store.pending())?.liveViewerIds, {'u-ann'});
    expect(tester.widget<Checkbox>(_checkbox('Ann')).value, isTrue);
  });

  testWidgets('a rejected change shows inline and keeps the controls', (tester) async {
    final setup = await _pump(tester);
    setup.api.liveFailure = const ApiRejectedException('That user is unavailable', statusCode: 400);
    await tester.tap(find.text('Ann'));
    await tester.pumpAndSettle();
    expect(find.text('That user is unavailable'), findsOneWidget);
    expect(find.text('Bob'), findsOneWidget);
  });

  testWidgets('with Live upload off, sharing is disabled and says why', (tester) async {
    await _pump(tester, storage: {'live_upload_enabled': 'false'});
    expect(find.text('Live sharing needs Live upload on.'), findsOneWidget);
    expect(tester.widget<Checkbox>(_checkbox('Ann')).onChanged, isNull);
  });

  testWidgets('the Live upload switch is saved', (tester) async {
    await _pump(tester);
    await tester.tap(find.text('Live upload'));
    await tester.pumpAndSettle();
    final container = ProviderScope.containerOf(tester.element(find.byType(LiveTrackingSection)));
    expect(container.read(liveUploadEnabledProvider), isFalse);
    expect(await const FlutterSecureStorage().read(key: 'live_upload_enabled'), 'false');
  });

  testWidgets('an older server: explains, no controls', (tester) async {
    await _pump(tester, serverApiLevel: 1);
    expect(find.textContaining('need a newer server'), findsOneWidget);
    expect(find.byType(CheckboxListTile), findsNothing);
  });

  testWidgets('signed out: asks to sign in', (tester) async {
    await _pump(tester, signedIn: false);
    expect(find.text('Sign in to a server to use live upload and sharing.'), findsOneWidget);
  });
}
