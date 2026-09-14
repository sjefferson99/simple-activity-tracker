import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/units/units.dart';
import 'package:simple_activity_tracker/domain/models/live_metrics.dart';
import 'package:simple_activity_tracker/domain/models/split.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';
import 'package:simple_activity_tracker/features/live_run/metric_spec.dart';

MetricSpec _specFor(String id, ActivityMode mode) =>
    metricSpecsFor(mode).firstWhere((s) => s.id == id);

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
        elevationGainMeters: 100,
      );
      expect(spec.label(SpeedUnit.mph), 'Elevation gain (ft)');
      expect(spec.valueOf(metrics, null, SpeedUnit.mph), '328');
    });
  });
}
