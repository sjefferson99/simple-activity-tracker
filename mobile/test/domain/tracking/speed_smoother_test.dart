import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/tracking/speed_smoother.dart';

void main() {
  group('SpeedSmoother', () {
    test('the first fix is trusted fully with no prior value to blend against', () {
      final smoother = SpeedSmoother();
      final now = DateTime(2026, 1, 1, 12, 0, 0);
      expect(smoother.addSpeed(5.0, now), 5.0);
      expect(smoother.smoothedMps, 5.0);
    });

    test('a single noisy fix is damped, not fully trusted', () {
      final smoother = SpeedSmoother();
      var now = DateTime(2026, 1, 1, 12, 0, 0);
      smoother.addSpeed(3.0, now);

      // A one-second-later fix reporting a wild jump.
      now = now.add(const Duration(seconds: 1));
      final result = smoother.addSpeed(10.0, now);

      expect(result, greaterThan(3.0));
      expect(result, lessThan(10.0));
    });

    test('a real, sustained speed change is fully reflected within a few seconds', () {
      final smoother = SpeedSmoother();
      var now = DateTime(2026, 1, 1, 12, 0, 0);
      smoother.addSpeed(3.0, now);

      // Ten fixes at the new speed, 1s apart — a genuine pace change, not a
      // single blip, so it must not still be dragged toward 3.0 by then.
      double result = 3.0;
      for (var i = 0; i < 10; i++) {
        now = now.add(const Duration(seconds: 1));
        result = smoother.addSpeed(5.0, now);
      }

      expect(result, closeTo(5.0, 0.1));
    });

    test('a long gap trusts the new fix almost fully rather than staying stuck', () {
      final smoother = SpeedSmoother();
      var now = DateTime(2026, 1, 1, 12, 0, 0);
      smoother.addSpeed(3.0, now);

      // A long stall (weak signal, backgrounded app) before the next fix.
      now = now.add(const Duration(minutes: 5));
      final result = smoother.addSpeed(8.0, now);

      expect(result, closeTo(8.0, 0.01));
    });

    test('a non-positive gap between fixes resets rather than dividing unreasonably', () {
      final smoother = SpeedSmoother();
      final now = DateTime(2026, 1, 1, 12, 0, 0);
      smoother.addSpeed(3.0, now);

      // A duplicate/out-of-order timestamp.
      final result = smoother.addSpeed(9.0, now);

      expect(result, 9.0);
    });

    test('reset clears the smoothed value so the next fix starts fresh', () {
      final smoother = SpeedSmoother();
      final now = DateTime(2026, 1, 1, 12, 0, 0);
      smoother.addSpeed(3.0, now);
      expect(smoother.smoothedMps, isNotNull);

      smoother.reset();
      expect(smoother.smoothedMps, isNull);

      // The next fix after a reset must be trusted fully, like a first fix
      // ever — otherwise a pause/resume or re-anchor would drag the new
      // segment's first reading toward whatever was true before the gap.
      expect(smoother.addSpeed(6.0, now), 6.0);
    });
  });
}
