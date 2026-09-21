import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/audio/split_audio_announcer.dart';
import 'package:simple_activity_tracker/core/units/units.dart';
import 'package:simple_activity_tracker/domain/models/current_split_info.dart';
import 'package:simple_activity_tracker/domain/tracking/split_audio_cue.dart';
import 'package:simple_activity_tracker/domain/tracking/split_target.dart';

CurrentSplitInfo _split({int index = 2, double? targetSpeedMps}) =>
    CurrentSplitInfo(
      index: index,
      plannedCount: null,
      sizeKind: SplitSizeKind.distanceMeters,
      size: 1000,
      targetSpeedMps: targetSpeedMps,
    );

void main() {
  group('splitStatsAnnouncement', () {
    test('null for a verdict cue', () {
      final cue = SplitAudioCue.verdict(
        verdict: SplitVerdict.onTarget,
        split: _split(),
        avgSpeedMps: 3.0,
      );
      expect(splitStatsAnnouncement(cue, SpeedUnit.minKm), isNull);
    });

    test('null for the very first split (nothing finished yet)', () {
      final cue = SplitAudioCue.splitChanged(
        split: _split(index: 1),
        avgSpeedMps: null,
      );
      expect(splitStatsAnnouncement(cue, SpeedUnit.minKm), isNull);
    });

    test('null when the finished split has no average speed', () {
      final cue = SplitAudioCue.splitChanged(
        split: _split(index: 2),
        avgSpeedMps: null,
      );
      expect(splitStatsAnnouncement(cue, SpeedUnit.minKm), isNull);
    });

    test('announces the just-finished split index and pace', () {
      final cue = SplitAudioCue.splitChanged(
        split: _split(index: 2),
        avgSpeedMps: 1000 / 330, // 5:30/km
      );
      expect(
        splitStatsAnnouncement(cue, SpeedUnit.minKm),
        'Split 1 complete. Average 5 minutes 30 per kilometre.',
      );
    });
  });

  group('splitVerdictAnnouncement', () {
    test('null for a splitChanged cue', () {
      final cue = SplitAudioCue.splitChanged(
        split: _split(),
        avgSpeedMps: 3.0,
      );
      expect(splitVerdictAnnouncement(cue, SpeedUnit.minKm), isNull);
    });

    test('null when there is no target', () {
      final cue = SplitAudioCue.verdict(
        verdict: SplitVerdict.onTarget,
        split: _split(targetSpeedMps: null),
        avgSpeedMps: 3.0,
      );
      expect(splitVerdictAnnouncement(cue, SpeedUnit.minKm), isNull);
    });

    test('capitalizes "back on target"', () {
      const target = 1000 / 300; // 5:00/km
      final cue = SplitAudioCue.verdict(
        verdict: SplitVerdict.onTarget,
        split: _split(targetSpeedMps: target),
        avgSpeedMps: target,
      );
      expect(splitVerdictAnnouncement(cue, SpeedUnit.minKm), 'Back on target');
    });

    test('announces a too-slow correction, capitalized', () {
      const target = 1000 / 300; // 5:00/km
      final cue = SplitAudioCue.verdict(
        verdict: SplitVerdict.tooSlow,
        split: _split(targetSpeedMps: target),
        avgSpeedMps: target * 0.9,
      );
      final phrase = splitVerdictAnnouncement(cue, SpeedUnit.minKm)!;
      expect(phrase[0], phrase[0].toUpperCase());
      expect(phrase, contains('too slow'));
    });
  });
}
