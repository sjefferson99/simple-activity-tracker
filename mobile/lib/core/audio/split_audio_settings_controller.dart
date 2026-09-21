import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../domain/tracking/split_audio_settings.dart';

const _splitAudioSettingsKey = 'split_audio_settings';

final splitAudioSettingsControllerProvider =
    NotifierProvider<SplitAudioSettingsController, SplitAudioSettings>(
      SplitAudioSettingsController.new,
    );

/// The audio-cue toggles set on the Splits screen (issue #125). Persisted
/// (not secure — same rationale as `SplitPlanController`: not sensitive, but
/// `flutter_secure_storage` is already a dependency) so the app reopens with
/// whichever settings were last chosen.
///
/// Starts at [SplitAudioSettings.defaultSettings] and stays there until the
/// async [_load] resolves — same pattern as `SplitPlanController`/
/// `ActivityModeController` reading real state asynchronously after a
/// synchronous default.
class SplitAudioSettingsController extends Notifier<SplitAudioSettings> {
  FlutterSecureStorage get _storage => const FlutterSecureStorage();

  // Guards against _load() (fired from build(), can still be in flight)
  // overwriting an update() the user made in the meantime — same rationale
  // as SplitPlanController's guard.
  bool _userHasSelected = false;

  // Real on-device bug (2026-09-21): a cold app launch's very first Start
  // tap could beat _load()'s async flutter_secure_storage read, so
  // LiveRunController.start()'s ref.read(...) captured the stale
  // SplitAudioSettings.defaultSettings (every toggle off) and — per its own
  // "fixed for the run's duration" contract, same as _activityMode/
  // _splitPlan — stayed silently off for that entire run regardless of what
  // was actually persisted. Invisible on a warm app (plenty of time passes
  // before anyone reaches Start) and on every run after the first (_load()
  // has long since resolved by then), which is exactly the symptom
  // reported: works on the second run, not the first, after a fresh launch.
  // _loadFuture lets a caller that can't tolerate a stale default (unlike
  // ActivityMode/SplitPlan, where a stale-but-reasonable fallback is an
  // acceptable trade) await the real value instead.
  late final Future<void> _loadFuture;

  @override
  SplitAudioSettings build() {
    _loadFuture = _load();
    return SplitAudioSettings.defaultSettings;
  }

  /// Waits for the initial load from storage to finish, so a caller reading
  /// [state] right after is guaranteed the real persisted value rather than
  /// [SplitAudioSettings.defaultSettings]'s synchronous placeholder. Cheap
  /// and safe to call more than once — resolves immediately once the first
  /// call has completed, mirroring `CertTrustStore.ensureLoaded()`'s
  /// idempotent-await shape.
  Future<void> ensureLoaded() => _loadFuture;

  Future<void> _load() async {
    final stored = await _storage.read(key: _splitAudioSettingsKey);
    if (stored == null) return;
    if (_userHasSelected) return;
    final settings = SplitAudioSettings.fromJson(
      Map<String, Object?>.from(
        jsonDecode(stored) as Map<Object?, Object?>,
      ),
    );
    if (settings != null && settings != state) state = settings;
  }

  Future<void> update(SplitAudioSettings settings) async {
    _userHasSelected = true;
    state = settings;
    await _storage.write(
      key: _splitAudioSettingsKey,
      value: jsonEncode(settings.toJson()),
    );
  }
}
