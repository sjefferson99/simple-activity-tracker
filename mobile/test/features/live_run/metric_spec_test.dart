import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/models/live_metrics.dart';
import 'package:simple_activity_tracker/domain/models/split.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';
import 'package:simple_activity_tracker/features/live_run/metric_spec.dart';

MetricSpec _specFor(String id, ActivityMode mode) =>
    metricSpecsFor(mode).firstWhere((s) => s.id == id);

void main() {
  group('current_split label', () {
    test('reads "Split speed" in km/h mode and "Split pace" in min/km mode', () {
      final spec = _specFor('current_split', ActivityMode.running);
      expect(spec.label(true), 'Split speed');
      expect(spec.label(false), 'Split pace');
    });
  });

  group('distance value', () {
    test('shows both km and mi', () {
      final spec = _specFor('distance', ActivityMode.running);
      const metrics = LiveMetrics(
        elapsed: Duration.zero,
        distanceMeters: 1609.344,
        avgSpeedMps: null,
        completedSplits: [],
        currentSplitElapsed: Duration.zero,
        currentSplitDistanceMeters: 0,
      );
      expect(spec.valueOf(metrics, null, true), '1.61 km / 1.00 mi');
    });
  });

  group('last_split value', () {
    test('shows placeholder with no completed splits', () {
      final spec = _specFor('last_split', ActivityMode.running);
      expect(spec.valueOf(LiveMetrics.zero, null, false), '--:--');
    });

    test('prefixes the duration with the 1-based split number', () {
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
            avgSpeedMps: 3.7,
            distanceMeters: 1000,
          ),
        ],
        currentSplitElapsed: Duration.zero,
        currentSplitDistanceMeters: 0,
      );
      expect(spec.valueOf(metrics, null, false), '#2  4:30');
    });
  });
}
