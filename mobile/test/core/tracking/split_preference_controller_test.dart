import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/tracking/split_preference_controller.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';

ProviderContainer _container(Map<String, String> backing) {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(
    backing,
  );
  final container = ProviderContainer();
  addTearDown(container.dispose);
  return container;
}

void main() {
  test(
    'defaults to 1km before storage has loaded, and stays there with nothing stored',
    () async {
      final container = _container({});
      expect(
        container.read(splitPreferenceControllerProvider),
        SplitPreference.defaultPreference,
      );

      // Let the async _load() in build() resolve.
      await pumpEventQueue();
      expect(
        container.read(splitPreferenceControllerProvider),
        SplitPreference.defaultPreference,
      );
    },
  );

  test('loads a previously persisted preference on build', () async {
    final container = _container({
      'split_kind': 'time_min',
      'split_value': '5',
    });
    // ProviderContainer providers are lazy — build() (and the _load() it
    // fires) only runs once something actually reads the provider, the same
    // way a widget's ref.watch would trigger it in the real app.
    container.read(splitPreferenceControllerProvider);
    await pumpEventQueue();

    expect(
      container.read(splitPreferenceControllerProvider),
      const SplitPreference(kind: SplitKind.timeMin, value: 5),
    );
  });

  test(
    'falls back to the default when the persisted value is invalid/garbage',
    () async {
      final container = _container({
        'split_kind': 'bogus',
        'split_value': 'not-a-number',
      });
      container.read(splitPreferenceControllerProvider);
      await pumpEventQueue();

      expect(
        container.read(splitPreferenceControllerProvider),
        SplitPreference.defaultPreference,
      );
    },
  );

  test('select updates state immediately and persists it', () async {
    final container = _container({});
    await container
        .read(splitPreferenceControllerProvider.notifier)
        .select(const SplitPreference(kind: SplitKind.distanceMi, value: 2));

    expect(
      container.read(splitPreferenceControllerProvider),
      const SplitPreference(kind: SplitKind.distanceMi, value: 2),
    );

    // A fresh controller (simulating an app restart) picks up the persisted value.
    final storage = const FlutterSecureStorage();
    expect(await storage.read(key: 'split_kind'), 'distance_mi');
    expect(await storage.read(key: 'split_value'), '2');
  });

  test(
    'a slow _load() cannot clobber a select() the user already made',
    () async {
      final container = _container({
        'split_kind': 'time_min',
        'split_value': '10',
      });
      // Trigger build()/the unawaited _load(), but don't let it resolve yet.
      container.read(splitPreferenceControllerProvider);

      await container
          .read(splitPreferenceControllerProvider.notifier)
          .select(const SplitPreference(kind: SplitKind.distanceKm, value: 3));

      // Now let the in-flight _load() resolve — it must not overwrite the
      // user's selection with the stale persisted value it read earlier.
      await pumpEventQueue();

      expect(
        container.read(splitPreferenceControllerProvider),
        const SplitPreference(kind: SplitKind.distanceKm, value: 3),
      );
    },
  );
}
