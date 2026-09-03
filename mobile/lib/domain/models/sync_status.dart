/// The upload state of one [RunRecord]. Sealed so every consumer (UI,
/// SyncService) is forced to handle each case explicitly rather than
/// guessing at a stringly-typed status field.
sealed class SyncStatus {
  const SyncStatus();

  factory SyncStatus.fromJson(Map<String, dynamic> json) {
    return switch (json['type'] as String) {
      'pending' => const SyncStatusPending(),
      'uploading' => const SyncStatusUploading(),
      'uploaded' => SyncStatusUploaded(serverRunId: json['serverRunId'] as String),
      'failed' => SyncStatusFailed(
          error: json['error'] as String,
          attempts: json['attempts'] as int,
          retryable: json['retryable'] as bool,
        ),
      final other => throw ArgumentError('Unknown SyncStatus type: $other'),
    };
  }

  Map<String, dynamic> toJson();
}

class SyncStatusPending extends SyncStatus {
  const SyncStatusPending();

  @override
  Map<String, dynamic> toJson() => {'type': 'pending'};
}

class SyncStatusUploading extends SyncStatus {
  const SyncStatusUploading();

  @override
  Map<String, dynamic> toJson() => {'type': 'uploading'};
}

class SyncStatusUploaded extends SyncStatus {
  final String serverRunId;

  const SyncStatusUploaded({required this.serverRunId});

  @override
  Map<String, dynamic> toJson() => {'type': 'uploaded', 'serverRunId': serverRunId};
}

/// [retryable] distinguishes a transient failure (network/timeout/5xx/429 —
/// SyncService will retry with backoff) from a permanent one (other 4xx,
/// e.g. a rejected file — surfaced for the user to act on, never auto-retried).
class SyncStatusFailed extends SyncStatus {
  final String error;
  final int attempts;
  final bool retryable;

  const SyncStatusFailed({
    required this.error,
    required this.attempts,
    required this.retryable,
  });

  @override
  Map<String, dynamic> toJson() => {
        'type': 'failed',
        'error': error,
        'attempts': attempts,
        'retryable': retryable,
      };
}
