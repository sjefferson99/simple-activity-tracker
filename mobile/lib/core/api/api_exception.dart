/// The typed outcomes an [ApiClient] call can fail with. SyncService maps
/// these onto retryable vs permanent failures (docs/WEB-PLAN.md §6.3) —
/// callers should never need to inspect an HTTP status code themselves.
sealed class ApiException implements Exception {
  final String message;

  const ApiException(this.message);
}

/// No connectivity, DNS failure, connection refused, etc. Retryable.
class ApiNetworkException extends ApiException {
  const ApiNetworkException(super.message);
}

/// The request took too long. Retryable.
class ApiTimeoutException extends ApiException {
  const ApiTimeoutException(super.message);
}

/// The device's token/session was rejected (401) — the caller should mark
/// the app signed-out and prompt the user to sign in again. Not retryable
/// on its own; retried automatically once the user re-authenticates.
class ApiUnauthorizedException extends ApiException {
  const ApiUnauthorizedException(super.message);
}

/// Server returned 429 — too many requests. Retryable (with backoff).
class ApiRateLimitedException extends ApiException {
  const ApiRateLimitedException(super.message);
}

/// Server returned 5xx. Retryable.
class ApiServerException extends ApiException {
  final int statusCode;

  const ApiServerException(super.message, {required this.statusCode});
}

/// Any other 4xx (400, 404, 409, 413, …) — the server rejected the request
/// on its merits (bad file, oversize upload, ...) and retrying unchanged
/// would fail the same way every time. Not retryable.
class ApiRejectedException extends ApiException {
  final int statusCode;

  const ApiRejectedException(super.message, {required this.statusCode});
}
