import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/models/track_point.dart';
import 'package:simple_activity_tracker/domain/tracking/display_speed_window.dart';

/// One degree of longitude at the equator is ~111,195m, matching the
/// convention other tracking tests use — build points along the equator so
/// distances are easy to reason about.
TrackPoint _pointAtMeters(double metersFromOrigin, DateTime timestamp) {
  final degrees = metersFromOrigin / 111195;
  return TrackPoint(
    latitude: 0,
    longitude: degrees,
    timestamp: timestamp,
    accuracyMeters: 5,
    hasAccuracy: true,
  );
}

void main() {
  group('DisplaySpeedWindow', () {
    test('returns null for the first point (nothing to span yet)', () {
      final window = DisplaySpeedWindow();
      final start = DateTime(2026, 1, 1);
      expect(window.addPoint(_pointAtMeters(0, start)), isNull);
    });

    test(
      'a steady pace over several fixes settles to the true speed, not a '
      'per-fix chip reading',
      () {
        final window = DisplaySpeedWindow();
        final start = DateTime(2026, 1, 1);
        // 1.5 m/s steady, 1s fixes.
        double? last;
        for (var t = 0; t <= 5; t++) {
          last = window.addPoint(_pointAtMeters(1.5 * t, start.add(Duration(seconds: t))));
        }
        expect(last, closeTo(1.5, 0.01));
      },
    );

    test('the window excludes points older than ~6 seconds', () {
      final window = DisplaySpeedWindow();
      final start = DateTime(2026, 1, 1);
      // Fast for the first 2s, then a single very recent fix implies the
      // window should mostly reflect the recent pace once old points age out.
      window.addPoint(_pointAtMeters(0, start));
      window.addPoint(_pointAtMeters(10, start.add(const Duration(seconds: 1))));
      window.addPoint(_pointAtMeters(20, start.add(const Duration(seconds: 2))));
      // At t=20s, only fixes within the last 6s should remain in the window
      // (the t=0/1/2 fixes are long gone) — a lone recent pair spanning 1s
      // at 1 m/s should read ~1 m/s, not still show the earlier fast pace.
      window.addPoint(_pointAtMeters(21, start.add(const Duration(seconds: 20))));
      final speed = window.addPoint(_pointAtMeters(22, start.add(const Duration(seconds: 21))));
      expect(speed, closeTo(1.0, 0.05));
    });

    test(
      'sums path length rather than start-to-end displacement, so a turn '
      'inside the window is not cut short (issue #50 follow-up)',
      () {
        final window = DisplaySpeedWindow();
        final start = DateTime(2026, 1, 1);
        // An out-and-back: 5m east at 1 m/s, then 5m back west at 1 m/s.
        // Start-to-end displacement across the whole window is ~0m (a
        // real per-fix chord distance, not exactly 0, but far below the
        // true 10m of path covered) — path-summing must still read ~1 m/s,
        // not a near-zero speed from the turn cancelling out net movement.
        window.addPoint(_pointAtMeters(0, start));
        window.addPoint(_pointAtMeters(1, start.add(const Duration(seconds: 1))));
        window.addPoint(_pointAtMeters(2, start.add(const Duration(seconds: 2))));
        window.addPoint(_pointAtMeters(3, start.add(const Duration(seconds: 3))));
        window.addPoint(_pointAtMeters(4, start.add(const Duration(seconds: 4))));
        window.addPoint(_pointAtMeters(5, start.add(const Duration(seconds: 5))));
        window.addPoint(_pointAtMeters(4, start.add(const Duration(seconds: 6))));
        final speed = window.addPoint(_pointAtMeters(3, start.add(const Duration(seconds: 7))));
        expect(speed, closeTo(1.0, 0.05));
      },
    );

    test('reset clears the window so the next reading starts fresh', () {
      final window = DisplaySpeedWindow();
      final start = DateTime(2026, 1, 1);
      window.addPoint(_pointAtMeters(0, start));
      window.addPoint(_pointAtMeters(5, start.add(const Duration(seconds: 1))));

      window.reset();

      // Immediately after reset, a single point has nothing to span yet.
      expect(window.addPoint(_pointAtMeters(100, start.add(const Duration(minutes: 5)))), isNull);
    });

    test('a zero-duration gap between fixes is ignored, not a divide-by-zero', () {
      final window = DisplaySpeedWindow();
      final start = DateTime(2026, 1, 1);
      window.addPoint(_pointAtMeters(0, start));
      // Same timestamp as the previous fix.
      expect(window.addPoint(_pointAtMeters(1, start)), isNull);
    });
  });
}
