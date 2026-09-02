import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_runner/core/api/api_exception.dart';
import 'package:simple_runner/core/auth/auth_service.dart';

import '../../fakes/fake_api_client.dart';

AuthService _service(FakeApiClient api, Map<String, String> store) {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(store);
  return AuthService(apiClient: api, storage: const FlutterSecureStorage());
}

void main() {
  test('currentState is empty before anything is set', () async {
    final service = _service(FakeApiClient(), {});
    final state = await service.currentState();

    expect(state.serverUrl, isNull);
    expect(state.isSignedIn, isFalse);
  });

  test('setServerUrl persists and is reflected in currentState', () async {
    final service = _service(FakeApiClient(), {});
    await service.setServerUrl('http://192.168.1.10:8000');

    final state = await service.currentState();
    expect(state.serverUrl, 'http://192.168.1.10:8000');
    expect(state.isCleartext, isTrue);
  });

  test('signIn without a server URL throws', () async {
    final service = _service(FakeApiClient(), {});
    expect(
      () => service.signIn(email: 'a@example.com', password: 'x', deviceName: 'Pixel'),
      throwsStateError,
    );
  });

  test('signIn stores the token and email on success', () async {
    final api = FakeApiClient();
    final service = _service(api, {});
    await service.setServerUrl('https://runner.example.com');

    final state = await service.signIn(
      email: 'runner@example.com',
      password: 'secret',
      deviceName: 'Pixel 8',
    );

    expect(state.isSignedIn, isTrue);
    expect(state.token, 'fake-token');
    expect(state.email, 'runner@example.com');
    expect(state.serverUrl, 'https://runner.example.com');
  });

  test('signIn surfaces an ApiException from the server', () async {
    final api = FakeApiClient()
      ..loginHandler = ({
        required baseUrl,
        required email,
        required password,
        required deviceName,
      }) async =>
          throw const ApiUnauthorizedException('Invalid email or password');
    final service = _service(api, {});
    await service.setServerUrl('https://runner.example.com');

    expect(
      () => service.signIn(email: 'a@example.com', password: 'wrong', deviceName: 'Pixel'),
      throwsA(isA<ApiUnauthorizedException>()),
    );
  });

  test('signOut clears the token but keeps the server URL', () async {
    final api = FakeApiClient();
    final service = _service(api, {});
    await service.setServerUrl('https://runner.example.com');
    await service.signIn(email: 'runner@example.com', password: 'x', deviceName: 'Pixel');

    final state = await service.signOut();

    expect(state.isSignedIn, isFalse);
    expect(state.serverUrl, 'https://runner.example.com');
  });

  test('signOut succeeds locally even if the server logout call fails', () async {
    final api = FakeApiClient();
    final service = _service(api, {});
    await service.setServerUrl('https://runner.example.com');
    await service.signIn(email: 'runner@example.com', password: 'x', deviceName: 'Pixel');

    // Simulate the server being unreachable during logout.
    final failingService = AuthService(
      apiClient: _ThrowingLogoutClient(api),
      storage: const FlutterSecureStorage(),
    );
    final state = await failingService.signOut();

    expect(state.isSignedIn, isFalse);
  });

  test('markSignedOutDueToAuthFailure clears the token, keeps the server URL', () async {
    final api = FakeApiClient();
    final service = _service(api, {});
    await service.setServerUrl('https://runner.example.com');
    await service.signIn(email: 'runner@example.com', password: 'x', deviceName: 'Pixel');

    final state = await service.markSignedOutDueToAuthFailure();

    expect(state.isSignedIn, isFalse);
    expect(state.serverUrl, 'https://runner.example.com');
  });
}

class _ThrowingLogoutClient extends FakeApiClient {
  _ThrowingLogoutClient(FakeApiClient delegate) {
    loginHandler = delegate.loginHandler;
  }

  @override
  Future<void> logout({required String baseUrl, required String token}) {
    throw const ApiNetworkException('offline');
  }
}
