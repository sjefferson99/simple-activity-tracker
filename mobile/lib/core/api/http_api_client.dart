import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../../domain/models/run_summary.dart';
import 'api_client.dart';
import 'api_exception.dart';
import 'dto/analysis_dto.dart';
import 'dto/login_response_dto.dart';
import 'dto/run_dto.dart';
import 'dto/user_dto.dart';

const _requestTimeout = Duration(seconds: 30);

/// The only file in the app that knows the server's URLs and JSON wire
/// format — everything else talks to [ApiClient]. Wraps every call in the
/// same error mapping (docs/WEB-PLAN.md §6.3): network/timeout/5xx/429 are
/// retryable, 401 is unauthorized, other 4xx are permanent rejections.
class HttpApiClient implements ApiClient {
  final http.Client _client;

  HttpApiClient({http.Client? client}) : _client = client ?? http.Client();

  Uri _uri(String baseUrl, String path) => Uri.parse('$baseUrl$path');

  Map<String, String> _authHeaders(String token) => {'Authorization': 'Bearer $token'};

  @override
  Future<LoginResponseDto> login({
    required String baseUrl,
    required String email,
    required String password,
    required String deviceName,
  }) async {
    final response = await _send(() => _client
        .post(
          _uri(baseUrl, '/api/v1/auth/login'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({
            'email': email,
            'password': password,
            'device_name': deviceName,
          }),
        )
        .timeout(_requestTimeout));
    return LoginResponseDto.fromJson(_decodeJson(response));
  }

  @override
  Future<void> logout({required String baseUrl, required String token}) async {
    await _send(() => _client
        .post(_uri(baseUrl, '/api/v1/auth/logout'), headers: _authHeaders(token))
        .timeout(_requestTimeout));
  }

  @override
  Future<UserDto> me({required String baseUrl, required String token}) async {
    final response = await _send(() =>
        _client.get(_uri(baseUrl, '/api/v1/me'), headers: _authHeaders(token)).timeout(_requestTimeout));
    return UserDto.fromJson(_decodeJson(response));
  }

  @override
  Future<RunDto> uploadRun({
    required String baseUrl,
    required String token,
    required RunSummary summary,
    required File gpxFile,
  }) async {
    final response = await _send(() async {
      final request = http.MultipartRequest('POST', _uri(baseUrl, '/api/v1/runs'))
        ..headers.addAll(_authHeaders(token))
        ..fields['summary'] = jsonEncode(summary.toJson())
        ..files.add(await http.MultipartFile.fromPath('gpx', gpxFile.path));
      final streamed = await _client.send(request).timeout(_requestTimeout);
      return http.Response.fromStream(streamed);
    });
    return RunDto.fromJson(_decodeJson(response));
  }

  @override
  Future<AnalysisDto> getAnalysis({
    required String baseUrl,
    required String token,
    required String serverRunId,
  }) async {
    final response = await _send(() => _client
        .get(_uri(baseUrl, '/api/v1/runs/$serverRunId/analysis'), headers: _authHeaders(token))
        .timeout(_requestTimeout));
    return AnalysisDto.fromJson(_decodeJson(response));
  }

  Map<String, dynamic> _decodeJson(http.Response response) =>
      jsonDecode(response.body) as Map<String, dynamic>;

  /// Runs [call], mapping transport failures and non-2xx statuses onto the
  /// [ApiException] hierarchy. A 202 (analysis still pending) is treated as
  /// success — callers read `status` off the decoded body, not the HTTP code.
  Future<http.Response> _send(Future<http.Response> Function() call) async {
    final http.Response response;
    try {
      response = await call();
    } on TimeoutException catch (e) {
      throw ApiTimeoutException(e.toString());
    } on SocketException catch (e) {
      throw ApiNetworkException(e.toString());
    } on http.ClientException catch (e) {
      throw ApiNetworkException(e.toString());
    }

    final status = response.statusCode;
    if (status == 200 || status == 201 || status == 202 || status == 204) {
      return response;
    }
    if (status == 401) {
      throw ApiUnauthorizedException(_errorMessage(response));
    }
    if (status == 429) {
      throw ApiRateLimitedException(_errorMessage(response));
    }
    if (status >= 500) {
      throw ApiServerException(_errorMessage(response), statusCode: status);
    }
    throw ApiRejectedException(_errorMessage(response), statusCode: status);
  }

  /// The server's error shape is `{"error": {"code", "message"}}` (§5.2) —
  /// fall back to the raw body if it doesn't parse (e.g. an upstream proxy
  /// error page that never reached the app).
  String _errorMessage(http.Response response) {
    try {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      final error = body['error'] as Map<String, dynamic>?;
      return (error?['message'] as String?) ?? response.body;
    } on Object {
      return response.body;
    }
  }
}
