import '../tracking/activity_mode.dart';
import 'run_summary.dart';
import 'sync_status.dart';

/// One finished run's sync bookkeeping: the summary already uploaded (or
/// about to be), where its GPX file lives, and how far along the upload is.
/// Persisted as a JSON sidecar next to the GPX file — see FileRunStore.
class RunRecord {
  final String clientRunId;
  final String gpxPath;
  final ActivityMode activityMode;
  final RunSummary summary;
  final SyncStatus syncStatus;

  /// The full analysis result once the server has computed it (§5.4),
  /// cached here so the summary screen's Insights section survives an app
  /// restart without re-fetching. Null until fetched.
  final Map<String, dynamic>? analysisResult;

  const RunRecord({
    required this.clientRunId,
    required this.gpxPath,
    required this.activityMode,
    required this.summary,
    required this.syncStatus,
    this.analysisResult,
  });

  RunRecord copyWith({
    SyncStatus? syncStatus,
    Map<String, dynamic>? analysisResult,
  }) => RunRecord(
    clientRunId: clientRunId,
    gpxPath: gpxPath,
    activityMode: activityMode,
    summary: summary,
    syncStatus: syncStatus ?? this.syncStatus,
    analysisResult: analysisResult ?? this.analysisResult,
  );

  /// `activityMode` defaults to [ActivityMode.running] when reading an older
  /// sidecar written before this field existed, so an app update doesn't
  /// break parsing of runs already queued on disk.
  factory RunRecord.fromJson(Map<String, dynamic> json) => RunRecord(
    clientRunId: json['clientRunId'] as String,
    gpxPath: json['gpxPath'] as String,
    activityMode: ActivityMode.values.firstWhere(
      (m) => m.name == json['activityMode'] as String?,
      orElse: () => ActivityMode.running,
    ),
    summary: RunSummary.fromJson(json['summary'] as Map<String, dynamic>),
    syncStatus: SyncStatus.fromJson(json['syncStatus'] as Map<String, dynamic>),
    analysisResult: json['analysisResult'] as Map<String, dynamic>?,
  );

  Map<String, dynamic> toJson() => {
    'clientRunId': clientRunId,
    'gpxPath': gpxPath,
    'activityMode': activityMode.name,
    'summary': summary.toJson(),
    'syncStatus': syncStatus.toJson(),
    'analysisResult': analysisResult,
  };
}
