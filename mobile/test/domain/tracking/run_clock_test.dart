import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/tracking/run_clock.dart';

void main() {
  final start = DateTime.utc(2026, 1, 1, 9);
  DateTime at(int seconds) => start.add(Duration(seconds: seconds));

  test('elapsed is wall-clock time since start', () {
    final clock = RunClock(startedAt: start);
    expect(clock.elapsed(at(0)), Duration.zero);
    expect(clock.elapsed(at(90)), const Duration(seconds: 90));
  });

  test('pausing freezes elapsed at the pause instant', () {
    final clock = RunClock(startedAt: start)..pause(at(30));
    expect(clock.isPaused, isTrue);
    expect(clock.elapsed(at(30)), const Duration(seconds: 30));
    expect(clock.elapsed(at(300)), const Duration(seconds: 30));
  });

  test('resuming excludes the paused span from elapsed', () {
    final clock = RunClock(startedAt: start)
      ..pause(at(30))
      ..resume(at(50));
    expect(clock.isPaused, isFalse);
    // 60s of wall clock, 20s of it paused.
    expect(clock.elapsed(at(60)), const Duration(seconds: 40));
  });

  test('multiple pauses accumulate', () {
    final clock = RunClock(startedAt: start)
      ..pause(at(10))
      ..resume(at(20))
      ..pause(at(30))
      ..resume(at(45));
    expect(clock.elapsed(at(60)), const Duration(seconds: 35));
  });

  test('a second pause while paused does not move the pause instant', () {
    final clock = RunClock(startedAt: start)
      ..pause(at(10))
      ..pause(at(20))
      ..resume(at(30));
    expect(clock.elapsed(at(30)), const Duration(seconds: 10));
  });

  test('resume when not paused is a no-op', () {
    final clock = RunClock(startedAt: start)..resume(at(10));
    expect(clock.elapsed(at(20)), const Duration(seconds: 20));
  });

  test('never reports a negative elapsed', () {
    final clock = RunClock(startedAt: start);
    expect(
      clock.elapsed(start.subtract(const Duration(seconds: 5))),
      Duration.zero,
    );
  });
}
