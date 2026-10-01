import '../../../domain/models/live_metrics.dart';
import '../../../domain/models/track_point.dart';
import '../../../domain/tracking/activity_mode.dart';
import '../../../domain/tracking/split_plan.dart';
import '../tolerant_json.dart';
import 'split_config_dto.dart';

/// Wire shapes for live tracking and sharing (issue #130, API level 2 —
/// docs/LIVE-TRACKING-PLAN.md §2.3). Every response is read tolerantly
/// (docs/VERSIONING.md §3.3): a missing or mistyped field falls back to a
/// default rather than throwing.

/// The server's view of a live session: the next point index it expects
/// (the phone resends from there) and the session's state.
class LiveSessionStateDto {
  final int nextIndex;
  final String state;

  const LiveSessionStateDto({required this.nextIndex, required this.state});

  factory LiveSessionStateDto.fromJson(Map<String, dynamic> json) => LiveSessionStateDto(
    nextIndex: readInt(json, 'next_index') ?? 0,
    state: readString(json, 'state') ?? 'active',
  );
}

/// `PUT /api/v1/live/{client_activity_id}` body.
class LiveSessionRequestDto {
  final ActivityMode activityMode;
  final DateTime startedAt;
  final SplitPlan? splitPlan;

  const LiveSessionRequestDto({
    required this.activityMode,
    required this.startedAt,
    this.splitPlan,
  });

  Map<String, dynamic> toJson() => {
    'activity_type': activityMode.name,
    'started_at': startedAt.toUtc().toIso8601String(),
    // Same rule as the GPX: a split plan only belongs to an activity that
    // has splits (issue #99 D8 / #109).
    if (splitPlan != null && activityMode.supportsSplits)
      'split_plan': splitPlanWireJson(splitPlan!),
  };
}

/// One point as uploaded. [segment] increments on each resume after a pause,
/// like the GPX's track segments.
class LivePointDto {
  final TrackPoint point;
  final int segment;

  const LivePointDto(this.point, this.segment);

  // Optional values outside the server's accepted ranges (LivePointIn) are
  // left out rather than sent: one odd GPS reading must not get the whole
  // batch rejected.
  static bool _within(double? value, double min, double max) =>
      value != null && value.isFinite && value >= min && value <= max;

  Map<String, dynamic> toJson() => {
    't': point.timestamp.toUtc().toIso8601String(),
    'lat': point.latitude,
    'lon': point.longitude,
    if (_within(point.elevationMeters, -1000, 10000)) 'ele': point.elevationMeters,
    if (point.hasAccuracy && _within(point.accuracyMeters, 0, 100000))
      'accuracy': point.accuracyMeters,
    if (point.hasSpeed && _within(point.speedMps, 0, 1000)) 'speed': point.speedMps,
    'segment': segment,
  };
}

/// `POST /api/v1/live/{client_activity_id}/points` body. [metrics] is what
/// the phone shows right now; the live page displays it verbatim.
class LivePointsRequestDto {
  final int fromIndex;
  final List<LivePointDto> points;
  final LiveMetrics? metrics;
  final double? currentSpeedMps;

  /// `active`, `paused` or `finished`.
  final String state;

  const LivePointsRequestDto({
    required this.fromIndex,
    required this.points,
    required this.state,
    this.metrics,
    this.currentSpeedMps,
  });

  Map<String, dynamic> toJson() => {
    'from_index': fromIndex,
    'points': [for (final point in points) point.toJson()],
    'state': state,
    if (metrics != null) 'metrics': _metricsJson(metrics!, currentSpeedMps),
  };

  static double? _finite(double? value) =>
      value != null && value.isFinite && value >= 0 ? value : null;

  static Map<String, dynamic> _metricsJson(LiveMetrics m, double? currentSpeedMps) => {
    'distance_meters': _finite(m.distanceMeters) ?? 0,
    'elapsed_seconds': m.elapsedWallClock.inMilliseconds / 1000,
    'moving_seconds': m.elapsed.inMilliseconds / 1000,
    'avg_speed_mps': _finite(m.avgSpeedMps),
    'current_speed_mps': _finite(currentSpeedMps),
    'splits': [
      for (final split in m.completedSplits)
        {
          'index': split.index,
          'duration_seconds': split.duration.inMilliseconds / 1000,
          'avg_speed_mps': _finite(split.avgSpeedMps) ?? 0,
          'distance_m': _finite(split.distanceMeters),
          if (_finite(split.targetSpeedMps) != null) 'target_speed_mps': split.targetSpeedMps,
        },
    ],
  };
}

/// Another user on the server, as the user directory shows them: never an
/// email (plan D5).
class UserDirectoryEntryDto {
  final String id;
  final String displayName;

  const UserDirectoryEntryDto({required this.id, required this.displayName});

  static List<UserDirectoryEntryDto> listFromJson(Map<String, dynamic> json) => [
    for (final user in readMapList(json, 'users'))
      if (readString(user, 'id') case final String id)
        UserDirectoryEntryDto(id: id, displayName: readString(user, 'display_name') ?? id),
  ];

  Map<String, dynamic> toJson() => {'id': id, 'display_name': displayName};
}

/// One of the caller's own grants.
class ShareDto {
  final String viewerId;
  final String displayName;
  final bool canViewLive;
  final bool canViewHistory;

  const ShareDto({
    required this.viewerId,
    required this.displayName,
    required this.canViewLive,
    required this.canViewHistory,
  });
}

/// `GET /api/v1/me/shares` and `PUT /api/v1/me/live-sharing` response.
class MySharesDto {
  final bool liveSharingPaused;
  final List<ShareDto> shares;

  const MySharesDto({required this.liveSharingPaused, required this.shares});

  factory MySharesDto.fromJson(Map<String, dynamic> json) => MySharesDto(
    liveSharingPaused: json['live_sharing_paused'] == true,
    shares: [
      for (final share in readMapList(json, 'shares'))
        if (readString(share, 'viewer_id') case final String viewerId)
          ShareDto(
            viewerId: viewerId,
            displayName: readString(share, 'display_name') ?? viewerId,
            canViewLive: share['can_view_live'] == true,
            canViewHistory: share['can_view_history'] == true,
          ),
    ],
  );

  Set<String> get liveViewerIds => {
    for (final share in shares)
      if (share.canViewLive) share.viewerId,
  };
}

/// `PUT /api/v1/me/live-sharing` body: the phone's whole live-sharing
/// setting as one idempotent document, so a change made offline is replayed
/// as-is once the phone is back online (last write wins).
class LiveSharingRequestDto {
  final bool liveSharingPaused;
  final Set<String> liveViewerIds;

  const LiveSharingRequestDto({required this.liveSharingPaused, required this.liveViewerIds});

  Map<String, dynamic> toJson() => {
    'live_sharing_paused': liveSharingPaused,
    'live_viewer_ids': liveViewerIds.toList()..sort(),
  };

  factory LiveSharingRequestDto.fromJson(Map<String, dynamic> json) => LiveSharingRequestDto(
    liveSharingPaused: json['live_sharing_paused'] == true,
    liveViewerIds: {
      for (final id in (json['live_viewer_ids'] as List<dynamic>? ?? const []))
        if (id is String) id,
    },
  );

  @override
  bool operator ==(Object other) =>
      other is LiveSharingRequestDto &&
      other.liveSharingPaused == liveSharingPaused &&
      other.liveViewerIds.length == liveViewerIds.length &&
      other.liveViewerIds.containsAll(liveViewerIds);

  @override
  int get hashCode => Object.hash(liveSharingPaused, Object.hashAllUnordered(liveViewerIds));
}
