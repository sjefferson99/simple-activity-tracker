import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/dto/live_dto.dart';
import '../../core/auth/auth_state_controller.dart';
import '../../core/sync/live_sharing_store.dart';
import '../../core/version/api_compat.dart';

/// What Settings' live-sharing controls show (issue #130 D4).
class LiveSharingView {
  final LiveSharingSnapshot snapshot;

  /// The server is older than live tracking: nothing to configure.
  final bool unsupported;

  /// The server couldn't be reached; [snapshot] is the last known setting.
  final bool offline;

  /// A change made on this phone hasn't reached the server yet. It will,
  /// before any more live points are sent.
  final bool pendingSync;

  const LiveSharingView({
    required this.snapshot,
    this.unsupported = false,
    this.offline = false,
    this.pendingSync = false,
  });

  LiveSharingView copyWith({LiveSharingSnapshot? snapshot, bool? offline, bool? pendingSync}) =>
      LiveSharingView(
        snapshot: snapshot ?? this.snapshot,
        unsupported: unsupported,
        offline: offline ?? this.offline,
        pendingSync: pendingSync ?? this.pendingSync,
      );
}

/// Null when signed out. Loads the user list and the user's grants from the
/// server, falling back to the last known setting offline. A change takes
/// effect straight away when online; offline it's kept on the phone and sent
/// before any more live points (LiveSharingStore).
final liveSharingControllerProvider =
    AsyncNotifierProvider.autoDispose<LiveSharingController, LiveSharingView?>(
      LiveSharingController.new,
    );

class LiveSharingController extends AsyncNotifier<LiveSharingView?> {
  @override
  Future<LiveSharingView?> build() async {
    final auth = await ref.watch(authStateControllerProvider.future);
    if (!auth.isSignedIn || !auth.hasServerUrl) return null;
    final api = ref.read(apiClientProvider);
    final store = ref.read(liveSharingStoreProvider);

    try {
      final info = await api.getServerInfo(baseUrl: auth.serverUrl!, token: auth.token!);
      if (info.apiLevel < ApiLevels.liveTracking) {
        return const LiveSharingView(snapshot: LiveSharingSnapshot.empty, unsupported: true);
      }
      var pendingSync = false;
      try {
        await store.flush(api, auth);
      } on ApiRejectedException {
        // Dropped by the store; the server's own setting is loaded below.
      } on ApiException {
        pendingSync = true;
      }
      final users = await api.listUsers(baseUrl: auth.serverUrl!, token: auth.token!);
      final shares = await api.getMyShares(baseUrl: auth.serverUrl!, token: auth.token!);
      var snapshot = LiveSharingSnapshot(
        paused: shares.liveSharingPaused,
        users: {for (final user in users) user.id: user.displayName},
        liveViewerIds: shares.liveViewerIds,
      );
      // A change still waiting to be sent is what the user last chose.
      final pending = await store.pending();
      if (pending != null) snapshot = snapshot.withSetting(pending);
      await store.saveSnapshot(snapshot);
      ref.invalidate(liveSharingSnapshotProvider);
      return LiveSharingView(snapshot: snapshot, pendingSync: pendingSync || pending != null);
    } on ApiUnauthorizedException {
      rethrow;
    } on ApiException {
      return LiveSharingView(
        snapshot: await store.snapshot(),
        offline: true,
        pendingSync: await store.pending() != null,
      );
    }
  }

  Future<void> setPaused(bool paused) => _change(
    (snapshot) => LiveSharingRequestDto(
      liveSharingPaused: paused,
      liveViewerIds: snapshot.liveViewerIds,
    ),
  );

  Future<void> setViewer(String viewerId, bool canWatchLive) => _change(
    (snapshot) => LiveSharingRequestDto(
      liveSharingPaused: snapshot.paused,
      liveViewerIds: canWatchLive
          ? {...snapshot.liveViewerIds, viewerId}
          : ({...snapshot.liveViewerIds}..remove(viewerId)),
    ),
  );

  /// Saves the change locally first (so it's never lost), shows it, then
  /// tries to send it. A network failure isn't an error here: the change
  /// stays queued and the view says so. A rejection is rethrown for the
  /// screen to show next to the control, after reloading the server's own
  /// setting (never routed into `state`, which would unmount the controls).
  Future<void> _change(LiveSharingRequestDto Function(LiveSharingSnapshot) next) async {
    final view = state.value;
    if (view == null || view.unsupported) return;
    final store = ref.read(liveSharingStoreProvider);
    final setting = next(view.snapshot);
    await store.setPending(setting);
    state = AsyncData(view.copyWith(snapshot: view.snapshot.withSetting(setting), pendingSync: true));
    ref.invalidate(liveSharingSnapshotProvider);

    final auth = await ref.read(authStateControllerProvider.future);
    if (!auth.isSignedIn || !auth.hasServerUrl) return;
    try {
      await store.flush(ref.read(apiClientProvider), auth);
      state = AsyncData(
        state.value!.copyWith(snapshot: await store.snapshot(), pendingSync: false, offline: false),
      );
      ref.invalidate(liveSharingSnapshotProvider);
    } on ApiRejectedException {
      ref.invalidateSelf();
      rethrow;
    } on ApiException {
      // Stays queued — see doc comment.
    }
  }
}
