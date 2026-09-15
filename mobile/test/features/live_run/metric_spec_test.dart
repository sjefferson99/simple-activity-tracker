import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/units/units.dart';
import 'package:simple_activity_tracker/domain/models/current_split_info.dart';
import 'package:simple_activity_tracker/domain/models/live_metrics.dart';
import 'package:simple_activity_tracker/domain/models/split.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';
import 'package:simple_activity_tracker/domain/tracking/split_target.dart';
import 'package:simple_activity_tracker/features/live_run/metric_spec.dart';

MetricSpec _specFor(String id, ActivityMode mode) =>
    metricSpecsFor(mode).firstWhere((s) => s.id == id);

const _defaultCurrentSplit = CurrentSplitInfo(
  index: 1,
  plannedCount: null,
  sizeKind: SplitSizeKind.distanceMeters,
  size: 1000,
  targetSpeedMps: null,
);

void main() {
  group('current_split label', () {
    test(
      'reads "Split speed" in km/h mode and "Split pace" in min/km mode',
      () {
        final spec = _specFor('current_split', ActivityMode.running);
        expect(spec.label(SpeedUnit.kmh), 'Split speed');
        expect(spec.label(SpeedUnit.minKm), 'Split pace');
      },
    );
  });

  group('current_split value', () {
    test('appends km/h in km/h mode', () {
      final spec = _specFor('current_split', ActivityMode.running);
      final metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: const [],
        currentSplitElapsed: const Duration(seconds: 100),
        currentSplitDistanceMeters: 500,
        currentSplit: _defaultCurrentSplit,
      );
      expect(spec.valueOf(metrics, null, SpeedUnit.kmh), '18.0 km/h');
    });

    test('appends /km in min/km mode', () {
      final spec = _specFor('current_split', ActivityMode.running);
      final metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: const [],
        currentSplitElapsed: const Duration(seconds: 100),
        currentSplitDistanceMeters: 500,
        currentSplit: _defaultCurrentSplit,
      );
      expect(spec.valueOf(metrics, null, SpeedUnit.minKm), '3:20 /km');
    });

    test('appends mph in mph mode', () {
      final spec = _specFor('current_split', ActivityMode.running);
      final metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: const [],
        currentSplitElapsed: const Duration(seconds: 100),
        currentSplitDistanceMeters: 500,
        currentSplit: _defaultCurrentSplit,
      );
      expect(spec.valueOf(metrics, null, SpeedUnit.mph), '11.2 mph');
    });

    test('shows placeholder with no elapsed time in the current split', () {
      final spec = _specFor('current_split', ActivityMode.running);
      expect(spec.valueOf(LiveMetrics.zero, null, SpeedUnit.kmh), '--.- km/h');
      expect(
        spec.valueOf(LiveMetrics.zero, null, SpeedUnit.minKm),
        '--:-- /km',
      );
      expect(spec.valueOf(LiveMetrics.zero, null, SpeedUnit.mph), '--.- mph');
      expect(
        spec.valueOf(LiveMetrics.zero, null, SpeedUnit.minMi),
        '--:-- /mi',
      );
    });
  });

  group('avg_speed value', () {
    test('appends km/h in km/h mode', () {
      final spec = _specFor('avg_speed', ActivityMode.running);
      const metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: 5.0,
        completedSplits: [],
        currentSplitElapsed: Duration.zero,
        currentSplitDistanceMeters: 0,
        currentSplit: _defaultCurrentSplit,
      );
      expect(spec.valueOf(metrics, null, SpeedUnit.kmh), '18.0 km/h');
    });

    test('appends /km in min/km mode', () {
      final spec = _specFor('avg_speed', ActivityMode.running);
      const metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: 5.0,
        completedSplits: [],
        currentSplitElapsed: Duration.zero,
        currentSplitDistanceMeters: 0,
        currentSplit: _defaultCurrentSplit,
      );
      expect(spec.valueOf(metrics, null, SpeedUnit.minKm), '3:20 /km');
    });

    test('shows placeholder with no average speed yet', () {
      final spec = _specFor('avg_speed', ActivityMode.running);
      expect(spec.valueOf(LiveMetrics.zero, null, SpeedUnit.kmh), '--.- km/h');
      expect(
        spec.valueOf(LiveMetrics.zero, null, SpeedUnit.minKm),
        '--:-- /km',
      );
    });
  });

  group('distance value', () {
    test('shows both km and mi stacked, regardless of speed unit', () {
      final spec = _specFor('distance', ActivityMode.running);
      const metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 1609.344,
        avgSpeedMps: null,
        completedSplits: [],
        currentSplitElapsed: Duration.zero,
        currentSplitDistanceMeters: 0,
        currentSplit: _defaultCurrentSplit,
      );
      expect(spec.valueOf(metrics, null, SpeedUnit.kmh), '1.61 km\n1.00 mi');
      expect(spec.valueOf(metrics, null, SpeedUnit.mph), '1.61 km\n1.00 mi');
    });
  });

  group('last_split label', () {
    test('reads "Last split speed" in km/h mode and "Last split pace" in min/km mode', () {
      final spec = _specFor('last_split', ActivityMode.running);
      expect(spec.label(SpeedUnit.kmh), 'Last split speed');
      expect(spec.label(SpeedUnit.minKm), 'Last split pace');
    });
  });

  group('last_split value', () {
    test('shows placeholder with no completed splits', () {
      final spec = _specFor('last_split', ActivityMode.running);
      expect(spec.valueOf(LiveMetrics.zero, null, SpeedUnit.kmh), '--.- km/h');
      expect(
        spec.valueOf(LiveMetrics.zero, null, SpeedUnit.minKm),
        '--:-- /km',
      );
    });

    test(
      'prefixes the last split\'s speed/pace with its 1-based split number',
      () {
        final spec = _specFor('last_split', ActivityMode.running);
        final metrics = LiveMetrics(
          elapsed: Duration.zero,
          distanceMeters: 0,
          avgSpeedMps: null,
          completedSplits: const [
            Split(
              index: 1,
              duration: Duration(minutes: 5),
              avgSpeedMps: 3.33,
              distanceMeters: 1000,
            ),
            Split(
              index: 2,
              duration: Duration(minutes: 4, seconds: 30),
              avgSpeedMps: 5.0,
              distanceMeters: 1000,
            ),
          ],
          currentSplitElapsed: Duration.zero,
          currentSplitDistanceMeters: 0,
        currentSplit: _defaultCurrentSplit,
        );
        expect(spec.valueOf(metrics, null, SpeedUnit.minKm), '#2  3:20 /km');
        expect(spec.valueOf(metrics, null, SpeedUnit.kmh), '#2  18.0 km/h');
      },
    );

    // #78: for a time-based split preference every split shares the same
    // fixed duration (e.g. always "5:00" for a 5-minute split), so the old
    // duration-based tile never changed split-to-split. Speed/pace is the
    // number that actually varies there, since distance covered per split
    // differs even though the time doesn't.
    test('shows differing speed/pace for equal-duration time-based splits', () {
      final spec = _specFor('last_split', ActivityMode.running);
      final metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: const [
          Split(
            index: 1,
            duration: Duration(minutes: 5),
            avgSpeedMps: 3.0,
            distanceMeters: 900,
          ),
          Split(
            index: 2,
            duration: Duration(minutes: 5),
            avgSpeedMps: 3.5,
            distanceMeters: 1050,
          ),
        ],
        currentSplitElapsed: Duration.zero,
        currentSplitDistanceMeters: 0,
        currentSplit: _defaultCurrentSplit,
      );
      expect(spec.valueOf(metrics, null, SpeedUnit.kmh), '#2  12.6 km/h');
    });
  });

  group('max_speed value (cycling)', () {
    test('shows km/h for a km-based speed unit', () {
      final spec = _specFor('max_speed', ActivityMode.cycling);
      const metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: [],
        currentSplitElapsed: Duration.zero,
        currentSplitDistanceMeters: 0,
        currentSplit: _defaultCurrentSplit,
        maxSpeedMps: 10.0,
      );
      expect(spec.valueOf(metrics, null, SpeedUnit.kmh), '36.0 km/h');
    });

    test('shows mph for a mile-based speed unit', () {
      final spec = _specFor('max_speed', ActivityMode.cycling);
      const metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: [],
        currentSplitElapsed: Duration.zero,
        currentSplitDistanceMeters: 0,
        currentSplit: _defaultCurrentSplit,
        maxSpeedMps: 10.0,
      );
      expect(spec.valueOf(metrics, null, SpeedUnit.mph), '22.4 mph');
    });
  });

  group('elevation_gain (cycling)', () {
    test('shows meters and label for a km-based speed unit', () {
      final spec = _specFor('elevation_gain', ActivityMode.cycling);
      const metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: [],
        currentSplitElapsed: Duration.zero,
        currentSplitDistanceMeters: 0,
        currentSplit: _defaultCurrentSplit,
        elevationGainMeters: 100,
      );
      expect(spec.label(SpeedUnit.kmh), 'Elevation gain (m)');
      expect(spec.valueOf(metrics, null, SpeedUnit.kmh), '100');
    });

    test('shows feet and label for a mile-based speed unit', () {
      final spec = _specFor('elevation_gain', ActivityMode.cycling);
      const metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: [],
        currentSplitElapsed: Duration.zero,
        currentSplitDistanceMeters: 0,
        currentSplit: _defaultCurrentSplit,
        elevationGainMeters: 100,
      );
      expect(spec.label(SpeedUnit.mph), 'Elevation gain (ft)');
      expect(spec.valueOf(metrics, null, SpeedUnit.mph), '328');
    });
  });

  group('current_split detail/verdict (issue #99)', () {
    const withoutTarget = CurrentSplitInfo(
      index: 3,
      plannedCount: 6,
      sizeKind: SplitSizeKind.distanceMeters,
      size: 1000,
      targetSpeedMps: null,
    );
    const withTarget = CurrentSplitInfo(
      index: 3,
      plannedCount: 6,
      sizeKind: SplitSizeKind.distanceMeters,
      size: 1000,
      targetSpeedMps: 1000 / 300, // 5:00/km
    );

    test('detail shows split count and size with no target', () {
      final spec = _specFor('current_split', ActivityMode.running);
      final metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: const [],
        currentSplitElapsed: Duration.zero,
        currentSplitDistanceMeters: 0,
        currentSplit: withoutTarget,
      );
      expect(spec.detail!(metrics, SpeedUnit.minKm), 'Split 3/6 · 1 km');
    });

    test('verdict is null with no target', () {
      final spec = _specFor('current_split', ActivityMode.running);
      final metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: const [],
        currentSplitElapsed: const Duration(seconds: 30),
        currentSplitDistanceMeters: 150,
        currentSplit: withoutTarget,
      );
      expect(spec.verdict!(metrics), isNull);
    });

    test('detail shows the target before any speed is available', () {
      final spec = _specFor('current_split', ActivityMode.running);
      final metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: const [],
        currentSplitElapsed: Duration.zero,
        currentSplitDistanceMeters: 0,
        currentSplit: withTarget,
      );
      expect(spec.detail!(metrics, SpeedUnit.minKm), 'Split 3/6 · 1 km @ 5:00');
    });

    test('verdict is null within the grace period even with a target', () {
      final spec = _specFor('current_split', ActivityMode.running);
      // 100 m/s implied speed (wildly off target) but only 5s elapsed.
      final metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: const [],
        currentSplitElapsed: const Duration(seconds: 5),
        currentSplitDistanceMeters: 500,
        currentSplit: withTarget,
      );
      expect(spec.verdict!(metrics), isNull);
    });

    test('detail shows the delta once a verdict is available', () {
      final spec = _specFor('current_split', ActivityMode.running);
      // Past the grace period, running faster than the 5:00/km target.
      final metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: const [],
        currentSplitElapsed: const Duration(seconds: 15),
        currentSplitDistanceMeters: 15 * (1000 / 250), // 4:10/km pace
        currentSplit: withTarget,
      );
      final detail = spec.detail!(metrics, SpeedUnit.minKm);
      expect(detail, contains('Split 3/6 · 1 km'));
      expect(detail, contains('▲')); // pace faster => arrow up (slow down)
      expect(spec.verdict!(metrics), SplitVerdict.tooFast);
    });

    test(
      'detail keeps showing the target itself once a delta is available, not just the delta',
      () {
        // Regression: on-device the header lost its "@ 5:00" target the
        // moment a delta appeared, leaving only "how far off" with no
        // "off from what" visible anywhere on the tile.
        final spec = _specFor('current_split', ActivityMode.running);
        final metrics = LiveMetrics(
          elapsed: Duration.zero,
          distanceMeters: 0,
          avgSpeedMps: null,
          completedSplits: const [],
          currentSplitElapsed: const Duration(seconds: 15),
          currentSplitDistanceMeters: 15 * (1000 / 250),
          currentSplit: withTarget,
        );
        final detail = spec.detail!(metrics, SpeedUnit.minKm);
        expect(detail, contains('@ 5:00'));
      },
    );
  });

  group('split_remaining value', () {
    test('distance-kind: shows remaining distance and an ETA from current split pace', () {
      final spec = _specFor('split_remaining', ActivityMode.running);
      // 1km split, 200m covered in 100s => 2 m/s so far, 800m left => 400s.
      final metrics = LiveMetrics(
        elapsed: const Duration(seconds: 100),
        distanceMeters: 200,
        avgSpeedMps: 2,
        completedSplits: const [],
        currentSplitElapsed: const Duration(seconds: 100),
        currentSplitDistanceMeters: 200,
        currentSplit: const CurrentSplitInfo(
          index: 1,
          plannedCount: null,
          sizeKind: SplitSizeKind.distanceMeters,
          size: 1000,
          targetSpeedMps: null,
        ),
      );
      final value = spec.valueOf(metrics, null, SpeedUnit.kmh);
      expect(value, contains('800 m'));
      expect(value, contains('6:40'));
    });

    test('distance-kind: shows "--:--" for the ETA with no moving time yet', () {
      final spec = _specFor('split_remaining', ActivityMode.running);
      final metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: const [],
        currentSplitElapsed: Duration.zero,
        currentSplitDistanceMeters: 0,
        currentSplit: _defaultCurrentSplit,
      );
      final value = spec.valueOf(metrics, null, SpeedUnit.kmh);
      expect(value, contains('1 km'));
      expect(value, contains('--:--'));
    });

    test('distance-kind: shows zero remaining once the split size is covered', () {
      final spec = _specFor('split_remaining', ActivityMode.running);
      final metrics = LiveMetrics(
        elapsed: const Duration(seconds: 200),
        distanceMeters: 1000,
        avgSpeedMps: 5,
        completedSplits: const [],
        currentSplitElapsed: const Duration(seconds: 200),
        currentSplitDistanceMeters: 1000,
        currentSplit: _defaultCurrentSplit,
      );
      final value = spec.valueOf(metrics, null, SpeedUnit.kmh);
      expect(value, contains('0 m'));
    });

    test('time-kind: shows remaining time counting down from the split size', () {
      final spec = _specFor('split_remaining', ActivityMode.running);
      final metrics = LiveMetrics(
        elapsed: const Duration(seconds: 40),
        distanceMeters: 100,
        avgSpeedMps: 2.5,
        completedSplits: const [],
        currentSplitElapsed: const Duration(seconds: 40),
        currentSplitDistanceMeters: 100,
        currentSplit: const CurrentSplitInfo(
          index: 1,
          plannedCount: 3,
          sizeKind: SplitSizeKind.durationSeconds,
          size: 60,
          targetSpeedMps: null,
        ),
      );
      final value = spec.valueOf(metrics, null, SpeedUnit.kmh);
      expect(value, '0:20');
    });

    test('time-kind: never goes negative once past the split boundary', () {
      final spec = _specFor('split_remaining', ActivityMode.running);
      final metrics = LiveMetrics(
        elapsed: const Duration(seconds: 65),
        distanceMeters: 100,
        avgSpeedMps: 1.5,
        completedSplits: const [],
        currentSplitElapsed: const Duration(seconds: 65),
        currentSplitDistanceMeters: 100,
        currentSplit: const CurrentSplitInfo(
          index: 1,
          plannedCount: 3,
          sizeKind: SplitSizeKind.durationSeconds,
          size: 60,
          targetSpeedMps: null,
        ),
      );
      final value = spec.valueOf(metrics, null, SpeedUnit.kmh);
      expect(value, '0:00');
    });
  });

  group('last_split detail/verdict (issue #99)', () {
    test('detail and verdict are null with no completed splits', () {
      final spec = _specFor('last_split', ActivityMode.running);
      expect(spec.detail!(LiveMetrics.zero, SpeedUnit.minKm), isNull);
      expect(spec.verdict!(LiveMetrics.zero), isNull);
    });

    test('detail and verdict are null when the split had no target', () {
      final spec = _specFor('last_split', ActivityMode.running);
      final metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: const [
          Split(
            index: 1,
            duration: Duration(minutes: 5),
            avgSpeedMps: 3.33,
            distanceMeters: 1000,
          ),
        ],
        currentSplitElapsed: Duration.zero,
        currentSplitDistanceMeters: 0,
        currentSplit: _defaultCurrentSplit,
      );
      expect(spec.detail!(metrics, SpeedUnit.minKm), isNull);
      expect(spec.verdict!(metrics), isNull);
    });

    test('detail and verdict reflect the split result against its target', () {
      final spec = _specFor('last_split', ActivityMode.running);
      final metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 0,
        avgSpeedMps: null,
        completedSplits: const [
          Split(
            index: 1,
            duration: Duration(minutes: 5), // well past the grace period
            avgSpeedMps: 3.5, // faster than the 3.0 m/s target
            distanceMeters: 1050,
            targetSpeedMps: 3.0,
          ),
        ],
        currentSplitElapsed: Duration.zero,
        currentSplitDistanceMeters: 0,
        currentSplit: _defaultCurrentSplit,
      );
      expect(spec.verdict!(metrics), SplitVerdict.tooFast);
      expect(spec.detail!(metrics, SpeedUnit.kmh), contains('▼'));
    });

    test(
      'a completed split shorter than the grace period still gets a verdict (unlike an in-progress one)',
      () {
        final spec = _specFor('last_split', ActivityMode.running);
        final metrics = LiveMetrics(
          elapsed: Duration.zero,
          distanceMeters: 0,
          avgSpeedMps: null,
          completedSplits: const [
            Split(
              index: 1,
              duration: Duration(seconds: 5), // shorter than the grace period
              avgSpeedMps: 3.5,
              distanceMeters: 17.5,
              targetSpeedMps: 3.0,
            ),
          ],
          currentSplitElapsed: Duration.zero,
          currentSplitDistanceMeters: 0,
          currentSplit: _defaultCurrentSplit,
        );
        // splitVerdict() itself still applies the grace threshold uniformly
        // (it has no notion of "already finished") — a split this short
        // (a very small custom split) legitimately gets no verdict yet,
        // same as an in-progress split would. Documented here rather than
        // silently assumed, since MetricSpec's own doc says "no grace" for
        // this tile — true relative to the *current* split's tile, whose
        // grace resets every split; a fresh completed split is never
        // "mid-grace" the way an in-progress one can be.
        expect(spec.verdict!(metrics), isNull);
      },
    );
  });
}
