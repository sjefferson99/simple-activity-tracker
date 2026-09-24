import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/dto/server_info_dto.dart';
import 'package:simple_activity_tracker/core/version/app_version.dart';
import 'package:simple_activity_tracker/features/settings/about_section.dart';

const _app = AppVersion(version: '1.3.0', buildNumber: '60');

ServerInfoDto _server(String version, {int apiLevel = 1, int minAppApiLevel = 0}) =>
    ServerInfoDto(version: version, apiLevel: apiLevel, minAppApiLevel: minAppApiLevel);

void main() {
  group('compatibilityNote', () {
    test('matching versions need no note', () {
      expect(compatibilityNote(_app, _server('1.3.0')), isNull);
    });

    test('a main build past the same release counts as matching', () {
      expect(compatibilityNote(_app, _server('1.3.0+4.gabc1234')), isNull);
    });

    test('different versions get a neutral recommendation', () {
      final note = compatibilityNote(_app, _server('1.2.9'));
      expect(note?.message, 'Matching versions are recommended.');
      expect(note?.isWarning, isFalse);
    });

    test('dev builds are never compared', () {
      expect(
        compatibilityNote(const AppVersion(version: '0.0.0', buildNumber: '1'), _server('1.3.0')),
        isNull,
      );
      expect(compatibilityNote(_app, _server('dev')), isNull);
    });

    test('a legacy server gets a neutral note', () {
      final note = compatibilityNote(_app, ServerInfoDto.legacy);
      expect(note?.isWarning, isFalse);
      expect(note?.message, contains('predates version reporting'));
    });

    test('app too old is a warning to update the app', () {
      final note = compatibilityNote(_app, _server('2.0.0', apiLevel: 5, minAppApiLevel: 4));
      expect(note?.isWarning, isTrue);
      expect(note?.message, contains('Update the app'));
    });
  });

  group('AppVersion', () {
    test('the pubspec placeholder reads as a dev build', () {
      const dev = AppVersion(version: '0.0.0', buildNumber: '1');
      expect(dev.isDevBuild, isTrue);
      expect(dev.display, 'dev build');
      expect(_app.display, '1.3.0');
      expect(_app.full, '1.3.0+60');
    });
  });

  group('ServerInfoDto.fromJson', () {
    test('parses the server shape', () {
      final info = ServerInfoDto.fromJson({
        'version': '1.3.0',
        'api_level': 1,
        'min_app_api_level': 0,
      });
      expect(info.version, '1.3.0');
      expect(info.apiLevel, 1);
      expect(info.isLegacy, isFalse);
    });

    test('tolerates missing and mistyped fields', () {
      final info = ServerInfoDto.fromJson({'api_level': 'two', 'extra': true});
      expect(info.version, 'unknown');
      expect(info.apiLevel, 0);
      expect(info.minAppApiLevel, 0);
    });
  });
}
