import 'package:flutter_test/flutter_test.dart';
import 'package:simple_runner/domain/tracking/metrics_engine.dart';
import 'package:simple_runner/domain/models/track_point.dart';

/// One degree of longitude at the equator is ~111,195m, matching the
/// haversine implementation under test elsewhere — build points along the
/// equator so distances are easy to reason about.
TrackPoint _pointAtMeters(
  double metersFromOrigin,
  DateTime timestamp, {
  double accuracyMeters = 5,
}) {
  final degrees = metersFromOrigin / 111195;
  return TrackPoint(
    latitude: 0,
    longitude: degrees,
    timestamp: timestamp,
    accuracyMeters: accuracyMeters,
  );
}

void main() {
  group('MetricsEngine basic accumulation', () {
    test('first point produces zeroed metrics with no crash', () {
      final engine = MetricsEngine();
      engine.addPoint(_pointAtMeters(0, DateTime(2026, 1, 1, 0, 0, 0)));

      expect(engine.metrics.distanceMeters, 0);
      expect(engine.metrics.elapsed, Duration.zero);
      expect(engine.metrics.currentSpeedMps, isNull);
      expect(engine.metrics.avgSpeedMps, isNull);
      expect(engine.metrics.completedSplits, isEmpty);
    });

    test('accumulates distance and elapsed time across points', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(_pointAtMeters(100, start.add(const Duration(seconds: 20))));
      engine.addPoint(_pointAtMeters(200, start.add(const Duration(seconds: 40))));

      expect(engine.metrics.distanceMeters, closeTo(200, 1));
      expect(engine.metrics.elapsed, const Duration(seconds: 40));
    });

    test('a constant 5 m/s run reports ~5 m/s average speed', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      for (var i = 0; i <= 100; i++) {
        engine.addPoint(_pointAtMeters(
          i * 5.0,
          start.add(Duration(seconds: i)),
        ));
      }

      expect(engine.metrics.avgSpeedMps, closeTo(5, 0.05));
    });
  });

  group('accuracy filtering', () {
    test('drops points with accuracy worse than the threshold', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      // A wildly inaccurate fix that would otherwise inflate distance.
      engine.addPoint(_pointAtMeters(
        5000,
        start.add(const Duration(seconds: 10)),
        accuracyMeters: 100,
      ));

      expect(engine.metrics.distanceMeters, 0);
      expect(engine.metrics.elapsed, Duration.zero);
    });

    test('resumes correctly after a dropped point using the last good fix', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(_pointAtMeters(
        5000,
        start.add(const Duration(seconds: 10)),
        accuracyMeters: 100,
      ));
      engine.addPoint(_pointAtMeters(50, start.add(const Duration(seconds: 20))));

      // Distance/time measured from the last *accepted* point (at 0m, t=0),
      // not from the rejected 5000m fix.
      expect(engine.metrics.distanceMeters, closeTo(50, 1));
      expect(engine.metrics.elapsed, const Duration(seconds: 20));
    });
  });

  group('splits', () {
    test('completes a split with interpolated crossing time', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      // Moving at 10 m/s: point at 900m (t=90s), then 1100m (t=110s).
      // The 1000m boundary is crossed 10s into that 20s/200m segment.
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(_pointAtMeters(900, start.add(const Duration(seconds: 90))));
      engine.addPoint(_pointAtMeters(1100, start.add(const Duration(seconds: 110))));

      expect(engine.metrics.completedSplits, hasLength(1));
      final split = engine.metrics.completedSplits.first;
      expect(split.index, 1);
      expect(
        split.duration.inMilliseconds,
        closeTo(const Duration(seconds: 100).inMilliseconds, 50),
      );
      expect(split.avgSpeedMps, closeTo(10, 0.1));
    });

    test('tracks distance/time in the split still in progress', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(_pointAtMeters(300, start.add(const Duration(seconds: 30))));

      expect(engine.metrics.completedSplits, isEmpty);
      expect(engine.metrics.currentSplitDistanceMeters, closeTo(300, 1));
      expect(engine.metrics.currentSplitElapsed, const Duration(seconds: 30));
    });

    test('completes multiple splits crossed within a single segment', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      // 25 m/s for 100s covers 2500m in one jump, crossing two split boundaries.
      // Each 1000m split takes 1000/25 = 40s at this constant speed.
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(_pointAtMeters(2500, start.add(const Duration(seconds: 100))));

      expect(engine.metrics.completedSplits, hasLength(2));
      expect(engine.metrics.completedSplits[0].index, 1);
      expect(engine.metrics.completedSplits[1].index, 2);
      expect(
        engine.metrics.completedSplits[0].duration.inMilliseconds,
        closeTo(const Duration(seconds: 40).inMilliseconds, 50),
      );
      // Both splits are 1000m at the same constant speed, so equal duration
      // (within floating-point rounding of the Duration arithmetic).
      expect(
        engine.metrics.completedSplits[0].duration.inMicroseconds,
        closeTo(engine.metrics.completedSplits[1].duration.inMicroseconds, 5),
      );
      expect(engine.metrics.currentSplitDistanceMeters, closeTo(500, 1));
    });
  });

  group('degenerate inputs', () {
    test('a split covering distance in ~no time reports a finite speed', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      // 2500m in 2ms — physically nonsense, but a GPS timestamp glitch can
      // produce it and it must not yield Infinity.
      engine.addPoint(
        _pointAtMeters(2500, start.add(const Duration(milliseconds: 2))),
      );

      for (final split in engine.metrics.completedSplits) {
        expect(split.avgSpeedMps.isFinite, isTrue);
      }
    });
  });

  group('current speed window', () {
    test('still reports a speed when fixes arrive slower than the window', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      // 4s apart, wider than the 3s smoothing window.
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(_pointAtMeters(20, start.add(const Duration(seconds: 4))));
      engine.addPoint(_pointAtMeters(40, start.add(const Duration(seconds: 8))));

      expect(engine.metrics.currentSpeedMps, isNotNull);
      expect(engine.metrics.currentSpeedMps, closeTo(5, 0.5));
    });
  });

  group('resetSegmentAnchor', () {
    test('prevents a pause gap from being counted as movement', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(_pointAtMeters(100, start.add(const Duration(seconds: 20))));

      engine.resetSegmentAnchor();

      // Resume far later and further away — without the reset this would
      // be treated as one huge fast segment.
      final resumeTime = start.add(const Duration(minutes: 10));
      engine.addPoint(_pointAtMeters(100, resumeTime));
      engine.addPoint(_pointAtMeters(150, resumeTime.add(const Duration(seconds: 10))));

      expect(engine.metrics.distanceMeters, closeTo(150, 1));
      expect(engine.metrics.elapsed, const Duration(seconds: 30));
    });
  });
}
