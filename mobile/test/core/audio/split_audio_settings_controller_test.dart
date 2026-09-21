import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/audio/split_audio_settings_controller.dart';
import 'package:simple_activity_tracker/domain/tracking/split_audio_settings.dart';

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
    'defaults to defaultSettings before storage has loaded, and stays there with nothing stored',
    () async {
      final container = _container({});
      expect(
        container.read(splitAudioSettingsControllerProvider),
        SplitAudioSettings.defaultSettings,
      );

      await pumpEventQueue();
      expect(
        container.read(splitAudioSettingsControllerProvider),
        SplitAudioSettings.defaultSettings,
      );
    },
  );

  test('loads previously persisted settings on build', () async {
    const settings = SplitAudioSettings(
      beepOnSplitChange: true,
      beepOnVerdictChange: false,
      announceSplitStats: true,
      announceVerdictCorrection: true,
    );
    final container = _container({
      'split_audio_settings': jsonEncode(settings.toJson()),
    });
    container.read(splitAudioSettingsControllerProvider);
    await pumpEventQueue();

    expect(container.read(splitAudioSettingsControllerProvider), settings);
  });

  test('update() updates state immediately and persists it', () async {
    final container = _container({});
    const settings = SplitAudioSettings(
      beepOnSplitChange: true,
      beepOnVerdictChange: false,
      announceSplitStats: false,
      announceVerdictCorrection: false,
    );
    await container
        .read(splitAudioSettingsControllerProvider.notifier)
        .update(settings);

    expect(container.read(splitAudioSettingsControllerProvider), settings);

    final storage = const FlutterSecureStorage();
    final stored = await storage.read(key: 'split_audio_settings');
    expect(stored, isNotNull);
    expect(
      SplitAudioSettings.fromJson(jsonDecode(stored!) as Map<String, Object?>),
      settings,
    );
  });

  test(
    'a slow _load() cannot clobber an update() the user already made',
    () async {
      const persisted = SplitAudioSettings(
        beepOnSplitChange: true,
        beepOnVerdictChange: true,
        announceSplitStats: false,
        announceVerdictCorrection: false,
      );
      final container = _container({
        'split_audio_settings': jsonEncode(persisted.toJson()),
      });
      // Trigger build()/the unawaited _load(), but don't let it resolve yet.
      container.read(splitAudioSettingsControllerProvider);

      const selected = SplitAudioSettings.defaultSettings;
      await container
          .read(splitAudioSettingsControllerProvider.notifier)
          .update(selected);

      // Now let the in-flight _load() resolve — it must not overwrite the
      // user's update with the stale persisted value it read earlier.
      await pumpEventQueue();

      expect(container.read(splitAudioSettingsControllerProvider), selected);
    },
  );

  group('ensureLoaded', () {
    test(
      'resolves the real persisted value, not the synchronous default (regression: a cold app launch\'s first Start tap could read the stale default before _load() finished)',
      () async {
        const persisted = SplitAudioSettings(
          beepOnSplitChange: true,
          beepOnVerdictChange: true,
          announceSplitStats: true,
          announceVerdictCorrection: true,
        );
        final container = _container({
          'split_audio_settings': jsonEncode(persisted.toJson()),
        });
        final notifier = container.read(
          splitAudioSettingsControllerProvider.notifier,
        );

        // Immediately after build() — before any pumpEventQueue() — state is
        // still the synchronous default. This is the exact moment the real
        // bug read from: a caller that just does ref.read() here (as
        // LiveRunController.start() originally did) gets every toggle off
        // even though the real persisted value has all four on.
        expect(
          container.read(splitAudioSettingsControllerProvider).anyEnabled,
          isFalse,
        );

        await notifier.ensureLoaded();

        expect(container.read(splitAudioSettingsControllerProvider), persisted);
      },
    );

    test('is safe to await more than once', () async {
      final container = _container({});
      final notifier = container.read(
        splitAudioSettingsControllerProvider.notifier,
      );

      await notifier.ensureLoaded();
      await notifier.ensureLoaded();

      expect(
        container.read(splitAudioSettingsControllerProvider),
        SplitAudioSettings.defaultSettings,
      );
    });
  });
}
