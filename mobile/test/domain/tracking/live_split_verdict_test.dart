import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/models/current_split_info.dart';
import 'package:simple_activity_tracker/domain/models/live_metrics.dart';
import 'package:simple_activity_tracker/domain/tracking/live_split_verdict.dart';
import 'package:simple_activity_tracker/domain/tracking/split_target.dart';

const _target = 1000 / 300; // 5:00/km
const _pastGrace = Duration(seconds: 15);

SplitVerdict? _live(double ratio, {required double progress, SplitVerdict? previous}) =>
    liveSplitVerdict(
      avgSpeedMps: _target * ratio,
      targetSpeedMps: _target,
      elapsedInSplit: _pastGrace,
      progress: progress,
      previous: previous,
    );

/// Metrics for a 1 km split (or a 300 s one with [timeSplit]) at [ratio] of
/// the 5:00/km target, [progress] of the way through.
LiveMetrics _metrics(double ratio, double progress, {int index = 1, bool timeSplit = false}) {
  final speed = _target * ratio;
  final seconds = timeSplit ? 300 * progress : 1000 * progress / speed;
  // Never inside the grace period, so every case has a verdict.
  final elapsed = Duration(milliseconds: (seconds < 15 ? 15 : seconds) * 1000 ~/ 1);
  return LiveMetrics(
    elapsed: elapsed,
    distanceMeters: 0,
    avgSpeedMps: null,
    completedSplits: const [],
    currentSplitElapsed: elapsed,
    currentSplitDistanceMeters: speed * elapsed.inMilliseconds / 1000,
    currentSplit: CurrentSplitInfo(
      index: index,
      plannedCount: null,
      sizeKind: timeSplit ? SplitSizeKind.durationSeconds : SplitSizeKind.distanceMeters,
      size: timeSplit ? 300 : 1000,
      targetSpeedMps: _target,
    ),
  );
}

void main() {
  group('liveVerdictExitMargin', () {
    test('is twice the band early in a split, shrinking as 1/progress to half the band', () {
      expect(liveVerdictExitMargin(0), liveVerdictMaxExitMargin);
      expect(liveVerdictExitMargin(0.15), liveVerdictMaxExitMargin);
      expect(liveVerdictExitMargin(0.3), closeTo(liveVerdictMaxExitMargin / 2, 1e-12));
      expect(liveVerdictExitMargin(0.6), closeTo(liveVerdictMinExitMargin, 1e-12));
      expect(liveVerdictExitMargin(1), liveVerdictMinExitMargin);
    });
  });

  group('liveSplitVerdict', () {
    test('with no previous verdict it is the plain band', () {
      expect(_live(1.012, progress: 0.05), SplitVerdict.onTarget);
      expect(_live(1.02, progress: 0.05), SplitVerdict.tooFast);
      expect(_live(0.98, progress: 0.05), SplitVerdict.tooSlow);
    });

    test('on target holds early in a split until beyond band + full margin', () {
      const previous = SplitVerdict.onTarget;
      // Band 1.3% + twice it = 3.9%.
      expect(_live(1.035, progress: 0.05, previous: previous), SplitVerdict.onTarget);
      expect(_live(0.965, progress: 0.05, previous: previous), SplitVerdict.onTarget);
      expect(_live(1.045, progress: 0.05, previous: previous), SplitVerdict.tooFast);
      expect(_live(0.955, progress: 0.05, previous: previous), SplitVerdict.tooSlow);
    });

    test('the hold narrows late in a split', () {
      const previous = SplitVerdict.onTarget;
      // Band 1.3% + half of it = 1.95% by the end.
      expect(_live(1.018, progress: 0.9, previous: previous), SplitVerdict.onTarget);
      expect(_live(1.025, progress: 0.9, previous: previous), SplitVerdict.tooFast);
    });

    test('off target re-enters at the plain band edge', () {
      expect(_live(1.02, progress: 0.05, previous: SplitVerdict.tooFast), SplitVerdict.tooFast);
      expect(_live(1.012, progress: 0.05, previous: SplitVerdict.tooFast), SplitVerdict.onTarget);
    });

    test('still nothing within the grace period', () {
      expect(
        liveSplitVerdict(
          avgSpeedMps: _target,
          targetSpeedMps: _target,
          elapsedInSplit: splitVerdictGrace - const Duration(seconds: 1),
          progress: 0.01,
          previous: SplitVerdict.onTarget,
        ),
        isNull,
      );
    });
  });

  group('currentSplitProgress', () {
    test('is distance- or time-based by split kind, clamped to 0..1', () {
      expect(currentSplitProgress(_metrics(1, 0.25)), closeTo(0.25, 0.01));
      expect(currentSplitProgress(_metrics(1, 0.5, timeSplit: true)), closeTo(0.5, 0.01));
      expect(currentSplitProgress(_metrics(1, 1.5)), 1);
    });
  });

  group('LiveSplitVerdictTracker', () {
    test('an average hovering at the band edge early on beeps once, not every flip', () {
      final tracker = LiveSplitVerdictTracker();
      final verdicts = [
        for (final ratio in [1.010, 1.016, 1.011, 1.018, 1.012, 1.015]) tracker.update(_metrics(ratio, 0.1)),
      ];
      // The plain band would flip on/off target five times.
      expect(verdicts, everyElement(SplitVerdict.onTarget));
    });

    test('a new split starts with no memory of the last one', () {
      final tracker = LiveSplitVerdictTracker();
      expect(tracker.update(_metrics(1.0, 0.9)), SplitVerdict.onTarget);
      expect(tracker.update(_metrics(1.02, 0.05, index: 2)), SplitVerdict.tooFast);
    });

    test('update is idempotent for the same metrics', () {
      final tracker = LiveSplitVerdictTracker();
      tracker.update(_metrics(1.0, 0.05));
      final drifting = _metrics(1.02, 0.05);
      expect(tracker.update(drifting), SplitVerdict.onTarget);
      expect(tracker.update(drifting), SplitVerdict.onTarget);
    });

    test('reset forgets the held verdict', () {
      final tracker = LiveSplitVerdictTracker();
      tracker.update(_metrics(1.0, 0.05));
      tracker.reset();
      expect(tracker.update(_metrics(1.02, 0.05)), SplitVerdict.tooFast);
    });
  });
}
