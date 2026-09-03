import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_runner/core/tracking/activity_mode_controller.dart';
import 'package:simple_runner/domain/tracking/activity_mode.dart';

ProviderContainer _container(Map<String, String> backing) {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(backing);
  final container = ProviderContainer();
  addTearDown(container.dispose);
  return container;
}

void main() {
  test('defaults to running before storage has loaded, and stays running with nothing stored', () async {
    final container = _container({});
    expect(container.read(activityModeControllerProvider), ActivityMode.running);

    // Let the async _load() in build() resolve.
    await pumpEventQueue();
    expect(container.read(activityModeControllerProvider), ActivityMode.running);
  });

  test('loads a previously persisted mode on build', () async {
    final container = _container({'activity_mode': 'cycling'});
    // ProviderContainer providers are lazy — build() (and the _load() it
    // fires) only runs once something actually reads the provider, the same
    // way a widget's ref.watch would trigger it in the real app.
    container.read(activityModeControllerProvider);
    await pumpEventQueue();

    expect(container.read(activityModeControllerProvider), ActivityMode.cycling);
  });

  test('select updates state immediately and persists it', () async {
    final container = _container({});
    await container
        .read(activityModeControllerProvider.notifier)
        .select(ActivityMode.cycling);

    expect(container.read(activityModeControllerProvider), ActivityMode.cycling);

    // A fresh controller (simulating an app restart) picks up the persisted value.
    final storage = const FlutterSecureStorage();
    expect(await storage.read(key: 'activity_mode'), 'cycling');
  });
}
