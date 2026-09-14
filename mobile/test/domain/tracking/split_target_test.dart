import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/tracking/split_target.dart';

void main() {
  group('splitVerdict', () {
    const target = 3.0; // m/s
    const pastGrace = Duration(seconds: 15);

    test('returns null when there is no target', () {
      expect(
        splitVerdict(
          avgSpeedMps: 3.0,
          targetSpeedMps: null,
          elapsedInSplit: pastGrace,
        ),
        isNull,
      );
    });

    test('returns null when there is no speed yet', () {
      expect(
        splitVerdict(
          avgSpeedMps: null,
          targetSpeedMps: target,
          elapsedInSplit: pastGrace,
        ),
        isNull,
      );
    });

    test('returns null within the grace period', () {
      expect(
        splitVerdict(
          avgSpeedMps: 100.0, // wildly off target, but still within grace
          targetSpeedMps: target,
          elapsedInSplit: splitVerdictGrace - const Duration(seconds: 1),
        ),
        isNull,
      );
    });

    test('returns onTarget exactly at the target speed', () {
      expect(
        splitVerdict(
          avgSpeedMps: target,
          targetSpeedMps: target,
          elapsedInSplit: pastGrace,
        ),
        SplitVerdict.onTarget,
      );
    });

    test('returns onTarget just inside the +5% boundary', () {
      expect(
        splitVerdict(
          avgSpeedMps: target * (1 + splitTargetTolerance) - 0.0001,
          targetSpeedMps: target,
          elapsedInSplit: pastGrace,
        ),
        SplitVerdict.onTarget,
      );
    });

    test('returns tooFast just outside the +5% boundary', () {
      expect(
        splitVerdict(
          avgSpeedMps: target * (1 + splitTargetTolerance) + 0.0001,
          targetSpeedMps: target,
          elapsedInSplit: pastGrace,
        ),
        SplitVerdict.tooFast,
      );
    });

    test('returns onTarget just inside the -5% boundary', () {
      expect(
        splitVerdict(
          avgSpeedMps: target * (1 - splitTargetTolerance) + 0.0001,
          targetSpeedMps: target,
          elapsedInSplit: pastGrace,
        ),
        SplitVerdict.onTarget,
      );
    });

    test('returns tooSlow just outside the -5% boundary', () {
      expect(
        splitVerdict(
          avgSpeedMps: target * (1 - splitTargetTolerance) - 0.0001,
          targetSpeedMps: target,
          elapsedInSplit: pastGrace,
        ),
        SplitVerdict.tooSlow,
      );
    });

    test('exactly at the grace boundary counts as past it', () {
      expect(
        splitVerdict(
          avgSpeedMps: target,
          targetSpeedMps: target,
          elapsedInSplit: splitVerdictGrace,
        ),
        SplitVerdict.onTarget,
      );
    });

    test('a non-positive target is treated as no target', () {
      expect(
        splitVerdict(
          avgSpeedMps: 3.0,
          targetSpeedMps: 0,
          elapsedInSplit: pastGrace,
        ),
        isNull,
      );
    });
  });
}
