import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Persists trust-on-first-use certificate pins: `host -> SHA-256
/// fingerprint of the certificate the user explicitly confirmed`. Used to
/// accept a self-signed certificate (e.g. deploy/standalone-tls/) for one
/// specific server without disabling certificate validation for anything
/// else — a certificate presented by a different host, or a *different*
/// certificate later presented by the same host (rotation, or a real
/// MITM), is never trusted just because some other pin exists.
///
/// Plain Dart, no Riverpod — [HttpApiClient] reads it directly on every
/// connection attempt, the same way [AuthService] is plain Dart so it can be
/// used outside widget code.
///
/// [dart:io]'s `badCertificateCallback` must return synchronously — it has
/// no async hook — so pins are mirrored into an in-memory [_cache] that
/// every write updates immediately and every read is seeded from via
/// [ensureLoaded]. Call [ensureLoaded] once before the first request that
/// might hit a pinned host (e.g. app startup, or right before signing in);
/// [pinnedFingerprintSync] returns `null` for a host it hasn't loaded yet,
/// which is safe — it just means a pinned cert looks untrusted until the
/// cache is warmed, never the other way around.
class CertTrustStore {
  static const _keyPrefix = 'cert_pin_';

  final FlutterSecureStorage _storage;
  final Map<String, String> _cache = {};
  bool _loaded = false;

  CertTrustStore({FlutterSecureStorage? storage}) : _storage = storage ?? const FlutterSecureStorage();

  /// Loads every stored pin into the in-memory cache. Cheap (a handful of
  /// small values at most) and idempotent — safe to call more than once;
  /// only the first call actually reads storage.
  Future<void> ensureLoaded() async {
    if (_loaded) return;
    final all = await _storage.readAll();
    for (final entry in all.entries) {
      if (entry.key.startsWith(_keyPrefix)) {
        _cache[entry.key.substring(_keyPrefix.length)] = entry.value;
      }
    }
    _loaded = true;
  }

  /// Synchronous read for `badCertificateCallback`. Returns `null` if
  /// [ensureLoaded] hasn't completed yet or no pin exists for [host].
  String? pinnedFingerprintSync(String host) => _cache[host];

  Future<String?> pinnedFingerprint(String host) async {
    await ensureLoaded();
    return _cache[host];
  }

  Future<void> trust(String host, String fingerprint) async {
    await _storage.write(key: '$_keyPrefix$host', value: fingerprint);
    _cache[host] = fingerprint;
  }

  Future<void> untrust(String host) async {
    await _storage.delete(key: '$_keyPrefix$host');
    _cache.remove(host);
  }
}
