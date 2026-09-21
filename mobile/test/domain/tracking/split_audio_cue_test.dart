import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/models/current_split_info.dart';
import 'package:simple_activity_tracker/domain/models/live_metrics.dart';
import 'package:simple_activity_tracker/domain/models/split.dart';
import 'package:simple_activity_tracker/domain/tracking/split_audio_cue.dart';
import 'package:simple_activity_tracker/domain/tracking/split_target.dart';

CurrentSplitInfo _split({
  int index = 1,
  double? targetSpeedMps,
  int? plannedCount,
}) => CurrentSplitInfo(
  index: index,
  plannedCount: plannedCount,
  sizeKind: SplitSizeKind.distanceMeters,
  size: 1000,
  targetSpeedMps: targetSpeedMps,
);

/// Builds a [LiveMetrics] with just the fields [detectSplitAudioCue] and its
/// helpers actually read — everything else is a fixed, otherwise-irrelevant
/// value.
LiveMetrics _metrics({
  required CurrentSplitInfo currentSplit,
  Duration currentSplitElapsed = Duration.zero,
  double currentSplitDistanceMeters = 0,
  List<Split> completedSplits = const [],
}) => LiveMetrics(
  elapsed: Duration.zero,
  distanceMeters: 0,
  avgSpeedMps: null,
  completedSplits: completedSplits,
  currentSplitElapsed: currentSplitElapsed,
  currentSplitDistanceMeters: currentSplitDistanceMeters,
  currentSplit: currentSplit,
);

