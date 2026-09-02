import '../../domain/models/live_metrics.dart';
import '../../domain/tracking/run_phase.dart';

sealed class LiveRunState {
  const LiveRunState();
}

class LiveRunIdle extends LiveRunState {
  const LiveRunIdle();
}

class LiveRunAcquiring extends LiveRunState {
  const LiveRunAcquiring();
}

/// Covers both [RunPhase.tracking] and [RunPhase.paused] — [phase]
/// distinguishes them so the UI can show the right controls/status.
class LiveRunActive extends LiveRunState {
  final RunPhase phase;
  final double? speedMps;
  final double accuracyMeters;
  final LiveMetrics metrics;

  const LiveRunActive({
    required this.phase,
    required this.speedMps,
    required this.accuracyMeters,
    required this.metrics,
  });
}

class LiveRunFinished extends LiveRunState {
  final LiveMetrics metrics;

  const LiveRunFinished({required this.metrics});
}

class LiveRunPermissionDenied extends LiveRunState {
  final bool forever;

  const LiveRunPermissionDenied({required this.forever});
}

class LiveRunServiceDisabled extends LiveRunState {
  const LiveRunServiceDisabled();
}
