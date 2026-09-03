import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_runner/core/api/cert_trust_store.dart';
import 'package:simple_runner/core/api/http_api_client.dart';

CertTrustStore _store(Map<String, String> backing) {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(backing);
  return CertTrustStore(storage: const FlutterSecureStorage());
}

void main() {
  group('decideCertificateTrust', () {
    test('trusts a fingerprint that matches the pin', () {
      final decision = decideCertificateTrust(
        fingerprint: 'abc123',
        host: 'runner.example.com',
        pinnedFingerprint: 'abc123',
      );

      expect(decision.trusted, isTrue);
      expect(decision.rejection, isNull);
    });

    test('rejects with no-pin message when nothing is pinned yet', () {
      final decision = decideCertificateTrust(
        fingerprint: 'abc123',
        host: 'runner.example.com',
        pinnedFingerprint: null,
      );

      expect(decision.trusted, isFalse);
      expect(decision.rejection!.host, 'runner.example.com');
      expect(decision.rejection!.fingerprint, 'abc123');
      expect(decision.rejection!.message, contains('trusted'));
    });

    test('rejects with a changed-certificate message when the pin no longer matches', () {
      final decision = decideCertificateTrust(
        fingerprint: 'new-fingerprint',
        host: 'runner.example.com',
        pinnedFingerprint: 'old-fingerprint',
      );

      expect(decision.trusted, isFalse);
      expect(decision.rejection!.message, contains('changed'));
    });
  });

  group('CertTrustStore', () {
    test('pinnedFingerprintSync is null before ensureLoaded', () {
      final store = _store({'cert_pin_runner.example.com': 'abc123'});
      expect(store.pinnedFingerprintSync('runner.example.com'), isNull);
    });

    test('ensureLoaded warms the sync cache from storage', () async {
      final store = _store({'cert_pin_runner.example.com': 'abc123'});
      await store.ensureLoaded();
      expect(store.pinnedFingerprintSync('runner.example.com'), 'abc123');
    });

    test('trust writes through to both storage and the sync cache immediately', () async {
      final store = _store({});
      await store.trust('runner.example.com', 'abc123');

      expect(store.pinnedFingerprintSync('runner.example.com'), 'abc123');
      expect(await store.pinnedFingerprint('runner.example.com'), 'abc123');
    });

    test('untrust removes the pin from both storage and the sync cache', () async {
      final store = _store({'cert_pin_runner.example.com': 'abc123'});
      await store.ensureLoaded();
      await store.untrust('runner.example.com');

      expect(store.pinnedFingerprintSync('runner.example.com'), isNull);
    });

    test('a pin for one host is never returned for another', () async {
      final store = _store({});
      await store.trust('runner.example.com', 'abc123');

      expect(store.pinnedFingerprintSync('evil.example.com'), isNull);
    });
  });
}
