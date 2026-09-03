/// The app's current sign-in state — pure data, no storage/network concerns.
class AuthState {
  final String? serverUrl;
  final String? token;
  final String? email;

  const AuthState({this.serverUrl, this.token, this.email});

  static const empty = AuthState();

  bool get isSignedIn => token != null;
  bool get hasServerUrl => serverUrl != null && serverUrl!.isNotEmpty;

  /// A configured `http(s)://…` URL is unencrypted only over plain http —
  /// used to show the Settings screen's cleartext warning (§6.3).
  bool get isCleartext => serverUrl != null && serverUrl!.startsWith('http://');

  AuthState copyWith({
    String? serverUrl,
    String? token,
    bool clearToken = false,
    String? email,
    bool clearEmail = false,
  }) =>
      AuthState(
        serverUrl: serverUrl ?? this.serverUrl,
        token: clearToken ? null : (token ?? this.token),
        email: clearEmail ? null : (email ?? this.email),
      );
}
