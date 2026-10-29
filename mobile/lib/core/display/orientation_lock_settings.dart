import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

const _portraitLockKey = 'portrait_lock_enabled';

final portraitLockProvider = NotifierProvider<PortraitLockController, bool>(
  PortraitLockController.new,
);

/// The Settings "Lock to portrait" switch (issue #150). Off by default, so
/// the app follows the phone's own rotation setting; on keeps the app upright
/// even when system auto-rotate is on (like Kindle's rotation lock).
/// Persisted the same way as LiveUploadEnabledController, with the same guard
/// against a slow initial load overwriting a change the user already made.
class PortraitLockController extends Notifier<bool> {
  FlutterSecureStorage get _storage => const FlutterSecureStorage();

  bool _userHasChanged = false;

  @override
  bool build() {
    unawaited(_load());
    return false;
  }

  Future<void> _load() async {
    final stored = await _storage.read(key: _portraitLockKey);
    if (_userHasChanged) return;
    final enabled = stored == 'true';
    if (enabled != state) state = enabled;
  }

  Future<void> set(bool enabled) async {
    _userHasChanged = true;
    state = enabled;
    await _storage.write(key: _portraitLockKey, value: '$enabled');
  }
}

/// Applies [locked] to the running app. An empty list hands control back to
/// the platform, i.e. the manifest/Info.plist default of following the
/// phone's rotation setting.
Future<void> applyPortraitLock(bool locked) => SystemChrome.setPreferredOrientations(
  locked ? const [DeviceOrientation.portraitUp] : const [],
);
