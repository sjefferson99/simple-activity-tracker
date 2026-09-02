import 'live_metrics.dart';

/// The phone's own numbers for a finished run — mirrors the server's
/// RunSummary schema exactly (docs/WEB-PLAN.md §5.3), including field names
/// and units (seconds/meters/m-per-second, not Duration/formatted strings),
/// so [toJson] can be sent to the server without any renaming at the call site.
class RunSummary {
  final String clientRunId;
  final DateTime startedAt;
  final DateTime endedAt;
  final double movingSeconds;
  final double distanceMeters;
  final double? avgSpeedMps;
  final List<RunSummarySplit> splits;
  final String sourcePlatform;
  final String sourceAppVersion;

  const RunSummary({
    required this.clientRunId,
    required this.startedAt,
    required this.endedAt,
    required this.movingSeconds,
    required this.distanceMeters,
    required this.avgSpeedMps,
    required this.splits,
    required this.sourcePlatform,
    required this.sourceAppVersion,
  });

  /// [metrics.elapsed] is already moving time, not wall-clock elapsed — see
  /// MetricsEngine — so it maps straight onto the server's `moving_seconds`.
  factory RunSummary.fromMetrics({
    required String clientRunId,
    required DateTime startedAt,
    required DateTime endedAt,
    required LiveMetrics metrics,
    required String sourcePlatform,
    required String sourceAppVersion,
  }) {
    return RunSummary(
      clientRunId: clientRunId,
      startedAt: startedAt,
      endedAt: endedAt,
      movingSeconds: metrics.elapsed.inMilliseconds / 1000,
      distanceMeters: metrics.distanceMeters,
      avgSpeedMps: metrics.avgSpeedMps,
      splits: [
        for (final split in metrics.completedSplits)
          RunSummarySplit(
            index: split.index,
            durationSeconds: split.duration.inMilliseconds / 1000,
            avgSpeedMps: split.avgSpeedMps,
          ),
      ],
      sourcePlatform: sourcePlatform,
      sourceAppVersion: sourceAppVersion,
    );
  }

  factory RunSummary.fromJson(Map<String, dynamic> json) {
    final source = json['source'] as Map<String, dynamic>;
    return RunSummary(
      clientRunId: json['client_run_id'] as String,
      startedAt: DateTime.parse(json['started_at'] as String),
      endedAt: DateTime.parse(json['ended_at'] as String),
      movingSeconds: (json['moving_seconds'] as num).toDouble(),
      distanceMeters: (json['distance_meters'] as num).toDouble(),
      avgSpeedMps: (json['avg_speed_mps'] as num?)?.toDouble(),
      splits: [
        for (final split in json['splits'] as List<dynamic>)
          RunSummarySplit.fromJson(split as Map<String, dynamic>),
      ],
      sourcePlatform: source['platform'] as String,
      sourceAppVersion: source['app_version'] as String,
    );
  }

  Map<String, dynamic> toJson() => {
        'client_run_id': clientRunId,
        'started_at': startedAt.toUtc().toIso8601String(),
        'ended_at': endedAt.toUtc().toIso8601String(),
        'moving_seconds': movingSeconds,
        'distance_meters': distanceMeters,
        'avg_speed_mps': avgSpeedMps,
        'splits': [for (final split in splits) split.toJson()],
        'source': {'platform': sourcePlatform, 'app_version': sourceAppVersion},
      };
}

class RunSummarySplit {
  final int index;
  final double durationSeconds;
  final double avgSpeedMps;

  const RunSummarySplit({
    required this.index,
    required this.durationSeconds,
    required this.avgSpeedMps,
  });

  factory RunSummarySplit.fromJson(Map<String, dynamic> json) => RunSummarySplit(
        index: json['index'] as int,
        durationSeconds: (json['duration_seconds'] as num).toDouble(),
        avgSpeedMps: (json['avg_speed_mps'] as num).toDouble(),
      );

  Map<String, dynamic> toJson() => {
        'index': index,
        'duration_seconds': durationSeconds,
        'avg_speed_mps': avgSpeedMps,
      };
}
