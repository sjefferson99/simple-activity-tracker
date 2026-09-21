import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/tracking/split_audio_settings.dart';

void main() {
  group('SplitAudioSettings', () {
    test('defaultSettings has every toggle off', () {
      const defaults = SplitAudioSettings.defaultSettings;
      expect(defaults.beepOnSplitChange, isFalse);
      expect(defaults.beepOnVerdictChange, isFalse);
      expect(defaults.announceSplitTarget, isFalse);
      expect(defaults.announceVerdictCorrection, isFalse);
      expect(defaults.anyEnabled, isFalse);
    });

    test('toJson/fromJson round-trips', () {
      const settings = SplitAudioSettings(
        beepOnSplitChange: false,
        beepOnVerdictChange: true,
        announceSplitTarget: true,
        announceVerdictCorrection: false,
      );
      final roundTripped = SplitAudioSettings.fromJson(settings.toJson());
      expect(roundTripped, settings);
    });

    test(
      'fromJson still parses a pre-master-toggle-removal stored value '
      '(extra "enabled" key ignored)',
      () {
        final legacyJson = {
          'enabled': true,
          'beepOnSplitChange': true,
          'beepOnVerdictChange': false,
          'announceSplitTarget': false,
          'announceVerdictCorrection': true,
        };
        final parsed = SplitAudioSettings.fromJson(legacyJson);
        expect(
          parsed,
          const SplitAudioSettings(
            beepOnSplitChange: true,
            beepOnVerdictChange: false,
            announceSplitTarget: false,
            announceVerdictCorrection: true,
          ),
        );
      },
    );

    test(
      'fromJson still parses a pre-rename stored value '
      '(old announceSplitStats key simply ignored, field reads as false)',
      () {
        final preRenameJson = {
          'beepOnSplitChange': true,
          'beepOnVerdictChange': false,
          'announceSplitStats': true, // the field's old name
          'announceVerdictCorrection': true,
        };
        final parsed = SplitAudioSettings.fromJson(preRenameJson);
        expect(
          parsed,
          const SplitAudioSettings(
            beepOnSplitChange: true,
            beepOnVerdictChange: false,
            announceSplitTarget: false,
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
      expect(updated.announceSplitTarget, settings.announceSplitTarget);
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

      final c = a.copyWith(announceSplitTarget: true);
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
          settings.copyWith(announceSplitTarget: true).anySpeechEnabled,
          isTrue,
        );
        expect(
          settings.copyWith(announceVerdictCorrection: true).anySpeechEnabled,
          isTrue,
        );
        expect(
          settings.copyWith(announceSplitTarget: true).anyBeepEnabled,
          isFalse,
        );
      });

      test('anyEnabled is true if any single toggle is on', () {
        const settings = SplitAudioSettings.defaultSettings;
        expect(settings.copyWith(beepOnSplitChange: true).anyEnabled, isTrue);
        expect(settings.copyWith(beepOnVerdictChange: true).anyEnabled, isTrue);
        expect(settings.copyWith(announceSplitTarget: true).anyEnabled, isTrue);
        expect(
          settings.copyWith(announceVerdictCorrection: true).anyEnabled,
          isTrue,
        );
      });
    });
  });
}
