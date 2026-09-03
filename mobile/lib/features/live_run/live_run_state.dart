import '../../domain/models/live_metrics.dart';
import '../../domain/tracking/activity_mode.dart';
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

  /// The mode captured at start() for this run — the source of truth for
  /// which metric tiles/units to show, independent of the home screen
  /// toggle's live value (which the UI hides once a run is active, but the
  /// mode itself is also fixed for a run's whole duration — see
  /// LiveRunController.start()).
  final ActivityMode activityMode;

  const LiveRunActive({
    required this.phase,
    required this.speedMps,
    required this.accuracyMeters,
    required this.metrics,
    required this.activityMode,
  });
}

class LiveRunFinished extends LiveRunState {
  final LiveMetrics metrics;

  /// The mode the finished run was recorded under — see
  /// [LiveRunActive.activityMode].
  final ActivityMode activityMode;

  /// Where the exported copy of this run's GPX file was written, in
  /// human-readable form (e.g. "Downloads/SimpleActivityTracker"), for showing in the
  /// UI. Null while the export is still in flight, on a platform where it
  /// doesn't apply (iOS relies on Files-app visibility instead — see
  /// RunExportService), or if the copy failed — the run itself is never at
  /// risk either way, since export is a copy of the file already saved.
  final String? exportedTo;

  /// Null only if the run had no GPX file to sync (shouldn't happen in
  /// practice — stop() always has one by the time it builds this state).
  /// Lets the summary screen watch SyncService.statusChanges and RunStore
  /// for this specific run's upload/analysis progress.
  final String? clientRunId;

  const LiveRunFinished({
    required this.metrics,
    required this.activityMode,
    this.exportedTo,
    this.clientRunId,
  });

  LiveRunFinished copyWith({String? exportedTo}) => LiveRunFinished(
    metrics: metrics,
    activityMode: activityMode,
    exportedTo: exportedTo ?? this.exportedTo,
    clientRunId: clientRunId,
  );
}

class LiveRunPermissionDenied extends LiveRunState {
  final bool forever;

  const LiveRunPermissionDenied({required this.forever});
}

class LiveRunServiceDisabled extends LiveRunState {
  const LiveRunServiceDisabled();
}
