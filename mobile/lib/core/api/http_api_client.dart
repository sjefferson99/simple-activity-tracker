import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';

import '../../domain/models/run_summary.dart';
import 'api_client.dart';
import 'api_exception.dart';
import 'cert_trust_store.dart';
import 'dto/analysis_dto.dart';
import 'dto/login_response_dto.dart';
import 'dto/run_dto.dart';
import 'dto/user_dto.dart';

const _requestTimeout = Duration(seconds: 30);

/// The outcome of [decideCertificateTrust]: either accept the handshake, or
/// reject it with the [ApiCertificateException] to surface to the caller.
class CertificateTrustDecision {
  final bool trusted;
  final ApiCertificateException? rejection;

  const CertificateTrustDecision.trust() : trusted = true, rejection = null;

  CertificateTrustDecision.reject(this.rejection) : trusted = false;
}

/// Pure trust-on-first-use decision, factored out of
/// [HttpApiClient._acceptCertificate] so it's unit-testable without a real
/// `X509Certificate` (its factory constructor is a VM intrinsic — it can't
/// be built in a plain unit test). Trusts [fingerprint] only if it exactly
/// matches [pinnedFingerprint] for [host]; a `null` pin (never trusted) and
/// a mismatched pin (cert changed since it was trusted) are both rejected,
/// with a message that tells the two cases apart.
CertificateTrustDecision decideCertificateTrust({
  required String fingerprint,
  required String host,
  required String? pinnedFingerprint,
}) {
  if (pinnedFingerprint != null && pinnedFingerprint == fingerprint) {
    return const CertificateTrustDecision.trust();
  }
  return CertificateTrustDecision.reject(ApiCertificateException(
    pinnedFingerprint == null
        ? 'The server at $host presented a certificate that isn\'t from a trusted '
            'authority. If this is your own server with a self-signed certificate, '
            'confirm the fingerprint to trust it.'
        : 'The certificate presented by $host has changed and no longer matches the '
            'one you trusted. Confirm the new fingerprint before trusting it again — '
            'this can happen after legitimately regenerating the certificate, or if '
            'something on the network is intercepting the connection.',
    host: host,
    fingerprint: fingerprint,
  ));
}

/// The only file in the app that knows the server's URLs and JSON wire
/// format — everything else talks to [ApiClient]. Wraps every call in the
/// same error mapping (docs/WEB-PLAN.md §6.3): network/timeout/5xx/429 are
/// retryable, 401 is unauthorized, other 4xx are permanent rejections.
///
/// Certificate trust: the default [http.Client] uses the platform trust
/// store, which rejects a self-signed certificate (e.g.
/// deploy/standalone-tls/) outright. This class instead builds its own
/// `dart:io` [HttpClient] with a `badCertificateCallback` that consults
/// [CertTrustStore] — untrusted-but-pinned-for-this-host certs are accepted,
/// anything else throws [ApiCertificateException] with the cert's
/// fingerprint so the UI can offer trust-on-first-use. This never weakens
/// validation for a certificate the platform already trusts (a real CA-
/// issued cert) — the callback only runs when the platform already rejected it.
class HttpApiClient implements ApiClient {
  late final http.Client _client;
  final CertTrustStore _certTrustStore;

  /// Whether this instance built its own cert-checking [IOClient] (true) or
  /// was handed a [client] by the caller (false, e.g. `MockClient` in
  /// tests). Only the former can ever invoke `badCertificateCallback`, so
  /// `_send` skips warming [_certTrustStore] entirely otherwise — avoids
  /// touching the secure-storage platform channel from plain unit tests
  /// that inject a fake transport and never exercise TLS at all.
  final bool _checksCertificates;

  /// Set by `badCertificateCallback` (which must be synchronous, so it
  /// can't await the async [CertTrustStore] read itself) whenever it
  /// rejects a handshake — `_send`'s SocketException handler, which runs
  /// right after the failed call, reads it to throw a specific
  /// [ApiCertificateException] instead of a generic [ApiNetworkException].
  /// At most one handshake is ever in flight per `_send` call, so a single
  /// field is enough — it's cleared at the start of every `_send`.
  ApiCertificateException? _lastCertRejection;

  HttpApiClient({http.Client? client, CertTrustStore? certTrustStore})
      : _certTrustStore = certTrustStore ?? CertTrustStore(),
        _checksCertificates = client == null {
    if (client != null) {
      _client = client;
      return;
    }
    final ioClient = HttpClient()..badCertificateCallback = _acceptCertificate;
    _client = IOClient(ioClient);
  }

  /// Must run synchronously (the platform API gives no async hook here), so
  /// it only computes the fingerprint and delegates the accept/reject
  /// decision to [decideCertificateTrust], which is pure and separately
  /// unit-testable — `X509Certificate` itself can't be constructed in a
  /// plain unit test.
  bool _acceptCertificate(X509Certificate cert, String host, int port) {
    final decision = decideCertificateTrust(
      fingerprint: sha256.convert(cert.der).toString(),
      host: host,
      pinnedFingerprint: _certTrustStore.pinnedFingerprintSync(host),
    );
    _lastCertRejection = decision.rejection;
    return decision.trusted;
  }

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
    if (_checksCertificates) await _certTrustStore.ensureLoaded();
    _lastCertRejection = null;
    final http.Response response;
    try {
      response = await call();
    } on TimeoutException catch (e) {
      throw ApiTimeoutException(e.toString());
    } on HandshakeException catch (e) {
      // badCertificateCallback ran and returned false just before this was
      // thrown, so _lastCertRejection holds the specific reason (untrusted
      // vs. changed-since-pinned) and the fingerprint to show the user.
      throw _lastCertRejection ?? ApiNetworkException(e.toString());
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
    // dart:io's HttpClient never auto-follows a redirect on a non-GET
    // request (the plain http.Client backing this class is a thin wrapper
    // over it), so a plain-http URL in front of a proxy that redirects to
    // https (like deploy/standalone-tls/nginx.conf) lands here with the
    // redirect's HTML body rather than JSON. Surface that plainly instead of
    // failing obscurely in the JSON decode a caller does next.
    if (status >= 300 && status < 400) {
      throw ApiRejectedException(
        'The server redirected this request (HTTP $status). If the server URL '
        'starts with http://, try https:// instead.',
        statusCode: status,
      );
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
