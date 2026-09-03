import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'auth_service.dart';
import 'auth_state.dart';

/// Reactive wrapper over [AuthService] for widgets — AuthService itself
/// stays plain Dart (see its doc comment) so SyncService and tests can use
/// it without any Riverpod machinery.
final authStateControllerProvider =
    AsyncNotifierProvider<AuthStateController, AuthState>(AuthStateController.new);

class AuthStateController extends AsyncNotifier<AuthState> {
  @override
  Future<AuthState> build() => ref.read(authServiceProvider).currentState();

  /// Mutation methods rethrow on failure rather than routing the error
  /// through `state` — an AsyncError here would replace the whole
  /// AsyncValue.data the Settings screen renders the sign-in form from,
  /// wiping the form (and the server URL the user just typed) the moment a
  /// login attempt fails. Callers catch the exception directly and show it
  /// next to the control that triggered it instead.
  Future<void> setServerUrl(String url) async {
    state = AsyncData(await ref.read(authServiceProvider).setServerUrl(url));
  }

  Future<void> signIn({
    required String email,
    required String password,
    required String deviceName,
  }) async {
    state = AsyncData(await ref.read(authServiceProvider).signIn(
          email: email,
          password: password,
          deviceName: deviceName,
        ));
  }

  Future<void> signOut() async {
    state = AsyncData(await ref.read(authServiceProvider).signOut());
  }

  /// Refreshes from storage without an API call — used after SyncService
  /// calls markSignedOutDueToAuthFailure() on the underlying AuthService,
  /// so the UI picks up the change on its next read.
  Future<void> refresh() async {
    state = AsyncData(await ref.read(authServiceProvider).currentState());
  }
}
