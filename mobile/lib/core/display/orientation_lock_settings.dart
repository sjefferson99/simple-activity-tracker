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
    final enabled = await _readStoredPortraitLock();
    if (_userHasChanged) return;
    if (enabled != state) state = enabled;
  }

  Future<void> set(bool enabled) async {
    _userHasChanged = true;
    state = enabled;
    await _storage.write(key: _portraitLockKey, value: '$enabled');
  }
}

Future<bool> _readStoredPortraitLock() async =>
    await const FlutterSecureStorage().read(key: _portraitLockKey) == 'true';

/// Applies the saved setting before the first frame, so a locked app held
/// sideways at launch never draws in landscape while the provider's async
/// load catches up. From then on the app root applies changes as they happen.
Future<void> applyStoredPortraitLock() async => applyPortraitLock(await _readStoredPortraitLock());

/// Applies [locked] to the running app. An empty list hands control back to
/// the platform, i.e. the manifest/Info.plist default of following the
/// phone's rotation setting.
Future<void> applyPortraitLock(bool locked) => SystemChrome.setPreferredOrientations(
  locked ? const [DeviceOrientation.portraitUp] : const [],
);
