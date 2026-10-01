import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/dto/live_dto.dart';
import 'package:simple_activity_tracker/domain/models/current_split_info.dart';
import 'package:simple_activity_tracker/domain/models/live_metrics.dart';
import 'package:simple_activity_tracker/domain/models/split.dart';
import 'package:simple_activity_tracker/domain/models/track_point.dart';

void main() {
  test('a point carries its segment and drops values the server would reject', () {
    final json = LivePointDto(
      TrackPoint(
        latitude: 51.5,
        longitude: -0.12,
        elevationMeters: 99999, // nonsense altitude
        timestamp: DateTime.utc(2026, 1, 1, 7),
        accuracyMeters: double.infinity,
        speedMps: 3.1,
        hasSpeed: true,
      ),
      2,
    ).toJson();
    expect(json, {
      't': '2026-01-01T07:00:00.000Z',
      'lat': 51.5,
      'lon': -0.12,
      'speed': 3.1,
      'segment': 2,
    });
  });

  test('a speed the platform never measured is not sent', () {
    final json = LivePointDto(
      TrackPoint(latitude: 1, longitude: 2, timestamp: DateTime.utc(2026), accuracyMeters: 5, speedMps: 0),
      0,
    ).toJson();
    expect(json.containsKey('speed'), isFalse);
    expect(json['accuracy'], 5);
  });

  test('metrics: wall-clock time, moving time and completed splits', () {
    const metrics = LiveMetrics(
      elapsed: Duration(seconds: 390),
      elapsedWallClock: Duration(seconds: 400),
      distanceMeters: 1234.5,
      avgSpeedMps: 3.1,
      completedSplits: [
        Split(
          index: 1,
          duration: Duration(seconds: 320),
          avgSpeedMps: 3.125,
          distanceMeters: 1000,
          targetSpeedMps: 3.0,
        ),
      ],
      currentSplitElapsed: Duration.zero,
      currentSplitDistanceMeters: 0,
      currentSplit: CurrentSplitInfo(
        index: 2,
        plannedCount: null,
        sizeKind: SplitSizeKind.distanceMeters,
        size: 1000,
        targetSpeedMps: null,
      ),
    );
    final json = const LivePointsRequestDto(
      fromIndex: 4,
      points: [],
      state: 'paused',
      metrics: metrics,
      currentSpeedMps: double.nan,
    ).toJson();
    expect(json['from_index'], 4);
    expect(json['state'], 'paused');
    expect(json['metrics'], {
      'distance_meters': 1234.5,
      'elapsed_seconds': 400.0,
      'moving_seconds': 390.0,
      'avg_speed_mps': 3.1,
      'current_speed_mps': null,
      'splits': [
        {
          'index': 1,
          'duration_seconds': 320.0,
          'avg_speed_mps': 3.125,
          'distance_m': 1000.0,
          'target_speed_mps': 3.0,
        },
      ],
    });
  });

  test('state responses are read tolerantly', () {
    final state = LiveSessionStateDto.fromJson({'next_index': 12.0, 'extra': true});
    expect(state.nextIndex, 12);
    expect(state.state, 'active');
  });

  test('a sharing setting compares by content, whatever the id order', () {
    expect(
      const LiveSharingRequestDto(liveSharingPaused: false, liveViewerIds: {'a', 'b'}),
      const LiveSharingRequestDto(liveSharingPaused: false, liveViewerIds: {'b', 'a'}),
    );
    expect(
      const LiveSharingRequestDto(liveSharingPaused: false, liveViewerIds: {'a'}),
      isNot(const LiveSharingRequestDto(liveSharingPaused: true, liveViewerIds: {'a'})),
    );
  });
}
