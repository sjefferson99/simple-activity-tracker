import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:simple_activity_tracker/core/api/api_exception.dart';
import 'package:simple_activity_tracker/core/api/dto/split_config_dto.dart';
import 'package:simple_activity_tracker/core/api/http_api_client.dart';
import 'package:simple_activity_tracker/domain/models/run_summary.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';

const _baseUrl = 'https://runner.example.com';

RunSummary _summary() => RunSummary(
  clientRunId: 'abc',
  startedAt: DateTime.utc(2026, 1, 1),
  endedAt: DateTime.utc(2026, 1, 1, 0, 30),
  activityMode: ActivityMode.running,
  movingSeconds: 1800,
  distanceMeters: 5000,
  avgSpeedMps: 2.78,
  splits: const [],
  sourcePlatform: 'android',
  sourceAppVersion: '1.0.0+1',
);

void main() {
  test('login parses a 200 response into a LoginResponseDto', () async {
    final client = HttpApiClient(
      client: MockClient((request) async {
        expect(request.url, Uri.parse('$_baseUrl/api/v1/auth/login'));
        expect(jsonDecode(request.body), {
          'email': 'runner@example.com',
          'password': 'secret',
          'device_name': 'Pixel 8',
        });
        return http.Response(
          jsonEncode({
            'token': 'srdt_x',
            'device': {
              'id': 'd1',
              'name': 'Pixel 8',
              'created_at': '2026-01-01T00:00:00Z',
              'last_used_at': null,
            },
            'user': {
              'id': 'u1',
              'email': 'runner@example.com',
              'display_name': 'Runner',
              'is_admin': false,
            },
          }),
          200,
        );
      }),
    );

    final result = await client.login(
      baseUrl: _baseUrl,
      email: 'runner@example.com',
      password: 'secret',
      deviceName: 'Pixel 8',
    );

    expect(result.token, 'srdt_x');
    expect(result.user.email, 'runner@example.com');
  });

  test('login throws ApiUnauthorizedException on 401', () async {
    final client = HttpApiClient(
      client: MockClient(
        (request) async => http.Response(
          jsonEncode({
            'error': {
              'code': 'invalid_credentials',
              'message': 'Invalid email or password',
            },
          }),
          401,
        ),
      ),
    );

    expect(
      () => client.login(
        baseUrl: _baseUrl,
        email: 'runner@example.com',
        password: 'wrong',
        deviceName: 'Pixel 8',
      ),
      throwsA(isA<ApiUnauthorizedException>()),
    );
  });

  test(
    'throws ApiRejectedException with a helpful message on a 3xx redirect',
    () async {
      // Reproduces deploy/standalone-tls/nginx.conf redirecting http:// to
      // https:// with a 301 â€” dart:io's HttpClient never auto-follows a
      // redirect on a POST, so this response reaches HttpApiClient as-is.
      final client = HttpApiClient(
        client: MockClient(
          (request) async => http.Response(
            '<html>301 Moved Permanently</html>',
            301,
            headers: {
              'location': 'https://runner.example.com/api/v1/auth/login',
            },
          ),
        ),
      );

      await expectLater(
        () => client.login(
          baseUrl: _baseUrl,
          email: 'runner@example.com',
          password: 'secret',
          deviceName: 'Pixel 8',
        ),
        throwsA(
          isA<ApiRejectedException>().having(
            (e) => e.message,
            'message',
            contains('https://'),
          ),
        ),
      );
    },
  );

  test('throws ApiRateLimitedException on 429', () async {
    final client = HttpApiClient(
      client: MockClient(
        (request) async => http.Response(
          '{"error":{"code":"rate_limited","message":"slow down"}}',
          429,
        ),
      ),
    );

    expect(
      () => client.me(baseUrl: _baseUrl, token: 't'),
      throwsA(isA<ApiRateLimitedException>()),
    );
  });

  test('throws ApiServerException on 500', () async {
    final client = HttpApiClient(
      client: MockClient(
        (request) async => http.Response('internal error', 500),
      ),
    );

    expect(
      () => client.me(baseUrl: _baseUrl, token: 't'),
      throwsA(isA<ApiServerException>()),
    );
  });

  test('throws ApiRejectedException on other 4xx (e.g. 413)', () async {
    final client = HttpApiClient(
      client: MockClient(
        (request) async => http.Response(
          '{"error":{"code":"gpx_too_large","message":"too big"}}',
          413,
        ),
      ),
    );

    expect(
      () => client.uploadRun(
        baseUrl: _baseUrl,
        token: 't',
        summary: _summary(),
        gpxFile: File('test/fixtures/run_dto_sample.json'), // any existing file
      ),
      throwsA(isA<ApiRejectedException>()),
    );
  });

  test('throws ApiNetworkException when the socket fails', () async {
    final client = HttpApiClient(
      client: MockClient(
        (request) async => throw const SocketException('no route'),
      ),
    );

    expect(
      () => client.me(baseUrl: _baseUrl, token: 't'),
      throwsA(isA<ApiNetworkException>()),
    );
  });

  test('uploadRun sends the summary and file as multipart fields', () async {
    late Map<String, String> capturedFields;
    late List<http.MultipartFile> capturedFiles;

    late Uri capturedUrl;
    final client = HttpApiClient(
      client: MockClient.streaming((request, bodyStream) async {
        final multipart = request as http.MultipartRequest;
        capturedUrl = request.url;
        capturedFields = multipart.fields;
        capturedFiles = multipart.files;
        return http.StreamedResponse(
          Stream.value(
            utf8.encode(
              jsonEncode(
                jsonDecode(
                  File('test/fixtures/run_dto_sample.json').readAsStringSync(),
                ),
              ),
            ),
          ),
          201,
        );
      }),
    );

    final result = await client.uploadRun(
      baseUrl: _baseUrl,
      token: 't',
      summary: _summary(),
      gpxFile: File('test/fixtures/run_dto_sample.json'),
    );

    expect(capturedUrl, Uri.parse('$_baseUrl/api/v1/activities'));
    expect(jsonDecode(capturedFields['summary']!)['client_activity_id'], 'abc');
    expect(jsonDecode(capturedFields['summary']!)['activity_type'], 'running');
    expect(capturedFiles, hasLength(1));
    expect(capturedFiles.first.field, 'gpx');
    expect(result.id, '44444444-4444-4444-4444-444444444444');
  });

  test('getAnalysis treats 202 (pending) as success, not an error', () async {
    late Uri capturedUrl;
    final client = HttpApiClient(
      client: MockClient((request) async {
        capturedUrl = request.url;
        return http.Response(
          jsonEncode({'status': 'pending', 'result': null}),
          202,
        );
      }),
    );

    final result = await client.getAnalysis(
      baseUrl: _baseUrl,
      token: 't',
      serverRunId: 'run-1',
    );

    expect(
      capturedUrl,
      Uri.parse('$_baseUrl/api/v1/activities/run-1/analysis'),
    );
    expect(result.isPending, isTrue);
  });

  test('getActivity parses the full activity record', () async {
    late Uri capturedUrl;
    final client = HttpApiClient(
      client: MockClient((request) async {
        capturedUrl = request.url;
        return http.Response(
          jsonEncode({
            'id': 'run-1',
            'client_activity_id': 'abc',
            'started_at': '2026-01-01T00:00:00Z',
            'ended_at': '2026-01-01T00:30:00Z',
            'activity_type': 'running',
            'title': null,
            'notes': null,
            'device_name': 'Pixel 8',
            'client_summary': <String, dynamic>{},
            'source_platform': 'android',
            'source_app_version': '1.0.0+1',
            'analysis': {'status': 'done', 'result': {'distance_meters': 5000.0}},
            'tags': <Map<String, dynamic>>[],
            'split_plan': null,
          }),
          200,
        );
      }),
    );

    final result = await client.getActivity(
      baseUrl: _baseUrl,
      token: 't',
      serverRunId: 'run-1',
    );

    expect(capturedUrl, Uri.parse('$_baseUrl/api/v1/activities/run-1'));
    expect(result.id, 'run-1');
    expect(result.deviceName, 'Pixel 8');
    expect(result.analysis.result?['distance_meters'], 5000.0);
  });

  test('listActivities passes limit and omits cursor when not given', () async {
    late Uri capturedUrl;
    final client = HttpApiClient(
      client: MockClient((request) async {
        capturedUrl = request.url;
        return http.Response(
          jsonEncode({'activities': <Map<String, dynamic>>[], 'next_cursor': null}),
          200,
        );
      }),
    );

    await client.listActivities(baseUrl: _baseUrl, token: 't');

    expect(capturedUrl.path, '/api/v1/activities');
    expect(capturedUrl.queryParameters['limit'], '50');
    expect(capturedUrl.queryParameters.containsKey('cursor'), isFalse);
  });

  test('listActivities passes a cursor when given', () async {
    late Uri capturedUrl;
    final client = HttpApiClient(
      client: MockClient((request) async {
        capturedUrl = request.url;
        return http.Response(
          jsonEncode({'activities': <Map<String, dynamic>>[], 'next_cursor': 'next-page'}),
          200,
        );
      }),
    );

    final result = await client.listActivities(
      baseUrl: _baseUrl,
      token: 't',
      cursor: 'page-2',
      limit: 20,
    );

    expect(capturedUrl.queryParameters['cursor'], 'page-2');
    expect(capturedUrl.queryParameters['limit'], '20');
    expect(result.nextCursor, 'next-page');
  });

  test('listSplitConfigs parses a list of SplitConfigDto', () async {
    late Uri capturedUrl;
    final client = HttpApiClient(
      client: MockClient((request) async {
        capturedUrl = request.url;
        return http.Response(
          jsonEncode({
            'configs': [
              {
                'id': 'c1',
                'name': '5k tempo',
                'plan': {
                  'split_type': 'distance_km',
                  'split_value': 1,
                  'rolling_target_mps': 2.5,
                  'custom_splits': <dynamic>[],
                  'targets_as': 'pace',
                },
                'created_at': '2026-01-01T00:00:00Z',
                'updated_at': '2026-01-01T00:00:00Z',
              },
            ],
          }),
          200,
        );
      }),
    );

    final result = await client.listSplitConfigs(baseUrl: _baseUrl, token: 't');

    expect(capturedUrl.path, '/api/v1/split-configs');
    expect(result, hasLength(1));
    expect(result.single.name, '5k tempo');
    expect(result.single.plan.rollingTargetSpeedMps, 2.5);
    expect(result.single.plan.base.kind, SplitKind.distanceKm);
  });

  test('listSplitConfigs parses a custom plan correctly', () async {
    final client = HttpApiClient(
      client: MockClient((request) async {
        return http.Response(
          jsonEncode({
            'configs': [
              {
                'id': 'c1',
                'name': 'Intervals',
                'plan': {
                  'split_type': 'time_min',
                  'split_value': 1,
                  'rolling_target_mps': null,
                  'custom_splits': [
                    [90.0, 4.0],
                    [60.0, null],
                  ],
                  'targets_as': 'speed',
                },
                'created_at': '2026-01-01T00:00:00Z',
                'updated_at': '2026-01-01T00:00:00Z',
              },
            ],
          }),
          200,
        );
      }),
    );

    final result = await client.listSplitConfigs(baseUrl: _baseUrl, token: 't');
    final plan = result.single.plan;
    expect(plan.isCustom, isTrue);
    expect(plan.customSplits, hasLength(2));
    expect(plan.customSplits[0].size, 90.0);
    expect(plan.customSplits[0].targetSpeedMps, 4.0);
    expect(plan.customSplits[1].targetSpeedMps, isNull);
    expect(plan.targetsAsPace, isFalse);
  });

  test('saveSplitConfig posts the plan JSON and parses the response', () async {
    late Map<String, dynamic> capturedBody;
    final client = HttpApiClient(
      client: MockClient((request) async {
        capturedBody = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'id': 'c1',
            'name': 'New config',
            'plan': capturedBody['plan'],
            'created_at': '2026-01-01T00:00:00Z',
            'updated_at': '2026-01-01T00:00:00Z',
          }),
          200,
        );
      }),
    );

    final plan = SplitPlan(
      base: const SplitPreference(kind: SplitKind.distanceKm, value: 1),
      rollingTargetSpeedMps: 3.0,
    );
    final result = await client.saveSplitConfig(
      baseUrl: _baseUrl,
      token: 't',
      request: SplitConfigSaveRequestDto(name: 'New config', plan: plan),
    );

    expect(capturedBody['name'], 'New config');
    expect(capturedBody['plan']['split_type'], 'distance_km');
    expect(capturedBody['plan']['rolling_target_mps'], 3.0);
    expect(capturedBody.containsKey('overwrite'), isFalse);
    expect(result.name, 'New config');
  });

  test('saveSplitConfig sends overwrite:true when requested', () async {
    late Map<String, dynamic> capturedBody;
    final client = HttpApiClient(
      client: MockClient((request) async {
        capturedBody = jsonDecode(request.body) as Map<String, dynamic>;
        return http.Response(
          jsonEncode({
            'id': 'c1',
            'name': 'Existing',
            'plan': capturedBody['plan'],
            'created_at': '2026-01-01T00:00:00Z',
            'updated_at': '2026-01-01T00:00:00Z',
          }),
          200,
        );
      }),
    );

    await client.saveSplitConfig(
      baseUrl: _baseUrl,
      token: 't',
      request: SplitConfigSaveRequestDto(
        name: 'Existing',
        plan: const SplitPlan(base: SplitPreference(kind: SplitKind.distanceKm, value: 1)),
        overwrite: true,
      ),
    );

    expect(capturedBody['overwrite'], isTrue);
  });

  test('saveSplitConfig throws ApiRejectedException with statusCode 409 on name conflict', () async {
    final client = HttpApiClient(
      client: MockClient((request) async {
        return http.Response(
          jsonEncode({
            'error': {'code': 'name_conflict', 'message': "A split config named 'x' already exists."},
          }),
          409,
        );
      }),
    );

    await expectLater(
      client.saveSplitConfig(
        baseUrl: _baseUrl,
        token: 't',
        request: SplitConfigSaveRequestDto(
          name: 'x',
          plan: const SplitPlan(base: SplitPreference(kind: SplitKind.distanceKm, value: 1)),
        ),
      ),
      throwsA(
        isA<ApiRejectedException>()
            .having((e) => e.statusCode, 'statusCode', 409)
            .having((e) => e.message, 'message', contains('already exists')),
      ),
    );
  });

  test('deleteSplitConfig sends a DELETE to the right path', () async {
    late Uri capturedUrl;
    late String capturedMethod;
    final client = HttpApiClient(
      client: MockClient((request) async {
        capturedUrl = request.url;
        capturedMethod = request.method;
        return http.Response('', 204);
      }),
    );

    await client.deleteSplitConfig(baseUrl: _baseUrl, token: 't', configId: 'c1');

    expect(capturedMethod, 'DELETE');
    expect(capturedUrl.path, '/api/v1/split-configs/c1');
  });
}
