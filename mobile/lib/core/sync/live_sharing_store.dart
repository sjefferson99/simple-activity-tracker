import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../api/api_client.dart';
import '../api/api_exception.dart';
import '../api/dto/live_dto.dart';
import '../auth/auth_state.dart';

final liveSharingStoreProvider = Provider<LiveSharingStore>((ref) => LiveSharingStore());

/// The last known live-sharing setting on this phone, for the run screen's
/// badge. Cheap (local storage only); Settings invalidates it whenever it
/// changes or reloads the setting.
final liveSharingSnapshotProvider = FutureProvider<LiveSharingSnapshot>(
  (ref) => ref.read(liveSharingStoreProvider).snapshot(),
);

const _pendingKey = 'live_sharing_pending';
const _cacheKey = 'live_sharing_cache';

/// The user's live-sharing setting as last known on this phone: who may
/// watch live, and whether "Don't live share" is on. Used to show Settings
/// and the run screen's badge while offline.
class LiveSharingSnapshot {
  final bool paused;

  /// Every user the server listed, id → display name.
  final Map<String, String> users;
  final Set<String> liveViewerIds;

  const LiveSharingSnapshot({
    required this.paused,
    required this.users,
    required this.liveViewerIds,
  });

  static const empty = LiveSharingSnapshot(paused: false, users: {}, liveViewerIds: {});

  /// How many people can watch right now (none while paused).
  int get watchingCount => paused ? 0 : liveViewerIds.length;

  LiveSharingSnapshot withSetting(LiveSharingRequestDto setting) => LiveSharingSnapshot(
    paused: setting.liveSharingPaused,
    users: users,
    liveViewerIds: setting.liveViewerIds,
  );

  Map<String, dynamic> toJson() => {
    'paused': paused,
    'users': users,
    'live_viewer_ids': liveViewerIds.toList(),
  };

  factory LiveSharingSnapshot.fromJson(Map<String, dynamic> json) => LiveSharingSnapshot(
    paused: json['paused'] == true,
    users: {
      for (final entry in (json['users'] as Map<String, dynamic>? ?? const {}).entries)
        if (entry.value is String) entry.key: entry.value as String,
    },
    liveViewerIds: {
      for (final id in (json['live_viewer_ids'] as List<dynamic>? ?? const []))
        if (id is String) id,
    },
  );
}

/// Keeps a live-sharing change made on the phone until the server has it
/// (issue #130 D4). Changes take effect immediately when online; offline, the
/// latest change waits here as one whole document and is sent before any
/// further live points ([LiveUploadService] calls [flush] first), so a
/// "Don't live share" tapped with no signal still wins over the next upload.
/// Plain Dart aside from the storage plugin, like AuthService.
class LiveSharingStore {
  final FlutterSecureStorage _storage;

  LiveSharingStore({FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage();

  Future<LiveSharingRequestDto?> pending() async {
    final raw = await _storage.read(key: _pendingKey);
    if (raw == null) return null;
    try {
      return LiveSharingRequestDto.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } on Object {
      return null;
    }
  }

  Future<void> setPending(LiveSharingRequestDto setting) async {
    await _storage.write(key: _pendingKey, value: jsonEncode(setting.toJson()));
    await saveSnapshot((await snapshot()).withSetting(setting));
  }

  Future<LiveSharingSnapshot> snapshot() async {
    final raw = await _storage.read(key: _cacheKey);
    if (raw == null) return LiveSharingSnapshot.empty;
    try {
      return LiveSharingSnapshot.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } on Object {
      return LiveSharingSnapshot.empty;
    }
  }

  Future<void> saveSnapshot(LiveSharingSnapshot snapshot) =>
      _storage.write(key: _cacheKey, value: jsonEncode(snapshot.toJson()));

  /// Sends the queued change, if any. Returns normally once nothing is left
  /// pending. A network-type failure is rethrown and the change stays queued;
  /// a rejection (a chosen user was disabled meanwhile, or the server is too
  /// old) can never succeed as-is, so the change is dropped, then rethrown.
  Future<void> flush(ApiClient api, AuthState auth) async {
    final setting = await pending();
    if (setting == null) return;
    try {
      final shares = await api.putLiveSharing(
        baseUrl: auth.serverUrl!,
        token: auth.token!,
        request: setting,
      );
      await _clearPendingIf(setting);
      final current = await snapshot();
      await saveSnapshot(
        LiveSharingSnapshot(
          paused: shares.liveSharingPaused,
          users: current.users,
          liveViewerIds: shares.liveViewerIds,
        ),
      );
    } on ApiRejectedException {
      await _clearPendingIf(setting);
      rethrow;
    }
  }

  /// Only clears [sent]: a newer change made while it was in flight stays
  /// queued for the next flush.
  Future<void> _clearPendingIf(LiveSharingRequestDto sent) async {
    if (await pending() == sent) await _storage.delete(key: _pendingKey);
  }
}
