import 'analysis_dto.dart';

/// Mirrors the server's ActivityOut schema — the full activity record as the
/// server sees it, returned from upload and GET /activities/{id}.
///
/// The Dart field is still named `clientRunId` (not renamed per the
/// activities-terminology scope) but it's parsed from the wire's
/// `client_activity_id` — see [fromJson].
class RunDto {
  final String id;
  final String clientRunId;
  final DateTime startedAt;
  final DateTime endedAt;
  final String activityType;
  final String? title;
  final String? notes;
  final Map<String, dynamic> clientSummary;
  final String sourcePlatform;
  final String sourceAppVersion;
  final AnalysisDto analysis;

  const RunDto({
    required this.id,
    required this.clientRunId,
    required this.startedAt,
    required this.endedAt,
    required this.activityType,
    required this.title,
    required this.notes,
    required this.clientSummary,
    required this.sourcePlatform,
    required this.sourceAppVersion,
    required this.analysis,
  });

  factory RunDto.fromJson(Map<String, dynamic> json) => RunDto(
    id: json['id'] as String,
    clientRunId: json['client_activity_id'] as String,
    startedAt: DateTime.parse(json['started_at'] as String),
    endedAt: DateTime.parse(json['ended_at'] as String),
    activityType: json['activity_type'] as String,
    title: json['title'] as String?,
    notes: json['notes'] as String?,
    clientSummary: json['client_summary'] as Map<String, dynamic>,
    sourcePlatform: json['source_platform'] as String,
    sourceAppVersion: json['source_app_version'] as String,
    analysis: AnalysisDto.fromJson(json['analysis'] as Map<String, dynamic>),
  );
}
