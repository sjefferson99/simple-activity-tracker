import 'package:flutter_test/flutter_test.dart';
import 'package:simple_runner/domain/models/sync_status.dart';

void main() {
  test('pending round-trips through JSON', () {
    const status = SyncStatusPending();
    expect(SyncStatus.fromJson(status.toJson()), isA<SyncStatusPending>());
  });

  test('uploading round-trips through JSON', () {
    const status = SyncStatusUploading();
    expect(SyncStatus.fromJson(status.toJson()), isA<SyncStatusUploading>());
  });

  test('uploaded round-trips through JSON with its serverRunId', () {
    const status = SyncStatusUploaded(serverRunId: 'server-123');
    final result = SyncStatus.fromJson(status.toJson());
    expect(result, isA<SyncStatusUploaded>());
    expect((result as SyncStatusUploaded).serverRunId, 'server-123');
  });

  test('failed round-trips through JSON with error/attempts/retryable', () {
    const status = SyncStatusFailed(error: 'boom', attempts: 3, retryable: true);
    final result = SyncStatus.fromJson(status.toJson());
    expect(result, isA<SyncStatusFailed>());
    final failed = result as SyncStatusFailed;
    expect(failed.error, 'boom');
    expect(failed.attempts, 3);
    expect(failed.retryable, isTrue);
  });

  test('fromJson throws on an unknown type', () {
    expect(
      () => SyncStatus.fromJson({'type': 'nonsense'}),
      throwsArgumentError,
    );
  });
}
