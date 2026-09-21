import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/audio/split_audio_announcer.dart';
import 'package:simple_activity_tracker/core/units/units.dart';
import 'package:simple_activity_tracker/domain/models/current_split_info.dart';
import 'package:simple_activity_tracker/domain/tracking/split_audio_cue.dart';
import 'package:simple_activity_tracker/domain/tracking/split_target.dart';

CurrentSplitInfo _split({
  int index = 2,
  int? plannedCount,
  double? targetSpeedMps,
  SplitSizeKind sizeKind = SplitSizeKind.distanceMeters,
  double size = 1000,
}) => CurrentSplitInfo(
  index: index,
  plannedCount: plannedCount,
  sizeKind: sizeKind,
  size: size,
  targetSpeedMps: targetSpeedMps,
);

void main() {
  group('targetAnnouncement', () {
    test('no target', () {
      expect(targetAnnouncement(_split(targetSpeedMps: null), SpeedUnit.minKm), 'No target.');
    });

    test('with a target', () {
      const target = 1000 / 300; // 5:00/km
      expect(
        targetAnnouncement(_split(targetSpeedMps: target), SpeedUnit.minKm),
        'Target 5 minutes per kilometre.',
      );
    });
  });

  group('splitStartAnnouncement', () {
    test('null for a verdict cue', () {
      final cue = SplitAudioCue.verdict(
        verdict: SplitVerdict.onTarget,
        split: _split(),
        avgSpeedMps: 3.0,
      );
      expect(splitStartAnnouncement(cue, SpeedUnit.minKm), isNull);
    });

    test('announces the new split\'s target, no target configured', () {
      final cue = SplitAudioCue.splitChanged(
        split: _split(targetSpeedMps: null),
        rolledOntoRollingSplits: false,
      );
      expect(splitStartAnnouncement(cue, SpeedUnit.minKm), 'No target.');
    });

    test('announces the new split\'s target, target configured', () {
      const target = 1000 / 300; // 5:00/km
      final cue = SplitAudioCue.splitChanged(
        split: _split(targetSpeedMps: target),
        rolledOntoRollingSplits: false,
      );
      expect(
        splitStartAnnouncement(cue, SpeedUnit.minKm),
        'Target 5 minutes per kilometre.',
      );
    });

    test(
      'prefixes with the rolling-splits announcement when rolling on, distance kind',
      () {
        const target = 1000 / 300; // 5:00/km
        final cue = SplitAudioCue.splitChanged(
          split: _split(
            targetSpeedMps: target,
            plannedCount: 3,
            sizeKind: SplitSizeKind.distanceMeters,
            size: 1000,
          ),
          rolledOntoRollingSplits: true,
        );
        expect(
          splitStartAnnouncement(cue, SpeedUnit.minKm),
          'Now on rolling splits of 1 kilometre. Target 5 minutes per kilometre.',
        );
      },
    );

    test(
      'prefixes with the rolling-splits announcement when rolling on, time kind',
      () {
        final cue = SplitAudioCue.splitChanged(
          split: _split(
            targetSpeedMps: null,
            plannedCount: 2,
            sizeKind: SplitSizeKind.durationSeconds,
            size: 90,
          ),
          rolledOntoRollingSplits: true,
        );
        expect(
          splitStartAnnouncement(cue, SpeedUnit.minKm),
          'Now on rolling splits of 1 minute 30 seconds. No target.',
        );
      },
    );
  });

  group('splitVerdictAnnouncement', () {
    test('null for a splitChanged cue', () {
      final cue = SplitAudioCue.splitChanged(
        split: _split(),
        rolledOntoRollingSplits: false,
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

    test('"Back on target." with no target restated', () {
      const target = 1000 / 300; // 5:00/km
      final cue = SplitAudioCue.verdict(
        verdict: SplitVerdict.onTarget,
        split: _split(targetSpeedMps: target),
        avgSpeedMps: target,
      );
      expect(splitVerdictAnnouncement(cue, SpeedUnit.minKm), 'Back on target.');
    });

    test('too-slow correction includes the delta and the target, pace unit', () {
      const target = 1000 / 300; // 5:00/km
      final cue = SplitAudioCue.verdict(
        verdict: SplitVerdict.tooSlow,
        split: _split(targetSpeedMps: target),
        avgSpeedMps: target * 0.8,
      );
      final phrase = splitVerdictAnnouncement(cue, SpeedUnit.minKm)!;
      expect(phrase, startsWith('Pace is'));
      expect(phrase, contains('too slow'));
      expect(phrase, contains('target pace is 5 minutes per kilometre'));
    });

    test('too-fast correction includes the delta and the target, speed unit', () {
      const target = 1000 / 300; // 5:00/km -> 12 km/h
      final cue = SplitAudioCue.verdict(
        verdict: SplitVerdict.tooFast,
        split: _split(targetSpeedMps: target),
        avgSpeedMps: target * 1.2,
      );
      final phrase = splitVerdictAnnouncement(cue, SpeedUnit.kmh)!;
      expect(phrase, startsWith('Speed is'));
      expect(phrase, contains('too fast'));
      expect(phrase, contains('target speed is'));
    });
  });
}
