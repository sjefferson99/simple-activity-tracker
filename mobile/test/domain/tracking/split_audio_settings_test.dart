import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/tracking/split_audio_settings.dart';

void main() {
  group('SplitAudioSettings', () {
    test('defaultSettings has every toggle off', () {
      const defaults = SplitAudioSettings.defaultSettings;
      expect(defaults.beepOnSplitChange, isFalse);
      expect(defaults.beepOnVerdictChange, isFalse);
      expect(defaults.announceSplitStats, isFalse);
      expect(defaults.announceVerdictCorrection, isFalse);
      expect(defaults.anyEnabled, isFalse);
    });

    test('toJson/fromJson round-trips', () {
      const settings = SplitAudioSettings(
        beepOnSplitChange: false,
        beepOnVerdictChange: true,
        announceSplitStats: true,
        announceVerdictCorrection: false,
      );
      final roundTripped = SplitAudioSettings.fromJson(settings.toJson());
      expect(roundTripped, settings);
    });

    test(
      'fromJson still parses a pre-removal stored value (extra "enabled" key ignored)',
      () {
        final legacyJson = {
          'enabled': true,
          'beepOnSplitChange': true,
          'beepOnVerdictChange': false,
          'announceSplitStats': false,
          'announceVerdictCorrection': true,
        };
        final parsed = SplitAudioSettings.fromJson(legacyJson);
        expect(
          parsed,
          const SplitAudioSettings(
            beepOnSplitChange: true,
            beepOnVerdictChange: false,
            announceSplitStats: false,
            announceVerdictCorrection: true,
          ),
        );
      },
    );

    test('fromJson returns null for malformed input', () {
      expect(SplitAudioSettings.fromJson(const {}), isNull);
      expect(
        SplitAudioSettings.fromJson(const {'beepOnSplitChange': 'not a bool'}),
        isNull,
      );
    });

    test('copyWith updates only the given fields', () {
      const settings = SplitAudioSettings.defaultSettings;
      final updated = settings.copyWith(beepOnSplitChange: true);
      expect(updated.beepOnSplitChange, isTrue);
      expect(updated.beepOnVerdictChange, settings.beepOnVerdictChange);
      expect(updated.announceSplitStats, settings.announceSplitStats);
      expect(
        updated.announceVerdictCorrection,
        settings.announceVerdictCorrection,
      );
    });

    test('equality/hashCode are value-based', () {
      const a = SplitAudioSettings.defaultSettings;
      const b = SplitAudioSettings.defaultSettings;
      expect(a, b);
      expect(a.hashCode, b.hashCode);

      final c = a.copyWith(announceSplitStats: true);
      expect(a == c, isFalse);
    });

    group('anyBeepEnabled / anySpeechEnabled / anyEnabled', () {
      test('all false when every toggle is off', () {
        const settings = SplitAudioSettings.defaultSettings;
        expect(settings.anyBeepEnabled, isFalse);
        expect(settings.anySpeechEnabled, isFalse);
        expect(settings.anyEnabled, isFalse);
      });

      test('anyBeepEnabled is true with either beep toggle alone', () {
        const settings = SplitAudioSettings.defaultSettings;
        expect(settings.copyWith(beepOnSplitChange: true).anyBeepEnabled, isTrue);
        expect(settings.copyWith(beepOnVerdictChange: true).anyBeepEnabled, isTrue);
        expect(settings.copyWith(beepOnSplitChange: true).anySpeechEnabled, isFalse);
      });

      test('anySpeechEnabled is true with either speech toggle alone', () {
        const settings = SplitAudioSettings.defaultSettings;
        expect(
          settings.copyWith(announceSplitStats: true).anySpeechEnabled,
          isTrue,
        );
        expect(
          settings.copyWith(announceVerdictCorrection: true).anySpeechEnabled,
          isTrue,
        );
        expect(
          settings.copyWith(announceSplitStats: true).anyBeepEnabled,
          isFalse,
        );
      });

      test('anyEnabled is true if any single toggle is on', () {
        const settings = SplitAudioSettings.defaultSettings;
        expect(settings.copyWith(beepOnSplitChange: true).anyEnabled, isTrue);
        expect(settings.copyWith(beepOnVerdictChange: true).anyEnabled, isTrue);
        expect(settings.copyWith(announceSplitStats: true).anyEnabled, isTrue);
        expect(
          settings.copyWith(announceVerdictCorrection: true).anyEnabled,
          isTrue,
        );
      });
    });
  });
}
