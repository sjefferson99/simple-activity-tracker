import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../domain/tracking/activity_mode.dart';

const _activityModeKey = 'activity_mode';

final activityModeControllerProvider =
    NotifierProvider<ActivityModeController, ActivityMode>(ActivityModeController.new);

/// The run/cycle toggle on the home screen. Persisted (not secure — it's not
/// sensitive, but flutter_secure_storage is already a dependency and this is
/// one more small string key alongside the ones AuthService keeps) so the
/// app reopens in whichever mode was last selected.
///
/// Starts at [ActivityMode.running] and stays there until the async [_load]
/// resolves — build() can't await — same pattern as AuthStateController
/// reading real state asynchronously after a synchronous default.
class ActivityModeController extends Notifier<ActivityMode> {
  FlutterSecureStorage get _storage => const FlutterSecureStorage();

  // Guards against _load() (fired from build(), can still be in flight)
  // overwriting a select() the user made in the meantime — without this, a
  // slow storage read completing after a fast tap could silently revert the
  // user's choice back to whatever was previously persisted.
  bool _userHasSelected = false;

  @override
  ActivityMode build() {
    unawaited(_load());
    return ActivityMode.running;
  }

  Future<void> _load() async {
    final stored = await _storage.read(key: _activityModeKey);
    if (_userHasSelected) return;
    final mode = ActivityMode.values.firstWhere(
      (m) => m.name == stored,
      orElse: () => ActivityMode.running,
    );
    if (mode != state) state = mode;
  }

  Future<void> select(ActivityMode mode) async {
    _userHasSelected = true;
    state = mode;
    await _storage.write(key: _activityModeKey, value: mode.name);
  }
}
