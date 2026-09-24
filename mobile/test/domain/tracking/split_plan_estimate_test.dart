import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';
import 'package:simple_activity_tracker/domain/tracking/split_plan_estimate.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';

void main() {
  group('estimateSplit', () {
    test('distance split at a target gives a time', () {
      final e = estimateSplit(SplitKind.distanceKm, 1000, 1000 / 300);
      expect(e.distanceMeters, 1000);
      expect(e.durationSeconds, closeTo(300, 1e-9));
    });

    test('time split at a target gives a distance', () {
      final e = estimateSplit(SplitKind.timeMin, 90, 4);
      expect(e.durationSeconds, 90);
      expect(e.distanceMeters, closeTo(360, 1e-9));
    });

    test('no target leaves the derived dimension null', () {
      expect(
        estimateSplit(SplitKind.distanceMi, 400, null).durationSeconds,
        isNull,
      );
      expect(estimateSplit(SplitKind.timeMin, 60, null).distanceMeters, isNull);
    });
  });

  group('estimateCustomPlanTotals', () {
    test('sums both dimensions when every split has a target', () {
      const plan = SplitPlan(
        base: SplitPreference.defaultPreference,
        customSplits: [
          PlannedSplit(size: 1000, targetSpeedMps: 1000 / 300),
          PlannedSplit(size: 400, targetSpeedMps: 4),
        ],
      );
      final totals = estimateCustomPlanTotals(plan);
      expect(totals.distanceMeters, 1400);
      expect(totals.durationSeconds, closeTo(400, 1e-9));
      expect(totals.untargetedCount, 0);
    });

    test('distance plan: time is null when any split lacks a target', () {
      const plan = SplitPlan(
        base: SplitPreference.defaultPreference,
        customSplits: [
          PlannedSplit(size: 1000, targetSpeedMps: 4),
          PlannedSplit(size: 400),
        ],
      );
      final totals = estimateCustomPlanTotals(plan);
      expect(totals.distanceMeters, 1400);
      expect(totals.durationSeconds, isNull);
      expect(totals.untargetedCount, 1);
    });

    test('time plan: distance is null when any split lacks a target', () {
      const plan = SplitPlan(
        base: SplitPreference(kind: SplitKind.timeMin, value: 1),
        customSplits: [
          PlannedSplit(size: 90, targetSpeedMps: 4),
          PlannedSplit(size: 30),
        ],
      );
      final totals = estimateCustomPlanTotals(plan);
      expect(totals.durationSeconds, 120);
      expect(totals.distanceMeters, isNull);
      expect(totals.untargetedCount, 1);
    });
  });
}