void main() {
  const target = 3.0; // m/s
  const pastGrace = Duration(seconds: 15);

  group('detectSplitAudioCue', () {
    test('returns null with no previous metrics (first sample of a run)', () {
      final current = _metrics(currentSplit: _split());
      expect(detectSplitAudioCue(previous: null, current: current), isNull);
    });

    test('returns null when nothing changed', () {
      final previous = _metrics(
        currentSplit: _split(index: 1),
        currentSplitElapsed: pastGrace,
        currentSplitDistanceMeters: pastGrace.inSeconds * target,
      );
      final current = previous;
      expect(
        detectSplitAudioCue(previous: previous, current: current),
        isNull,
      );
    });

    test(
      'split index incrementing produces splitChanged, carrying the new '
      'split (not the just-finished one\'s average, which the cue no '
      'longer needs — issue #125 follow-up removed the end-of-split '
      'summary in favour of announcing the new split\'s target)',
      () {
        final previous = _metrics(currentSplit: _split(index: 1));
        final current = _metrics(
          currentSplit: _split(index: 2, targetSpeedMps: target),
          completedSplits: [
            const Split(index: 1, duration: pastGrace, avgSpeedMps: 3.2, distanceMeters: 1000),
          ],
        );

        final cue = detectSplitAudioCue(previous: previous, current: current);
        expect(cue, isNotNull);
        expect(cue!.kind, SplitAudioCueKind.splitChanged);
        expect(cue.split.index, 2);
        expect(cue.split.targetSpeedMps, target);
        expect(cue.avgSpeedMps, isNull);
        expect(cue.rolledOntoRollingSplits, isFalse);
      },
    );

    group('rolledOntoRollingSplits', () {
      test(
        'true on the exact tick a custom plan\'s splits are exhausted',
        () {
          // A 2-split custom plan (plannedCount: 2): index 2 -> 3 is the
          // roll-on tick (3 == plannedCount + 1).
          final previous = _metrics(
            currentSplit: _split(index: 2, plannedCount: 2),
          );
          final current = _metrics(
            currentSplit: _split(index: 3, plannedCount: 2),
            completedSplits: [
              const Split(index: 1, duration: pastGrace, avgSpeedMps: 3.0, distanceMeters: 1000),
              const Split(index: 2, duration: pastGrace, avgSpeedMps: 3.0, distanceMeters: 1000),
            ],
          );

          final cue = detectSplitAudioCue(previous: previous, current: current);
          expect(cue!.rolledOntoRollingSplits, isTrue);
        },
      );

      test('false for an ordinary split boundary within a custom plan', () {
        final previous = _metrics(
          currentSplit: _split(index: 1, plannedCount: 3),
        );
        final current = _metrics(
          currentSplit: _split(index: 2, plannedCount: 3),
          completedSplits: [
            const Split(index: 1, duration: pastGrace, avgSpeedMps: 3.0, distanceMeters: 1000),
          ],
        );

        final cue = detectSplitAudioCue(previous: previous, current: current);
        expect(cue!.rolledOntoRollingSplits, isFalse);
      });

      test('false for a rolling plan (no plannedCount at all)', () {
        final previous = _metrics(currentSplit: _split(index: 1));
        final current = _metrics(
          currentSplit: _split(index: 2),
          completedSplits: [
            const Split(index: 1, duration: pastGrace, avgSpeedMps: 3.0, distanceMeters: 1000),
          ],
        );

        final cue = detectSplitAudioCue(previous: previous, current: current);
        expect(cue!.rolledOntoRollingSplits, isFalse);
      });

      test(
        'false for a later boundary after already rolling on (only the exact tick counts)',
        () {
          final previous = _metrics(
            currentSplit: _split(index: 3, plannedCount: 2),
          );
          final current = _metrics(
            currentSplit: _split(index: 4, plannedCount: 2),
            completedSplits: [
              const Split(index: 1, duration: pastGrace, avgSpeedMps: 3.0, distanceMeters: 1000),
              const Split(index: 2, duration: pastGrace, avgSpeedMps: 3.0, distanceMeters: 1000),
              const Split(index: 3, duration: pastGrace, avgSpeedMps: 3.0, distanceMeters: 1000),
            ],
          );

          final cue = detectSplitAudioCue(previous: previous, current: current);
          expect(cue!.rolledOntoRollingSplits, isFalse);
        },
      );
    });

    test(
      'a split index increment wins over a same-tick verdict change (D2)',
      () {
        // previous: split 1, too fast. current: split 2, no verdict data
        // yet — even if it had one, splitChanged must be what's returned.
        final previous = _metrics(
          currentSplit: _split(index: 1, targetSpeedMps: target),
          currentSplitElapsed: pastGrace,
          currentSplitDistanceMeters: pastGrace.inSeconds * target * 1.2,
        );
        final current = _metrics(
          currentSplit: _split(index: 2, targetSpeedMps: target),
          currentSplitElapsed: Duration.zero,
          currentSplitDistanceMeters: 0,
          completedSplits: [
            const Split(
              index: 1,
              duration: pastGrace,
              avgSpeedMps: 3.6,
              distanceMeters: 1000,
              targetSpeedMps: target,
            ),
          ],
        );

        final cue = detectSplitAudioCue(previous: previous, current: current);
        expect(cue!.kind, SplitAudioCueKind.splitChanged);
      },
    );

    test('grace period elapsing (null -> tooFast) produces a verdict cue', () {
      final previous = _metrics(
        currentSplit: _split(index: 1, targetSpeedMps: target),
        currentSplitElapsed: splitVerdictGrace - const Duration(seconds: 1),
        currentSplitDistanceMeters:
            (splitVerdictGrace - const Duration(seconds: 1)).inSeconds *
            target *
            1.2,
      );
      final elapsed = splitVerdictGrace;
      final current = _metrics(
        currentSplit: _split(index: 1, targetSpeedMps: target),
        currentSplitElapsed: elapsed,
        currentSplitDistanceMeters: elapsed.inSeconds * target * 1.2,
      );

      final cue = detectSplitAudioCue(previous: previous, current: current);
      expect(cue!.kind, SplitAudioCueKind.verdict);
      expect(cue.verdict, SplitVerdict.tooFast);
    });

    test('tooFast -> onTarget produces a verdict(onTarget) cue', () {
      final previous = _metrics(
        currentSplit: _split(index: 1, targetSpeedMps: target),
        currentSplitElapsed: pastGrace,
        currentSplitDistanceMeters: pastGrace.inSeconds * target * 1.2,
      );
      final current = _metrics(
        currentSplit: _split(index: 1, targetSpeedMps: target),
        currentSplitElapsed: pastGrace + const Duration(seconds: 1),
        currentSplitDistanceMeters:
            (pastGrace + const Duration(seconds: 1)).inSeconds * target,
      );

      final cue = detectSplitAudioCue(previous: previous, current: current);
      expect(cue!.kind, SplitAudioCueKind.verdict);
      expect(cue.verdict, SplitVerdict.onTarget);
    });

    test('tooSlow -> onTarget produces a verdict(onTarget) cue', () {
      final previous = _metrics(
        currentSplit: _split(index: 1, targetSpeedMps: target),
        currentSplitElapsed: pastGrace,
        currentSplitDistanceMeters: pastGrace.inSeconds * target * 0.8,
      );
      final current = _metrics(
        currentSplit: _split(index: 1, targetSpeedMps: target),
        currentSplitElapsed: pastGrace + const Duration(seconds: 1),
        currentSplitDistanceMeters:
            (pastGrace + const Duration(seconds: 1)).inSeconds * target,
      );

      final cue = detectSplitAudioCue(previous: previous, current: current);
      expect(cue!.kind, SplitAudioCueKind.verdict);
      expect(cue.verdict, SplitVerdict.onTarget);
    });

    test('onTarget -> tooFast produces a verdict(tooFast) cue', () {
      final previous = _metrics(
        currentSplit: _split(index: 1, targetSpeedMps: target),
        currentSplitElapsed: pastGrace,
        currentSplitDistanceMeters: pastGrace.inSeconds * target,
      );
      final current = _metrics(
        currentSplit: _split(index: 1, targetSpeedMps: target),
        currentSplitElapsed: pastGrace + const Duration(seconds: 1),
        currentSplitDistanceMeters:
            (pastGrace + const Duration(seconds: 1)).inSeconds * target * 1.5,
      );

      final cue = detectSplitAudioCue(previous: previous, current: current);
      expect(cue!.kind, SplitAudioCueKind.verdict);
      expect(cue.verdict, SplitVerdict.tooFast);
    });

    test('onTarget -> tooSlow produces a verdict(tooSlow) cue', () {
      final previous = _metrics(
        currentSplit: _split(index: 1, targetSpeedMps: target),
        currentSplitElapsed: pastGrace,
        currentSplitDistanceMeters: pastGrace.inSeconds * target,
      );
      final current = _metrics(
        currentSplit: _split(index: 1, targetSpeedMps: target),
        currentSplitElapsed: pastGrace + const Duration(seconds: 1),
        currentSplitDistanceMeters:
            (pastGrace + const Duration(seconds: 1)).inSeconds * target * 0.5,
      );

      final cue = detectSplitAudioCue(previous: previous, current: current);
      expect(cue!.kind, SplitAudioCueKind.verdict);
      expect(cue.verdict, SplitVerdict.tooSlow);
    });

    test('tooFast -> tooSlow directly produces a verdict(tooSlow) cue', () {
      final previous = _metrics(
        currentSplit: _split(index: 1, targetSpeedMps: target),
        currentSplitElapsed: pastGrace,
        currentSplitDistanceMeters: pastGrace.inSeconds * target * 1.5,
      );
      final current = _metrics(
        currentSplit: _split(index: 1, targetSpeedMps: target),
        currentSplitElapsed: pastGrace + const Duration(seconds: 1),
        currentSplitDistanceMeters:
            (pastGrace + const Duration(seconds: 1)).inSeconds * target * 0.5,
      );

      final cue = detectSplitAudioCue(previous: previous, current: current);
      expect(cue!.kind, SplitAudioCueKind.verdict);
      expect(cue.verdict, SplitVerdict.tooSlow);
    });

    test(
      'a verdict clearing to null (e.g. re-anchor) is silent, not a cue',
      () {
        final previous = _metrics(
          currentSplit: _split(index: 1, targetSpeedMps: target),
          currentSplitElapsed: pastGrace,
          currentSplitDistanceMeters: pastGrace.inSeconds * target * 1.5,
        );
        // Moving time reset to zero (as a re-anchor/pause would do) — no
        // speed yet, so splitVerdict returns null again.
        final current = _metrics(
          currentSplit: _split(index: 1, targetSpeedMps: target),
          currentSplitElapsed: Duration.zero,
          currentSplitDistanceMeters: 0,
        );

        expect(
          detectSplitAudioCue(previous: previous, current: current),
          isNull,
        );
      },
    );

    test(
      'the same verdict sustained across many ticks produces no cue after the first',
      () {
        final tick1 = _metrics(
          currentSplit: _split(index: 1, targetSpeedMps: target),
          currentSplitElapsed: pastGrace,
          currentSplitDistanceMeters: pastGrace.inSeconds * target * 1.5,
        );
        final tick2 = _metrics(
          currentSplit: _split(index: 1, targetSpeedMps: target),
          currentSplitElapsed: pastGrace + const Duration(seconds: 1),
          currentSplitDistanceMeters:
              (pastGrace + const Duration(seconds: 1)).inSeconds *
              target *
              1.5,
        );
        final tick3 = _metrics(
          currentSplit: _split(index: 1, targetSpeedMps: target),
          currentSplitElapsed: pastGrace + const Duration(seconds: 2),
          currentSplitDistanceMeters:
              (pastGrace + const Duration(seconds: 2)).inSeconds *
              target *
              1.5,
        );

        // tick1 has no "previous" of its own in this test — start the diff
        // from tick1 -> tick2 (still tooFast -> tooFast).
        expect(
          detectSplitAudioCue(previous: tick1, current: tick2),
          isNull,
        );
        expect(
          detectSplitAudioCue(previous: tick2, current: tick3),
          isNull,
        );
      },
    );
  });
}
