/// Wall-clock time a run has been going, excluding explicit pauses — what
/// every mainstream tracker labels "Time". Deliberately separate from
/// [MetricsEngine]'s moving time: that only advances when a GPS segment is
/// *accepted*, so standing still, walking under a filter threshold, or a
/// weak fix all freeze it — which reads as the app being broken during
/// exactly the conditions the filters exist for (docs/GPS-METRICS-PLAN.md
/// §1.4). Pure Dart; the caller supplies `now` so it's testable without a
/// real clock.
class RunClock {
  final DateTime startedAt;
  DateTime? _pausedAt;
  Duration _pausedTotal = Duration.zero;

  RunClock({required this.startedAt});

  bool get isPaused => _pausedAt != null;

  /// Idempotent — a second pause while already paused keeps the original
  /// pause instant, so the paused span isn't shortened.
  void pause(DateTime now) {
    _pausedAt ??= now;
  }

  /// No-op if not paused.
  void resume(DateTime now) {
    final pausedAt = _pausedAt;
    if (pausedAt == null) return;
    _pausedTotal += now.difference(pausedAt);
    _pausedAt = null;
  }

  /// Time since [startedAt] minus every completed pause. While paused, the
  /// clock reads as of the pause instant, so the value holds steady.
  Duration elapsed(DateTime now) {
    final end = _pausedAt ?? now;
    final value = end.difference(startedAt) - _pausedTotal;
    return value.isNegative ? Duration.zero : value;
  }
}
