import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus_platform_interface/package_info_data.dart';
import 'package:package_info_plus_platform_interface/package_info_platform_interface.dart';
import 'package:path_provider_platform_interface/path_provider_platform_interface.dart';
import 'package:simple_activity_tracker/core/audio/split_audio_service.dart';
import 'package:simple_activity_tracker/core/audio/split_audio_settings_controller.dart';
import 'package:simple_activity_tracker/core/location/location_permission_state.dart';
import 'package:simple_activity_tracker/core/location/location_sample.dart';
import 'package:simple_activity_tracker/core/location/location_service.dart';
import 'package:simple_activity_tracker/core/tracking/activity_mode_controller.dart';
import 'package:simple_activity_tracker/core/tracking/split_plan_controller.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';
import 'package:simple_activity_tracker/domain/tracking/split_audio_settings.dart';
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';
import 'package:simple_activity_tracker/features/live_run/live_run_controller.dart';
import 'package:wakelock_plus_platform_interface/messages.g.dart';

// Fakes duplicated from live_run_controller_test.dart rather than shared —
// see that file's originals for the rationale on each.

class _FakePathProviderPlatform extends PathProviderPlatform {
  final String path;
  _FakePathProviderPlatform(this.path);
  @override
  Future<String?> getApplicationDocumentsPath() async => path;
}

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

