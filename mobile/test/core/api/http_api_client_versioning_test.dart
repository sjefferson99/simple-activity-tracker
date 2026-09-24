import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:simple_activity_tracker/core/api/api_exception.dart';
import 'package:simple_activity_tracker/core/api/dto/server_info_dto.dart';
import 'package:simple_activity_tracker/core/api/http_api_client.dart';
import 'package:simple_activity_tracker/core/version/api_compat.dart';
import 'package:simple_activity_tracker/domain/models/run_summary.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';

/// docs/VERSIONING.md — the HTTP-level half of "never break an older server".

const _baseUrl = 'https://runner.example.com';

final _summary = RunSummary(
  clientRunId: 'abc',
  startedAt: DateTime.utc(2026, 1, 1),
  endedAt: DateTime.utc(2026, 1, 1, 0, 30),
  activityMode: ActivityMode.running,
  movingSeconds: 1800,
  distanceMeters: 5000,
  avgSpeedMps: 2.78,
  maxSpeedMps: 4,
  elevationGainMeters: 10,
  splits: const [
    RunSummarySplit(
      index: 1,
      durationSeconds: 360,
      avgSpeedMps: 2.78,
      distanceMeters: 1000,
      targetSpeedMps: 3,
    ),
  ],
  sourcePlatform: 'android',
  sourceAppVersion: '1.3.0+60',
);

http.StreamedResponse _runDtoResponse() => http.StreamedResponse(
  Stream.value(utf8.encode(File('test/fixtures/run_dto_sample.json').readAsStringSync())),
  201,
);

Future<Map<String, dynamic>> _uploadedSummary(int serverApiLevel) async {
  late Map<String, dynamic> sent;
  final client = HttpApiClient(
    client: MockClient.streaming((request, _) async {
      sent = jsonDecode((request as http.MultipartRequest).fields['summary']!)
          as Map<String, dynamic>;
      return _runDtoResponse();
    }),
  );
  await client.uploadRun(
    baseUrl: _baseUrl,
    token: 't',
    summary: _summary,
    gpxFile: File('test/fixtures/run_dto_sample.json'),
    serverApiLevel: serverApiLevel,
  );
  return sent;
}

void main() {
  group('uploadRun shapes the summary for the server', () {
    test('a level 0 server never receives fields it would reject', () async {
      final sent = await _uploadedSummary(0);
      expect(sent.containsKey('max_speed_mps'), isFalse);
      expect(sent.containsKey('elevation_gain_meters'), isFalse);
      expect((sent['splits'] as List).single.containsKey('target_speed_mps'), isFalse);
      expect(sent['distance_meters'], 5000);
    });

    test('a current server receives everything', () async {
      final sent = await _uploadedSummary(kAppApiLevel);
      expect(sent['max_speed_mps'], 4);
      expect(sent['elevation_gain_meters'], 10);
      expect((sent['splits'] as List).single['target_speed_mps'], 3);
    });
  });

  group('getServerInfo', () {
    test('parses the server response', () async {
      final client = HttpApiClient(
        client: MockClient((request) async {
          expect(request.url, Uri.parse('$_baseUrl/api/v1/server-info'));
          expect(request.headers['Authorization'], 'Bearer t');
          return http.Response(
            jsonEncode({'version': '1.3.0', 'api_level': 1, 'min_app_api_level': 0}),
            200,
          );
        }),
      );
      final info = await client.getServerInfo(baseUrl: _baseUrl, token: 't');
      expect(info.version, '1.3.0');
      expect(info.apiLevel, 1);
    });

    test('a 404 means a server from before the endpoint existed', () async {
      final client = HttpApiClient(
        client: MockClient(
          (request) async => http.Response('{"detail":"Not Found"}', 404),
        ),
      );
      final info = await client.getServerInfo(baseUrl: _baseUrl, token: 't');
      expect(info, same(ServerInfoDto.legacy));
      expect(info.apiLevel, 0);
    });

    test('other failures still throw', () async {
      final client = HttpApiClient(
        client: MockClient((request) async => http.Response('boom', 503)),
      );
      expect(
        () => client.getServerInfo(baseUrl: _baseUrl, token: 't'),
        throwsA(isA<ApiServerException>()),
      );
    });
  });

  test('every request carries the app API level and version headers', () async {
    final seen = <Map<String, String>>[];
    final client = HttpApiClient(
      appVersion: () async => '1.3.0+60',
      client: MockClient((request) async {
        seen.add(request.headers);
        return http.Response(
          jsonEncode({
            'id': 'u1',
            'email': 'a@b.c',
            'display_name': 'A',
            'is_admin': false,
          }),
          200,
        );
      }),
    );
    await client.me(baseUrl: _baseUrl, token: 't');
    await client.me(baseUrl: _baseUrl, token: 't');
    for (final headers in seen) {
      expect(headers['X-App-Api-Level'], '$kAppApiLevel');
      expect(headers['X-App-Version'], '1.3.0+60');
    }
  });

  test('a failing version lookup never fails the request', () async {
    final client = HttpApiClient(
      appVersion: () async => throw StateError('no platform'),
      client: MockClient((request) async {
        expect(request.headers.containsKey('X-App-Version'), isFalse);
        expect(request.headers['X-App-Api-Level'], '$kAppApiLevel');
        return http.Response(
          jsonEncode({
            'id': 'u1',
            'email': 'a@b.c',
            'display_name': 'A',
            'is_admin': false,
          }),
          200,
        );
      }),
    );
    await client.me(baseUrl: _baseUrl, token: 't');
  });
}
