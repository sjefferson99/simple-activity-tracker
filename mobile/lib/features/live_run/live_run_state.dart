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

  /// Where the exported copy of this run's GPX file was written, in
  /// human-readable form (e.g. "Downloads/SimpleRunner"), for showing in the
  /// UI. Null while the export is still in flight, on a platform where it
  /// doesn't apply (iOS relies on Files-app visibility instead — see
  /// RunExportService), or if the copy failed — the run itself is never at
  /// risk either way, since export is a copy of the file already saved.
  final String? exportedTo;

  const LiveRunFinished({required this.metrics, this.exportedTo});

  LiveRunFinished copyWith({String? exportedTo}) => LiveRunFinished(
        metrics: metrics,
        exportedTo: exportedTo ?? this.exportedTo,
      );
}

class LiveRunPermissionDenied extends LiveRunState {
  final bool forever;

  const LiveRunPermissionDenied({required this.forever});
}

class LiveRunServiceDisabled extends LiveRunState {
  const LiveRunServiceDisabled();
}
