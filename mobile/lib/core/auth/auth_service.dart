import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../api/api_client.dart';
import '../api/api_exception.dart';
import 'auth_state.dart';

final authServiceProvider = Provider<AuthService>((ref) {
  return AuthService(apiClient: ref.read(apiClientProvider));
});

const _serverUrlKey = 'server_url';
const _tokenKey = 'device_token';
const _emailKey = 'email';

/// Holds the server URL and device token (secure storage) and drives
/// sign-in/out through [ApiClient]. Plain Dart aside from the storage
/// plugin — no Riverpod dependency here, so SyncService can use it directly
/// and tests don't need a ProviderContainer. The UI wraps this in a
/// Riverpod AsyncNotifier (see features/settings) for reactive display.
class AuthService {
  final ApiClient _apiClient;
  final FlutterSecureStorage _storage;

  AuthService({required ApiClient apiClient, FlutterSecureStorage? storage})
      : _apiClient = apiClient,
        _storage = storage ?? const FlutterSecureStorage();

  Future<AuthState> currentState() async {
    final serverUrl = await _storage.read(key: _serverUrlKey);
    final token = await _storage.read(key: _tokenKey);
    final email = await _storage.read(key: _emailKey);
    return AuthState(serverUrl: serverUrl, token: token, email: email);
  }

  Future<AuthState> setServerUrl(String url) async {
    await _storage.write(key: _serverUrlKey, value: url);
    return currentState();
  }

  Future<AuthState> signIn({
    required String email,
    required String password,
    required String deviceName,
  }) async {
    final state = await currentState();
    final serverUrl = state.serverUrl;
    if (serverUrl == null || serverUrl.isEmpty) {
      throw StateError('Set a server URL before signing in');
    }

    final response = await _apiClient.login(
      baseUrl: serverUrl,
      email: email,
      password: password,
      deviceName: deviceName,
    );
    await _storage.write(key: _tokenKey, value: response.token);
    await _storage.write(key: _emailKey, value: response.user.email);
    return currentState();
  }

  /// Best-effort: the token is deleted locally either way, so a failed
  /// server-side revoke (offline, server down) never strands the user
  /// signed in on the device.
  Future<AuthState> signOut() async {
    final state = await currentState();
    if (state.serverUrl != null && state.token != null) {
      try {
        await _apiClient.logout(baseUrl: state.serverUrl!, token: state.token!);
      } on ApiException {
        // ignore — see doc comment.
      }
    }
    await _storage.delete(key: _tokenKey);
    await _storage.delete(key: _emailKey);
    return currentState();
  }

  /// Called by SyncService when a bearer token is rejected (401) — it was
  /// revoked or expired server-side, not something a retry will fix. Keeps
  /// the server URL, so the user only has to re-enter credentials, and
  /// leaves the run queue untouched (docs/WEB-PLAN.md §6.3).
  Future<AuthState> markSignedOutDueToAuthFailure() async {
    await _storage.delete(key: _tokenKey);
    return currentState();
  }
}
