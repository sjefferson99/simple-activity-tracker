import 'dart:async';

import 'package:simple_runner/core/sync/connectivity.dart';

class FakeConnectivityMonitor implements ConnectivityMonitor {
  bool connected;
  final _controller = StreamController<void>.broadcast();

  FakeConnectivityMonitor({this.connected = true});

  @override
  Future<bool> get isConnected async => connected;

  @override
  Stream<void> get onConnected => _controller.stream;

  void goOnline() {
    connected = true;
    _controller.add(null);
  }

  void goOffline() {
    connected = false;
  }

  void dispose() => _controller.close();
}
