import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus_platform_interface/package_info_data.dart';
import 'package:package_info_plus_platform_interface/package_info_platform_interface.dart';
import 'package:path_provider_platform_interface/path_provider_platform_interface.dart';
import 'package:simple_activity_tracker/core/location/location_permission_state.dart';
import 'package:simple_activity_tracker/core/location/location_sample.dart';
import 'package:simple_activity_tracker/core/location/location_service.dart';
import 'package:simple_activity_tracker/features/live_run/live_run_controller.dart';
import 'package:simple_activity_tracker/features/live_run/live_run_state.dart';
import 'package:wakelock_plus_platform_interface/messages.g.dart';

/// `LiveRunController.start()` writes the run's GPX file under the app
/// documents directory (`newRunGpxFile`) — path_provider has no real
/// platform to ask outside a device/emulator, so this points it at a real
/// temp directory instead of a mocked channel.
class _FakePathProviderPlatform extends PathProviderPlatform {
  final String path;

  _FakePathProviderPlatform(this.path);

  @override
  Future<String?> getApplicationDocumentsPath() async => path;
}

/// stop() reads the app version via package_info_plus (for RunSummary) —
/// same story as path_provider, no real platform to ask outside a
/// device/emulator.
class _FakePackageInfoPlatform extends PackageInfoPlatform {
  @override
  Future<PackageInfoData> getAll({String? baseUrl}) async => PackageInfoData(
    appName: 'Simple Activity Tracker',
    packageName: 'test.simple_activity_tracker',
    version: '0.0.0',
    buildNumber: '1',
    buildSignature: '',
  );
}

/// Stands in for the platform side of `wakelock_plus`'s pigeon channel — its
/// own test helper (`wakelock_plus_platform_interface`'s `test/messages.g.dart`)
/// isn't published to pub.dev, so this mocks the same two channel
/// names/codec `WakelockPlusApi` uses directly. `LiveRunController` toggles
/// this on start/stop; without a handler the plugin throws
/// "Binding has not yet been initialized" outside a real device/emulator.
void _installFakeWakelockPlatform() {
  const codec = WakelockPlusApi.pigeonChannelCodec;
  void mock(String method, Object? Function(Object? call) handle) {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockDecodedMessageHandler<Object?>(
          BasicMessageChannel<Object?>(
            'dev.flutter.pigeon.wakelock_plus_platform_interface.WakelockPlusApi.$method',
            codec,
          ),
          (Object? message) async => wrapResponse(result: handle(message)),
        );
  }

  mock('toggle', (_) => null);
  mock('isEnabled', (_) => false);
}

/// A [LocationService] whose stream never emits until the test tells it to —
/// stands in for GPS that never gets a first fix (indoors, or #49's
/// Wi-Fi-off hang), so the acquiring timeout can be exercised without a real
/// platform channel.
class _NeverEmittingLocationService implements LocationService {
  final _controller = StreamController<LocationSample>.broadcast();

  @override
  Future<LocationPermissionState> checkPermission() async =>
      LocationPermissionState.granted;

  @override
  Future<LocationPermissionState> requestPermission() async =>
      LocationPermissionState.granted;

  @override
  Stream<LocationSample> get stream => _controller.stream;

  void emit(LocationSample sample) => _controller.add(sample);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  _installFakeWakelockPlatform();

  ProviderContainer container(LocationService locationService) {
    FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(
      {},
    );
    final tempDir = Directory.systemTemp.createTempSync(
      'live_run_controller_test',
    );
    addTearDown(() => tempDir.deleteSync(recursive: true));
    PathProviderPlatform.instance = _FakePathProviderPlatform(tempDir.path);
    PackageInfoPlatform.instance = _FakePackageInfoPlatform();

    final c = ProviderContainer(
      overrides: [locationServiceProvider.overrideWithValue(locationService)],
    );
    addTearDown(c.dispose);
    return c;
  }

  // Real (not faked) time, but short — LiveRunController.start() does real
  // dart:io/platform-channel work that fakeAsync's Timer-only clock can't
  // fast-forward through, so the acquiring timeout itself is shrunk via the
  // @visibleForTesting seam instead of faking the clock.
  const testTimeout = Duration(milliseconds: 50);

  test(
    'LiveRunAcquiring surfaces a timed-out message when no fix arrives in time',
    () async {
      final service = _NeverEmittingLocationService();
      final c = container(service);
      final controller = c.read(liveRunControllerProvider.notifier)
        ..acquiringTimeout = testTimeout;

      await controller.start();
      expect(c.read(liveRunControllerProvider), isA<LiveRunAcquiring>());
      expect(
        (c.read(liveRunControllerProvider) as LiveRunAcquiring).timedOut,
        isFalse,
      );

      await Future<void>.delayed(testTimeout * 3);
      expect(c.read(liveRunControllerProvider), isA<LiveRunAcquiring>());
      expect(
        (c.read(liveRunControllerProvider) as LiveRunAcquiring).timedOut,
        isTrue,
      );

      // Cleanly finish the run before the container/temp dir get torn down
      // — otherwise the still-running acquisition's own teardown (triggered
      // by container.dispose()) races the temp dir deletion, since
      // LiveRunController.build()'s onDispose hook is fire-and-forget by
      // design (see its comment).
      await controller.stop();
    },
  );

  test('a fix arriving before the timeout cancels it', () async {
    final service = _NeverEmittingLocationService();
    final c = container(service);
    final controller = c.read(liveRunControllerProvider.notifier)
      ..acquiringTimeout = testTimeout;

    await controller.start();

    service.emit(
      LocationSample(
        latitude: 0,
        longitude: 0,
        accuracyMeters: 5,
        hasAccuracy: true,
        timestamp: DateTime.now(),
      ),
    );
    await pumpEventQueue();
    expect(c.read(liveRunControllerProvider), isA<LiveRunActive>());

    // Waiting well past the (cancelled) timeout must not retroactively flip
    // back to an acquiring state — a real fix already arrived.
    await Future<void>.delayed(testTimeout * 3);
    expect(c.read(liveRunControllerProvider), isA<LiveRunActive>());
  });
}
