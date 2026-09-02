import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

final connectivityMonitorProvider = Provider<ConnectivityMonitor>((ref) {
  return PlusConnectivityMonitor();
});

/// Thin wrapper over connectivity_plus so [SyncService] can be tested with a
/// fake connectivity source instead of the real platform channel.
abstract class ConnectivityMonitor {
  /// Fires whenever connectivity is regained (transitions into "some
  /// connection"), which is one of SyncService's retry triggers — never
  /// fires for a transition into "no connection".
  Stream<void> get onConnected;

  Future<bool> get isConnected;
}

class PlusConnectivityMonitor implements ConnectivityMonitor {
  final Connectivity _connectivity = Connectivity();

  bool _hasConnection(List<ConnectivityResult> results) =>
      results.any((r) => r != ConnectivityResult.none);

  @override
  Stream<void> get onConnected => _connectivity.onConnectivityChanged
      .where(_hasConnection)
      .map((_) {});

  @override
  Future<bool> get isConnected async =>
      _hasConnection(await _connectivity.checkConnectivity());
}
