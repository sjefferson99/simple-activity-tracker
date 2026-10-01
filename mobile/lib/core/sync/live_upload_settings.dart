import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

const _liveUploadEnabledKey = 'live_upload_enabled';

final liveUploadEnabledProvider = NotifierProvider<LiveUploadEnabledController, bool>(
  LiveUploadEnabledController.new,
);

/// The Settings "Live upload" switch (issue #130 D3). On by default; turning
/// it off saves mobile data. LiveUploadService follows it immediately, even
/// mid-run. Persisted the same way as ActivityModeController, with the same
/// guard against a slow initial load overwriting a change the user already
/// made.
class LiveUploadEnabledController extends Notifier<bool> {
  FlutterSecureStorage get _storage => const FlutterSecureStorage();

  bool _userHasChanged = false;

  @override
  bool build() {
    unawaited(_load());
    return true;
  }

  Future<void> _load() async {
    final stored = await _storage.read(key: _liveUploadEnabledKey);
    if (_userHasChanged) return;
    final enabled = stored != 'false';
    if (enabled != state) state = enabled;
  }

  Future<void> set(bool enabled) async {
    _userHasChanged = true;
    state = enabled;
    await _storage.write(key: _liveUploadEnabledKey, value: '$enabled');
  }
}
