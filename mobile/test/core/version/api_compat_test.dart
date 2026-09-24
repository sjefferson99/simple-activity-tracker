import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/version/api_compat.dart';

int _serverConstant(String source, String name) {
  final match = RegExp('^$name\\s*=\\s*(\\d+)', multiLine: true).firstMatch(source);
  if (match == null) fail('$name not found in server/app/api_compat.py');
  return int.parse(match.group(1)!);
}

void main() {
  test('kAppApiLevel matches the server API_LEVEL in the same commit', () {
    // docs/VERSIONING.md §2: bumping the server's level without the app's
    // (or vice versa) means one side was changed without the other.
    final source = File('../server/app/api_compat.py').readAsStringSync();
    expect(kAppApiLevel, _serverConstant(source, 'API_LEVEL'));
  });

  test('levels are consistent', () {
    expect(kMinServerApiLevel, inInclusiveRange(0, kAppApiLevel));
    expect(ApiLevels.uploadExtendedStats, inInclusiveRange(1, kAppApiLevel));
  });

  group('assessCompatibility', () {
    test('compatible within range', () {
      expect(
        assessCompatibility(serverApiLevel: 1, serverMinAppApiLevel: 0, appApiLevel: 1),
        ServerCompatibility.compatible,
      );
    });

    test('a newer server that still supports this app is compatible', () {
      expect(
        assessCompatibility(serverApiLevel: 4, serverMinAppApiLevel: 1, appApiLevel: 1),
        ServerCompatibility.compatible,
      );
    });

    test('app below the server minimum is too old', () {
      expect(
        assessCompatibility(serverApiLevel: 4, serverMinAppApiLevel: 2, appApiLevel: 1),
        ServerCompatibility.appTooOld,
      );
    });

    test('server below the app minimum is too old', () {
      expect(
        assessCompatibility(
          serverApiLevel: 0,
          serverMinAppApiLevel: 0,
          appApiLevel: 3,
          minServerApiLevel: 1,
        ),
        ServerCompatibility.serverTooOld,
      );
    });

    test('every released server (level 0) is supported today', () {
      expect(
        assessCompatibility(serverApiLevel: kLegacyServerApiLevel, serverMinAppApiLevel: 0),
        ServerCompatibility.compatible,
      );
    });
  });
}
