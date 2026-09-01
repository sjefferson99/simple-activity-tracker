sealed class LiveRunState {
  const LiveRunState();
}

class LiveRunIdle extends LiveRunState {
  const LiveRunIdle();
}

class LiveRunAcquiring extends LiveRunState {
  const LiveRunAcquiring();
}

class LiveRunActive extends LiveRunState {
  final double? speedMps;
  final double accuracyMeters;

  const LiveRunActive({required this.speedMps, required this.accuracyMeters});
}

class LiveRunPermissionDenied extends LiveRunState {
  final bool forever;

  const LiveRunPermissionDenied({required this.forever});
}

class LiveRunServiceDisabled extends LiveRunState {
  const LiveRunServiceDisabled();
}