class _ScriptedLocationService implements LocationService {
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

/// A point [metersFromOrigin] along the equator (matches
/// domain/tracking/metrics_engine_test.dart's convention), moving at
/// [speedMps] — high enough to clear the stationary gate's 0.6 m/s
/// enter-moving threshold on every point, so three consecutive points are
/// always enough to be "moving" throughout these tests.
LocationSample _sampleAtMeters(
  double metersFromOrigin,
  DateTime timestamp, {
  double speedMps = 5.0,
}) {
  final degrees = metersFromOrigin / 111195;
  return LocationSample(
    latitude: 0,
    longitude: degrees,
    accuracyMeters: 5,
    hasAccuracy: true,
    speedMps: speedMps,
    hasSpeed: true,
    timestamp: timestamp,
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  _installFakeWakelockPlatform();

  /// A custom plan with two 5m splits (small enough for a handful of
  /// synthetic points to cross a boundary) and a deliberately unmissable
  /// target on split 1 (5 m/s — every test point below moves at exactly
  /// that speed once "moving", so it settles dead on target) so both a
  /// splitChanged cue and a verdict cue are reachable within a short point
  /// sequence.
  final testPlan = SplitPlan(
    base: const SplitPreference(kind: SplitKind.distanceKm, value: 1),
    customSplits: const [
      PlannedSplit(size: 5, targetSpeedMps: 5.0),
      PlannedSplit(size: 5, targetSpeedMps: 5.0),
    ],
  );

  Future<(ProviderContainer, NoopSplitAudioService)> setUp({
    required SplitAudioSettings audioSettings,
    ActivityMode activityMode = ActivityMode.running,
  }) async {
    FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(
      {},
    );
    final tempDir = Directory.systemTemp.createTempSync(
      'live_run_controller_audio_test',
    );
    addTearDown(() => tempDir.deleteSync(recursive: true));
    PathProviderPlatform.instance = _FakePathProviderPlatform(tempDir.path);
    PackageInfoPlatform.instance = _FakePackageInfoPlatform();

    final service = _ScriptedLocationService();
    final audio = NoopSplitAudioService();
    final c = ProviderContainer(
      overrides: [
        locationServiceProvider.overrideWithValue(service),
        splitAudioServiceProvider.overrideWithValue(audio),
      ],
    );
    addTearDown(c.dispose);

    // Real controllers, backed by the fake secure storage above — simplest
    // way to get a specific SplitPlan/SplitAudioSettings/ActivityMode into
    // the run without a second layer of fakes.
    await c.read(activityModeControllerProvider.notifier).select(activityMode);
    await c.read(splitPlanControllerProvider.notifier).select(testPlan);
    await c
        .read(splitAudioSettingsControllerProvider.notifier)
        .update(audioSettings);

    final controller = c.read(liveRunControllerProvider.notifier);
    await controller.start();
    return (c, audio);
  }

  test(
    'the start beep plays whenever either beep toggle is on, '
    'independent of the speech toggles',
    () async {
      final (c, audio) = await setUp(
        audioSettings: SplitAudioSettings.defaultSettings.copyWith(
          beepOnSplitChange: true,
        ),
      );

      // No fix emitted at all — the start cue must not wait on GPS (the
      // indoor/no-signal case this was added for).
      expect(audio.calls, contains('playActivityStarted'));
      expect(
        audio.calls.where((c) => c.startsWith('speak:')),
        isEmpty,
        reason: 'no speech toggle is on, so no TTS should fire',
      );

      await c.read(liveRunControllerProvider.notifier).stop();
    },
  );

  test(
    'the start TTS speaks whenever either speech toggle is on, '
    'independent of the beep toggles',
    () async {
      final (c, audio) = await setUp(
        audioSettings: SplitAudioSettings.defaultSettings.copyWith(
          announceVerdictCorrection: true,
        ),
      );

      expect(
        audio.calls,
        isNot(contains('playActivityStarted')),
        reason: 'no beep toggle is on, so no beep should fire',
      );
      // testPlan's split 1 has a target of 5.0 m/s (= 3:20/km); the plan's
      // targetsAsPace defaults to true, and _announcementUnit follows it.
      expect(
        audio.calls,
        contains('speak:Target 3 minutes 20 per kilometre.'),
      );

      await c.read(liveRunControllerProvider.notifier).stop();
    },
  );

  test(
    'a cold-launch race cannot silently start a run with audio off '
    '(regression: start() used to ref.read() the settings controller '
    'without awaiting its load, so a Start tap fast enough to beat the '
    'async flutter_secure_storage read captured the stale all-off default '
    'and stayed off for the whole run)',
    () async {
      FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(
        {
          // Written directly, not via update() — simulates a setting
          // already persisted from a previous app session, the way it
          // would be on a real cold launch.
          'split_audio_settings': jsonEncode(
            SplitAudioSettings.defaultSettings
                .copyWith(beepOnSplitChange: true)
                .toJson(),
          ),
        },
      );
      final tempDir = Directory.systemTemp.createTempSync(
        'live_run_controller_audio_race_test',
      );
      addTearDown(() => tempDir.deleteSync(recursive: true));
      PathProviderPlatform.instance = _FakePathProviderPlatform(tempDir.path);
      PackageInfoPlatform.instance = _FakePackageInfoPlatform();

      final service = _ScriptedLocationService();
      final audio = NoopSplitAudioService();
      final c = ProviderContainer(
        overrides: [
          locationServiceProvider.overrideWithValue(service),
          splitAudioServiceProvider.overrideWithValue(audio),
        ],
      );
      addTearDown(c.dispose);
      await c.read(splitPlanControllerProvider.notifier).select(testPlan);

      // The crux of the test: read the controller (triggering build()'s
      // fire-and-forget _load()) and immediately start() — no
      // pumpEventQueue() in between, so _load()'s async storage read has
      // not had a chance to resolve yet, exactly like a fast tap on a fresh
      // app launch.
      c.read(splitAudioSettingsControllerProvider);
      final controller = c.read(liveRunControllerProvider.notifier);
      await controller.start();

      expect(
        audio.calls,
        contains('playActivityStarted'),
        reason:
            'start() must have awaited the real persisted '
            'beepOnSplitChange:true value, not the stale all-off default',
      );

      await controller.stop();
    },
  );

  test('no start cue with every audio toggle off', () async {
    final (c, audio) = await setUp(
      audioSettings: SplitAudioSettings.defaultSettings,
    );
    expect(audio.calls, isEmpty);
    await c.read(liveRunControllerProvider.notifier).stop();
  });

  test('no start cue in cycling mode', () async {
    final (c, audio) = await setUp(
      audioSettings: SplitAudioSettings.defaultSettings.copyWith(
        beepOnSplitChange: true,
      ),
      activityMode: ActivityMode.cycling,
    );
    expect(audio.calls, isEmpty);
    await c.read(liveRunControllerProvider.notifier).stop();
  });

  test(
    'a beep plays on split change and the settings toggle is respected',
    () async {
      final (c, audio) = await setUp(
        audioSettings: SplitAudioSettings.defaultSettings.copyWith(
          beepOnSplitChange: true,
        ),
      );
      final service = c.read(locationServiceProvider) as _ScriptedLocationService;
      final start = DateTime.now();

      // Walk past the 5m boundary of split 1 at a steady 5 m/s — three
      // points to clear the stationary gate's enter-moving streak, a fourth
      // to cross the boundary.
      for (var i = 0; i <= 6; i++) {
        service.emit(
          _sampleAtMeters(i * 2.0, start.add(Duration(seconds: i))),
        );
        await pumpEventQueue();
      }

      expect(
        audio.calls,
        contains('playSplitChanged'),
        reason: 'expected a split-change beep once split 1 was crossed',
      );

      await c.read(liveRunControllerProvider.notifier).stop();
    },
  );

  test(
    'rolling onto the base plan after a custom plan is exhausted announces it',
    () async {
      final (c, audio) = await setUp(
        audioSettings: SplitAudioSettings.defaultSettings.copyWith(
          beepOnSplitChange: true,
          announceSplitTarget: true,
        ),
      );
      final service = c.read(locationServiceProvider) as _ScriptedLocationService;
      final start = DateTime.now();

      // testPlan has exactly two 5m custom splits — walk well past both
      // boundaries at 5 m/s: split 1 -> 2 (still custom), then 2 -> 3 (the
      // roll-on tick onto the 1km base plan, per testPlan's own doc).
      for (var i = 0; i <= 30; i++) {
        service.emit(
          _sampleAtMeters(i * 2.0, start.add(Duration(seconds: i))),
        );
        await pumpEventQueue();
      }

      expect(
        audio.calls,
        contains(
          'speak:Now on rolling splits of 1 kilometre. No target.',
        ),
        reason:
            'testPlan\'s base plan (1km, no rolling target) has no target, '
            'unlike its two custom splits',
      );

      await c.read(liveRunControllerProvider.notifier).stop();
    },
  );

  test('no cue is played with every audio toggle off', () async {
    final (c, audio) = await setUp(
      audioSettings: SplitAudioSettings.defaultSettings,
    );
    final service = c.read(locationServiceProvider) as _ScriptedLocationService;
    final start = DateTime.now();

    for (var i = 0; i <= 6; i++) {
      service.emit(_sampleAtMeters(i * 2.0, start.add(Duration(seconds: i))));
      await pumpEventQueue();
    }

    expect(audio.calls, isEmpty);

    await c.read(liveRunControllerProvider.notifier).stop();
  });

  test(
    'no cue is played in cycling mode, even with audio enabled and a plan with targets',
    () async {
      final (c, audio) = await setUp(
        audioSettings: SplitAudioSettings.defaultSettings.copyWith(
          beepOnSplitChange: true,
        ),
        activityMode: ActivityMode.cycling,
      );
      final service = c.read(locationServiceProvider) as _ScriptedLocationService;
      final start = DateTime.now();

      for (var i = 0; i <= 6; i++) {
        service.emit(
          _sampleAtMeters(i * 2.0, start.add(Duration(seconds: i))),
        );
        await pumpEventQueue();
      }

      expect(
        audio.calls,
        isEmpty,
        reason:
            'cycling has no split concept (ActivityMode.supportsSplits) — '
            'must not surface cues via audio that the tiles already hide',
      );

      await c.read(liveRunControllerProvider.notifier).stop();
    },
  );

  test('no cue is played while paused', () async {
    final (c, audio) = await setUp(
      audioSettings: SplitAudioSettings.defaultSettings.copyWith(
        beepOnSplitChange: true,
      ),
    );
    final service = c.read(locationServiceProvider) as _ScriptedLocationService;
    final controller = c.read(liveRunControllerProvider.notifier);
    final start = DateTime.now();

    // Three points to enter "moving", then pause before ever reaching the
    // 5m boundary.
    for (var i = 0; i <= 2; i++) {
      service.emit(_sampleAtMeters(i * 1.0, start.add(Duration(seconds: i))));
      await pumpEventQueue();
    }
    controller.pause();
    await pumpEventQueue();
    audio.calls.clear();

    // A fix delivered while paused must not be processed for cues at all —
    // _onSample already returns early on pause.
    service.emit(
      _sampleAtMeters(10.0, start.add(const Duration(seconds: 10))),
    );
    await pumpEventQueue();

    expect(audio.calls, isEmpty);

    await controller.stop();
  });
}
