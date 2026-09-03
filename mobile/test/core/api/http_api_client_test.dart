import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:simple_runner/core/api/api_exception.dart';
import 'package:simple_runner/core/api/http_api_client.dart';
import 'package:simple_runner/domain/models/run_summary.dart';

const _baseUrl = 'https://runner.example.com';

RunSummary _summary() => RunSummary(
      clientRunId: 'abc',
      startedAt: DateTime.utc(2026, 1, 1),
      endedAt: DateTime.utc(2026, 1, 1, 0, 30),
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
      client: MockClient((request) async => http.Response(
            jsonEncode({
              'error': {'code': 'invalid_credentials', 'message': 'Invalid email or password'}
            }),
            401,
          )),
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

  test('throws ApiRejectedException with a helpful message on a 3xx redirect', () async {
    // Reproduces deploy/standalone-tls/nginx.conf redirecting http:// to
    // https:// with a 301 — dart:io's HttpClient never auto-follows a
    // redirect on a POST, so this response reaches HttpApiClient as-is.
    final client = HttpApiClient(
      client: MockClient((request) async => http.Response(
            '<html>301 Moved Permanently</html>',
            301,
            headers: {'location': 'https://runner.example.com/api/v1/auth/login'},
          )),
    );

    await expectLater(
      () => client.login(
        baseUrl: _baseUrl,
        email: 'runner@example.com',
        password: 'secret',
        deviceName: 'Pixel 8',
      ),
      throwsA(isA<ApiRejectedException>().having(
        (e) => e.message,
        'message',
        contains('https://'),
      )),
    );
  });

  test('throws ApiRateLimitedException on 429', () async {
    final client = HttpApiClient(
      client: MockClient((request) async => http.Response('{"error":{"code":"rate_limited","message":"slow down"}}', 429)),
    );

    expect(
      () => client.me(baseUrl: _baseUrl, token: 't'),
      throwsA(isA<ApiRateLimitedException>()),
    );
  });

  test('throws ApiServerException on 500', () async {
    final client = HttpApiClient(
      client: MockClient((request) async => http.Response('internal error', 500)),
    );

    expect(
      () => client.me(baseUrl: _baseUrl, token: 't'),
      throwsA(isA<ApiServerException>()),
    );
  });

  test('throws ApiRejectedException on other 4xx (e.g. 413)', () async {
    final client = HttpApiClient(
      client: MockClient((request) async => http.Response(
            '{"error":{"code":"gpx_too_large","message":"too big"}}',
            413,
          )),
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
      client: MockClient((request) async => throw const SocketException('no route')),
    );

    expect(
      () => client.me(baseUrl: _baseUrl, token: 't'),
      throwsA(isA<ApiNetworkException>()),
    );
  });

  test('uploadRun sends the summary and file as multipart fields', () async {
    late Map<String, String> capturedFields;
    late List<http.MultipartFile> capturedFiles;

    final client = HttpApiClient(
      client: MockClient.streaming((request, bodyStream) async {
        final multipart = request as http.MultipartRequest;
        capturedFields = multipart.fields;
        capturedFiles = multipart.files;
        return http.StreamedResponse(
          Stream.value(utf8.encode(jsonEncode(jsonDecode(
              File('test/fixtures/run_dto_sample.json').readAsStringSync())))),
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

    expect(jsonDecode(capturedFields['summary']!)['client_run_id'], 'abc');
    expect(capturedFiles, hasLength(1));
    expect(capturedFiles.first.field, 'gpx');
    expect(result.id, '44444444-4444-4444-4444-444444444444');
  });

  test('getAnalysis treats 202 (pending) as success, not an error', () async {
    final client = HttpApiClient(
      client: MockClient((request) async => http.Response(
            jsonEncode({'status': 'pending', 'result': null}),
            202,
          )),
    );

    final result = await client.getAnalysis(
      baseUrl: _baseUrl,
      token: 't',
      serverRunId: 'run-1',
    );

    expect(result.isPending, isTrue);
  });
}
