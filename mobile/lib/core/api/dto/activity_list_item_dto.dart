import 'tag_dto.dart';

/// Mirrors the server's ActivityListItem schema — one row of GET
/// /api/v1/activities (issue #101). Note `distanceMeters`/`movingSeconds`
/// here come from the phone's own uploaded `client_summary`, not the
/// server's analysed distance (unlike the web app's richer `/activities`
/// list from #75/#76) — this endpoint is deliberately the plainer one, see
/// docs/ACTIVITY-HISTORY-PLAN.md D2.
class ActivityListItemDto {
  final String id;
  final String activityType;
  final DateTime startedAt;
  final DateTime endedAt;
  final String? title;
  final double distanceMeters;
  final double movingSeconds;
  final List<TagDto> tags;

  const ActivityListItemDto({
    required this.id,
    required this.activityType,
    required this.startedAt,
    required this.endedAt,
    required this.title,
    required this.distanceMeters,
    required this.movingSeconds,
    required this.tags,
  });

  factory ActivityListItemDto.fromJson(Map<String, dynamic> json) => ActivityListItemDto(
    id: json['id'] as String,
    activityType: json['activity_type'] as String,
    startedAt: DateTime.parse(json['started_at'] as String),
    endedAt: DateTime.parse(json['ended_at'] as String),
    title: json['title'] as String?,
    distanceMeters: (json['distance_meters'] as num).toDouble(),
    movingSeconds: (json['moving_seconds'] as num).toDouble(),
    tags: (json['tags'] as List<dynamic>)
        .map((tag) => TagDto.fromJson(tag as Map<String, dynamic>))
        .toList(),
  );
}

/// Mirrors the server's ActivityListResponse schema — one page of results.
/// `nextCursor` is opaque (pass back verbatim as the next request's cursor);
/// null means there is no further page.
class ActivityListResponseDto {
  final List<ActivityListItemDto> activities;
  final String? nextCursor;

  const ActivityListResponseDto({required this.activities, required this.nextCursor});

  factory ActivityListResponseDto.fromJson(Map<String, dynamic> json) => ActivityListResponseDto(
    activities: (json['activities'] as List<dynamic>)
        .map((item) => ActivityListItemDto.fromJson(item as Map<String, dynamic>))
        .toList(),
    nextCursor: json['next_cursor'] as String?,
  );
}
