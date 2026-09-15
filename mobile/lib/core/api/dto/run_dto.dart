import 'analysis_dto.dart';
import 'split_plan_dto.dart';
import 'tag_dto.dart';

/// Mirrors the server's ActivityOut schema — the full activity record as the
/// server sees it, returned from upload, GET /activities/{id}, and (once
/// analysis is done) linked to from the post-Stop summary screen (issue #97).
///
/// The Dart field is still named `clientRunId` (not renamed per the
/// activities-terminology scope) but it's parsed from the wire's
/// `client_activity_id` — see [fromJson]. `deviceName`/`tags`/`splitPlan` were
/// added for issue #101's activity detail screen; `created_at`/`updated_at`
/// are left unmapped since no mobile UI needs them yet.
class RunDto {
  final String id;
  final String clientRunId;
  final DateTime startedAt;
  final DateTime endedAt;
  final String activityType;
  final String? title;
  final String? notes;
  final String? deviceName;
  final Map<String, dynamic> clientSummary;
  final String sourcePlatform;
  final String sourceAppVersion;
  final AnalysisDto analysis;
  final List<TagDto> tags;
  final SplitPlanDto? splitPlan;

  const RunDto({
    required this.id,
    required this.clientRunId,
    required this.startedAt,
    required this.endedAt,
    required this.activityType,
    required this.title,
    required this.notes,
    required this.deviceName,
    required this.clientSummary,
    required this.sourcePlatform,
    required this.sourceAppVersion,
    required this.analysis,
    required this.tags,
    required this.splitPlan,
  });

  factory RunDto.fromJson(Map<String, dynamic> json) => RunDto(
    id: json['id'] as String,
    clientRunId: json['client_activity_id'] as String,
    startedAt: DateTime.parse(json['started_at'] as String),
    endedAt: DateTime.parse(json['ended_at'] as String),
    activityType: json['activity_type'] as String,
    title: json['title'] as String?,
    notes: json['notes'] as String?,
    deviceName: json['device_name'] as String?,
    clientSummary: json['client_summary'] as Map<String, dynamic>,
    sourcePlatform: json['source_platform'] as String,
    sourceAppVersion: json['source_app_version'] as String,
    analysis: AnalysisDto.fromJson(json['analysis'] as Map<String, dynamic>),
    tags: (json['tags'] as List<dynamic>? ?? const [])
        .map((tag) => TagDto.fromJson(tag as Map<String, dynamic>))
        .toList(),
    splitPlan: json['split_plan'] == null
        ? null
        : SplitPlanDto.fromJson(json['split_plan'] as Map<String, dynamic>),
  );
}
