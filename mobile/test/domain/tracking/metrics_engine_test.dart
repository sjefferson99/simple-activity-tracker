import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';
import 'package:simple_activity_tracker/domain/tracking/metrics_engine.dart';
import 'package:simple_activity_tracker/domain/models/track_point.dart';

/// One degree of longitude at the equator is ~111,195m, matching the
/// haversine implementation under test elsewhere â€” build points along the
/// equator so distances are easy to reason about.
TrackPoint _pointAtMeters(
  double metersFromOrigin,
  DateTime timestamp, {
  double accuracyMeters = 5,
  bool hasAccuracy = true,
  double? elevationMeters,
  double? speedMps,
  bool hasSpeed = false,
}) {
  final degrees = metersFromOrigin / 111195;
  return TrackPoint(
    latitude: 0,
    longitude: degrees,
    timestamp: timestamp,
    accuracyMeters: accuracyMeters,
    hasAccuracy: hasAccuracy,
    elevationMeters: elevationMeters,
    speedMps: speedMps,
    hasSpeed: hasSpeed,
  );
}

void main() {
  group('MetricsEngine basic accumulation', () {
    test('first point produces zeroed metrics with no crash', () {
      final engine = MetricsEngine();
      engine.addPoint(_pointAtMeters(0, DateTime(2026, 1, 1, 0, 0, 0)));

      expect(engine.metrics.distanceMeters, 0);
      expect(engine.metrics.elapsed, Duration.zero);
      expect(engine.metrics.avgSpeedMps, isNull);
      expect(engine.metrics.completedSplits, isEmpty);
    });

    test('accumulates distance and elapsed time across points', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(
        _pointAtMeters(100, start.add(const Duration(seconds: 20))),
      );
      engine.addPoint(
        _pointAtMeters(200, start.add(const Duration(seconds: 40))),
      );

      expect(engine.metrics.distanceMeters, closeTo(200, 1));
      expect(engine.metrics.elapsed, const Duration(seconds: 40));
    });

    test('a constant 5 m/s run reports ~5 m/s average speed', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      for (var i = 0; i <= 100; i++) {
        engine.addPoint(
          _pointAtMeters(i * 5.0, start.add(Duration(seconds: i))),
        );
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
      engine.addPoint(
        _pointAtMeters(
          5000,
          start.add(const Duration(seconds: 10)),
          accuracyMeters: 100,
        ),
      );

      expect(engine.metrics.distanceMeters, 0);
      expect(engine.metrics.elapsed, Duration.zero);
    });

    test('resumes correctly after a dropped point using the last good fix', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(
        _pointAtMeters(
          5000,
          start.add(const Duration(seconds: 10)),
          accuracyMeters: 100,
        ),
      );
      engine.addPoint(
        _pointAtMeters(50, start.add(const Duration(seconds: 20))),
      );

      // Distance/time measured from the last *accepted* point (at 0m, t=0),
      // not from the rejected 5000m fix.
      expect(engine.metrics.distanceMeters, closeTo(50, 1));
      expect(engine.metrics.elapsed, const Duration(seconds: 20));
    });

    test(
      'drops a point with hasAccuracy false even if accuracyMeters looks good',
      () {
        final engine = MetricsEngine();
        final start = DateTime(2026, 1, 1, 0, 0, 0);
        engine.addPoint(_pointAtMeters(0, start));
        // Platform never actually measured accuracy for this fix — a great
        // accuracyMeters value here is a placeholder, not a real reading.
        engine.addPoint(
          _pointAtMeters(
            5000,
            start.add(const Duration(seconds: 10)),
            accuracyMeters: 1,
            hasAccuracy: false,
          ),
        );

        expect(engine.metrics.distanceMeters, 0);
        expect(engine.metrics.elapsed, Duration.zero);
      },
    );

    test('resumes correctly after a hasAccuracy-false point using the last good fix', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(
        _pointAtMeters(
          5000,
          start.add(const Duration(seconds: 10)),
          accuracyMeters: 1,
          hasAccuracy: false,
        ),
      );
      engine.addPoint(
        _pointAtMeters(50, start.add(const Duration(seconds: 20))),
      );

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
      engine.addPoint(
        _pointAtMeters(900, start.add(const Duration(seconds: 90))),
      );
      engine.addPoint(
        _pointAtMeters(1100, start.add(const Duration(seconds: 110))),
      );

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
      engine.addPoint(
        _pointAtMeters(300, start.add(const Duration(seconds: 30))),
      );

      expect(engine.metrics.completedSplits, isEmpty);
      expect(engine.metrics.currentSplitDistanceMeters, closeTo(300, 1));
      expect(engine.metrics.currentSplitElapsed, const Duration(seconds: 30));
    });

    test('completes multiple splits crossed within a single segment', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      // 5 m/s for 500s covers 2500m in one jump (e.g. fixes arrived sparsely
      // during weak signal), crossing two split boundaries at a plausible
      // running pace throughout. Each 1000m split takes 1000/5 = 200s.
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(
        _pointAtMeters(2500, start.add(const Duration(seconds: 500))),
      );

      expect(engine.metrics.completedSplits, hasLength(2));
      expect(engine.metrics.completedSplits[0].index, 1);
      expect(engine.metrics.completedSplits[1].index, 2);
      expect(
        engine.metrics.completedSplits[0].duration.inMilliseconds,
        closeTo(const Duration(seconds: 200).inMilliseconds, 50),
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
    test(
      'a distance covered in ~no time is dropped as an implausible jump',
      () {
        final engine = MetricsEngine();
        final start = DateTime(2026, 1, 1, 0, 0, 0);
        engine.addPoint(_pointAtMeters(0, start));
        // 2500m in 2ms â€” physically nonsense, but a GPS timestamp glitch can
        // produce it. The implausible-speed filter drops it before it can
        // reach split/average-speed math, so no split is produced and nothing
        // divides toward Infinity.
        engine.addPoint(
          _pointAtMeters(2500, start.add(const Duration(milliseconds: 2))),
        );

        expect(engine.metrics.completedSplits, isEmpty);
        for (final split in engine.metrics.completedSplits) {
          expect(split.avgSpeedMps.isFinite, isTrue);
        }
      },
    );
  });

  group('implausible speed filtering', () {
    test('drops a segment implying an impossible running speed', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      // 65km in 19s (~3400 m/s) â€” a GPS glitch, e.g. a stale fix before a
      // real lock â€” reproduces the San Francisco -> San Jose jump seen on
      // the iOS Simulator's "City Run" scenario.
      engine.addPoint(
        _pointAtMeters(65000, start.add(const Duration(seconds: 19))),
      );

      expect(engine.metrics.distanceMeters, 0);
      expect(engine.metrics.elapsed, Duration.zero);
      expect(engine.metrics.avgSpeedMps, isNull);
    });

    test(
      'resumes correctly after an implausible jump using the last good fix',
      () {
        final engine = MetricsEngine();
        final start = DateTime(2026, 1, 1, 0, 0, 0);
        engine.addPoint(_pointAtMeters(0, start));
        engine.addPoint(
          _pointAtMeters(65000, start.add(const Duration(seconds: 19))),
        );
        // Back to a normal jogging pace, measured from the last *accepted*
        // point (0m, t=0), not from the rejected 65000m fix.
        engine.addPoint(
          _pointAtMeters(50, start.add(const Duration(seconds: 29))),
        );

        expect(engine.metrics.distanceMeters, closeTo(50, 1));
        expect(engine.metrics.elapsed, const Duration(seconds: 29));
      },
    );

    test('accepts a segment right at a fast sprint but not beyond it', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      // 10 m/s (36 km/h) is a hard sprint but physically plausible.
      engine.addPoint(
        _pointAtMeters(100, start.add(const Duration(seconds: 10))),
      );

      expect(engine.metrics.distanceMeters, closeTo(100, 1));
    });

    test('re-anchors instead of quarantining the run when the anchor was the bad fix', () {
      // Regression for a real run: a single implausible jump left the anchor
      // pinned on the pre-jump point, which made every subsequent *good*
      // fix near the jump's landing spot look like another impossible jump
      // too â€” quarantining ~77s of otherwise-clean jogging data before the
      // implied speed against the stale anchor finally decayed under the
      // threshold. Two consecutive rejects that agree with each other should
      // re-anchor onto them instead.
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      // Bad jump: 65km in 19s.
      engine.addPoint(
        _pointAtMeters(65000, start.add(const Duration(seconds: 19))),
      );
      // Rejected against the stale anchor at 0m, but agrees with the jump's
      // landing spot (10m in 1s) â€” so the anchor moves here. How the runner
      // got from 0m to 65km is unknowable, so nothing is credited yet.
      engine.addPoint(
        _pointAtMeters(65010, start.add(const Duration(seconds: 20))),
      );
      expect(engine.metrics.distanceMeters, 0);
      expect(engine.metrics.elapsed, Duration.zero);

      // From the re-anchored position, normal fixes accrue as usual.
      engine.addPoint(
        _pointAtMeters(65020, start.add(const Duration(seconds: 21))),
      );
      engine.addPoint(
        _pointAtMeters(65030, start.add(const Duration(seconds: 22))),
      );

      expect(engine.metrics.distanceMeters, closeTo(20, 1));
      expect(engine.metrics.elapsed, const Duration(seconds: 2));
    });

    test('does not credit a drifting bad-fix cluster as real distance', () {
      // Two rejected fixes that agree with each other identify the runner's
      // position, but the drift *between* them is the glitch's own noise â€”
      // banking it would invent distance the runner never covered.
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(
        _pointAtMeters(65000, start.add(const Duration(seconds: 19))),
      );
      engine.addPoint(
        _pointAtMeters(65059, start.add(const Duration(seconds: 25))),
      );

      expect(engine.metrics.distanceMeters, 0);
      expect(engine.metrics.elapsed, Duration.zero);
    });

    test('does not resurrect a stale candidate long after the glitch', () {
      // Speed alone is a weak test: given a long enough gap, any teleport
      // looks slow. A fix 5 minutes after the glitch is a genuine gap in the
      // run, not a recoverable pair â€” crediting it would add the whole gap
      // to elapsed time for one short segment and wreck average speed.
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(
        _pointAtMeters(65000, start.add(const Duration(seconds: 19))),
      );
      engine.addPoint(
        _pointAtMeters(65010, start.add(const Duration(seconds: 300))),
      );

      expect(engine.metrics.elapsed, Duration.zero);
      expect(engine.metrics.avgSpeedMps, isNull);
    });

    test('a repeated identical stale fix does not move the anchor', () {
      // A stuck GPS repeating the same wrong position implies 0 m/s between
      // the duplicates, which passes a speed-only test and would hand the
      // anchor to the bad location.
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(
        _pointAtMeters(65000, start.add(const Duration(seconds: 19))),
      );
      engine.addPoint(
        _pointAtMeters(65000, start.add(const Duration(seconds: 20))),
      );
      // Real position, near where the run actually is â€” still measured from
      // the original good anchor at 0m.
      engine.addPoint(
        _pointAtMeters(10, start.add(const Duration(seconds: 21))),
      );

      expect(engine.metrics.distanceMeters, closeTo(10, 1));
    });

    test('rejects a jump too far for any gap, however long', () {
      // 65km in an hour implies ~18 m/s, which a speed-only test would wave
      // through as a plausible sustained pace.
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(
        _pointAtMeters(65000, start.add(const Duration(hours: 1))),
      );

      expect(engine.metrics.distanceMeters, 0);
    });
  });

  group('noise floor (fallback stationary test, no chip speed available)', () {
    test('does not credit distance or elapsed time to sub-floor wander', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      // Indoor multipath: fixes drift by well under a metre per second while
      // the phone is stationary. Well inside the running-mode plausibility
      // cap (12 m/s), so the teleport filter alone would accept every one
      // of these as real motion.
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(
        _pointAtMeters(0.8, start.add(const Duration(seconds: 1))),
      );
      engine.addPoint(
        _pointAtMeters(0.3, start.add(const Duration(seconds: 2))),
      );
      engine.addPoint(
        _pointAtMeters(1.0, start.add(const Duration(seconds: 3))),
      );

      expect(engine.metrics.distanceMeters, 0);
      expect(engine.metrics.elapsed, Duration.zero);
      expect(engine.metrics.avgSpeedMps, isNull);
    });

    test('a real segment right at the noise floor is still accepted', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(_pointAtMeters(2, start.add(const Duration(seconds: 1))));

      expect(engine.metrics.distanceMeters, closeTo(2, 0.1));
      expect(engine.metrics.elapsed, const Duration(seconds: 1));
    });

    test('resumes normal accumulation once genuine motion follows wander', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      // Stationary indoor wander for a few seconds.
      engine.addPoint(
        _pointAtMeters(0.9, start.add(const Duration(seconds: 1))),
      );
      engine.addPoint(
        _pointAtMeters(0.3, start.add(const Duration(seconds: 2))),
      );
      // The runner actually starts moving.
      engine.addPoint(
        _pointAtMeters(50, start.add(const Duration(seconds: 12))),
      );

      // Measured from the last wander point (0.3m, t=2s), not from the very
      // first fix — the anchor keeps advancing through the noise.
      expect(engine.metrics.distanceMeters, closeTo(49.7, 0.5));
      expect(engine.metrics.elapsed, const Duration(seconds: 10));
    });

    test('walking pace at ~1s fixes clears the floor even though many '
        'individual steps are close to it', () {
      // #49: real on-device capture of a ~1.7 m/s walk averaged ~1.7m
      // between fixes; a naive "just raise the floor" fix would have
      // swallowed most of a genuine walk as noise. Modelled here as a
      // steady 1.7 m/s pace.
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      for (var i = 0; i <= 20; i++) {
        engine.addPoint(
          _pointAtMeters(i * 1.7, start.add(Duration(seconds: i))),
        );
      }

      expect(engine.metrics.distanceMeters, greaterThan(30));
    });
  });

  group('step 3a: chip-speed stationary gate (primary path)', () {
    test('a noisy stationary blip ringing for two fixes credits only a small '
        'residual, not the ~6m the old position-floor gate let through', () {
      // Real on-device indoor capture: phone motionless on a table, chip
      // speed rang 4.32, then 4.34 m/s for two consecutive fixes (not just
      // one) before decaying back down through 0.71 and 0.62 m/s. The old
      // position-floor gate accepted this because one segment happened to
      // exceed 1.2m, credited ~6m. A 2-fix confirmation still let ~5m of
      // this ringing through in testing. 3 consecutive fixes reduce it to
      // ~1.2m — the decaying tail (0.71, 0.62) is still above the 0.6
      // enter threshold, so it can complete the confirmation streak even
      // though it's the same noise event settling, not fresh motion.
      // Fully eliminating that would need the gate to also check for real
      // position displacement, not just speed; not worth the complexity
      // for this residual (docs/GPS-METRICS-PLAN.md's "reasonably good"
      // bar — see project decision 2026-09-07).
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      var t = 0;
      void point(double meters, double speed) {
        engine.addPoint(
          _pointAtMeters(
            meters,
            start.add(Duration(seconds: t)),
            speedMps: speed,
            hasSpeed: true,
          ),
        );
        t++;
      }

      point(0, 0.0);
      point(0.54, 4.32);
      point(2.76, 4.34);
      point(4.91, 0.71);
      point(5.74, 0.62);
      point(6.11, 0.24);

      expect(engine.metrics.distanceMeters, lessThan(2));
    });

    test('three consecutive fixes at/above the enter threshold credit motion, '
        'lagging by the segment that completes the confirmation', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      var t = 0;
      void point(double meters, double speed) {
        engine.addPoint(
          _pointAtMeters(
            meters,
            start.add(Duration(seconds: t)),
            speedMps: speed,
            hasSpeed: true,
          ),
        );
        t++;
      }

      point(0, 0.0);
      // Real walking pace from an on-device capture: ~1.0-1.35 m/s.
      point(1.2, 1.16); // streak 1 - not yet moving, segment not credited
      point(2.4, 1.15); // streak 2 - not yet moving, segment not credited
      point(3.6, 1.20); // streak 3 confirms moving as of *this* fix, but the
      // segment ending on it is judged by the pre-update verdict (still not
      // moving) - so it's not credited either; only the *next* segment,
      // after the verdict has actually flipped, is the first one credited.
      point(4.8, 1.18); // now moving - this segment is credited

      // Only the last segment (3.6m -> 4.8m) is credited — three fixes worth
      // of walk-off are the deliberate cost of not crediting on a
      // single/double noisy fix (the very bug this gate exists to fix).
      expect(engine.metrics.distanceMeters, closeTo(1.2, 0.1));
    });

    test(
      'a real walk-off after a stationary stretch ramps through the enter '
      'threshold, matching a genuine on-device resume-from-pause capture',
      () {
        // Real capture: resumed from a pause stationary (chip speed
        // 0.02-0.08 m/s for 4 fixes), then a genuine walk-off ramped
        // 0.51 -> 0.96 -> 1.18 -> 1.25 m/s over the next 4 fixes. The gate
        // must start crediting once 3 consecutive fixes clear 0.6 m/s.
        final engine = MetricsEngine();
        final start = DateTime(2026, 1, 1, 0, 0, 0);
        var t = 0;
        void point(double meters, double speed) {
          engine.addPoint(
            _pointAtMeters(
              meters,
              start.add(Duration(seconds: t)),
              speedMps: speed,
              hasSpeed: true,
            ),
          );
          t++;
        }

        point(0, 0.06);
        point(0.07, 0.08);
        point(0.13, 0.02);
        point(0.19, 0.08);
        // Ramp-up begins: 0.51 is below the enter threshold, so it doesn't
        // start the confirmation streak.
        point(1.28, 0.51);
        point(2.78, 0.96); // streak 1
        point(4.63, 1.18); // streak 2
        point(6.24, 1.25); // streak 3 confirms moving as of this fix
        point(7.9, 1.24); // moving - this segment is the first credited one

        expect(engine.metrics.distanceMeters, greaterThan(0));
      },
    );

    test('hysteresis keeps crediting through a dip below the enter threshold '
        'once already moving', () {
      // Once moving, only a drop below the lower exit threshold (0.4)
      // should stop crediting — pace jitter that dips just under the enter
      // threshold (0.6) but stays above exit must not flicker distance
      // on/off mid-stride.
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      var t = 0;
      void point(double meters, double speed) {
        engine.addPoint(
          _pointAtMeters(
            meters,
            start.add(Duration(seconds: t)),
            speedMps: speed,
            hasSpeed: true,
          ),
        );
        t++;
      }

      point(0, 1.2);
      point(1.2, 1.2);
      point(2.4, 1.2);
      point(3.6, 1.2); // confirms moving as of this fix
      final distanceOnceMoving = engine.metrics.distanceMeters;
      expect(
        distanceOnceMoving,
        0,
        reason:
            'nothing credited yet — the '
            'verdict only flips on this fix, judging none of the segments '
            'seen so far',
      );
      // Dips to 0.5 - below the enter threshold but above the exit one.
      point(4.1, 0.5);

      expect(
        engine.metrics.distanceMeters,
        greaterThan(distanceOnceMoving),
        reason:
            'a dip that stays above the exit threshold must still be '
            'credited, not treated as a stop',
      );
    });

    test(
      'a genuine stop (speed drops below the exit threshold) stops crediting',
      () {
        final engine = MetricsEngine();
        final start = DateTime(2026, 1, 1, 0, 0, 0);
        var t = 0;
        void point(double meters, double speed) {
          engine.addPoint(
            _pointAtMeters(
              meters,
              start.add(Duration(seconds: t)),
              speedMps: speed,
              hasSpeed: true,
            ),
          );
          t++;
        }

        point(0, 1.2);
        point(1.2, 1.2);
        point(2.4, 1.2); // confirms moving
        // Genuinely stops — below the exit threshold, no confirmation needed.
        point(2.5, 0.1);

        final distanceAtStop = engine.metrics.distanceMeters;
        // Further stationary wander must not add any more distance.
        point(2.7, 0.15);

        expect(engine.metrics.distanceMeters, distanceAtStop);
      },
    );

    test('falls back to the position noise floor when the platform reports no '
        'usable speed for a fix', () {
      // A mix of speed-bearing and speed-less fixes within the same run —
      // the gate must fall back to the position floor per-fix, not for the
      // whole run.
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      // No speed reported: falls back to the 1.2m floor. This segment is
      // under it, so it's rejected regardless of geometry alone.
      engine.addPoint(
        _pointAtMeters(0.5, start.add(const Duration(seconds: 1))),
      );

      expect(engine.metrics.distanceMeters, 0);
    });

    test('resetSegmentAnchor clears the moving/stationary verdict', () {
      // Without a reset, a pause/resume could inherit "already moving" from
      // before the pause and credit the first post-resume segment even if
      // its own chip speed is still ambiguous.
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      var t = 0;
      void point(double meters, double speed) {
        engine.addPoint(
          _pointAtMeters(
            meters,
            start.add(Duration(seconds: t)),
            speedMps: speed,
            hasSpeed: true,
          ),
        );
        t++;
      }

      point(0, 1.2);
      point(1.2, 1.2);
      point(2.4, 1.2);
      point(3.6, 1.2); // confirms moving as of this fix
      point(4.8, 1.2); // now moving - this segment is credited
      expect(engine.metrics.distanceMeters, greaterThan(0));

      engine.resetSegmentAnchor();

      final resumeTime = start.add(const Duration(minutes: 5));
      // First post-resume fix establishes the new anchor; the second reports
      // a speed below the enter threshold, so — starting fresh, not still
      // "moving" from before the pause — it must not be credited.
      engine.addPoint(
        _pointAtMeters(100, resumeTime, speedMps: 0.3, hasSpeed: true),
      );
      final distanceAfterAnchor = engine.metrics.distanceMeters;
      engine.addPoint(
        _pointAtMeters(
          100.3,
          resumeTime.add(const Duration(seconds: 1)),
          speedMps: 0.3,
          hasSpeed: true,
        ),
      );

      expect(engine.metrics.distanceMeters, distanceAfterAnchor);
    });
  });

  group('#49: a real out-and-back route is never mistaken for GPS drift', () {
    // A "straightness" filter (net displacement over a window vs. total path
    // walked in it) was tried and reverted here: a genuine on-device capture
    // of an ordinary out-and-back walk has the *identical* signature to
    // indoor multipath drift-then-snap-back — low net displacement relative
    // to path length, because the walker turns around — and that filter
    // rejected the whole walk, reporting 0 distance/elapsed throughout. Any
    // real loop, out-and-back, or lap course looks like this; position data
    // alone can't tell it apart from a bad fix snapping back. These tests
    // guard against reintroducing that class of filter without solving this.
    test('walking out and back to the start credits real distance', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      var t = 0;
      void point(double meters) {
        engine.addPoint(
          _pointAtMeters(meters, start.add(Duration(seconds: t))),
        );
        t++;
      }

      // Walk out ~50m at a real walking pace (5m/s steps, clear of the 3m
      // noise floor)...
      for (var m = 0; m <= 50; m += 5) {
        point(m.toDouble());
      }
      // ...then walk back to (near) the start.
      for (var m = 45; m >= 0; m -= 5) {
        point(m.toDouble());
      }

      // Every leg was a genuine plausible-speed, above-noise-floor segment,
      // so all of it should be credited — net displacement ending up near
      // zero must not suppress any of it.
      expect(engine.metrics.distanceMeters, greaterThan(90));
    });

    test(
      'a short there-and-back loop (a lap course) still accrues distance',
      () {
        final engine = MetricsEngine();
        final start = DateTime(2026, 1, 1, 0, 0, 0);
        var t = 0;
        void point(double meters) {
          engine.addPoint(
            _pointAtMeters(meters, start.add(Duration(seconds: t))),
          );
          t++;
        }

        // Several short back-and-forth laps, each leg a real walking-speed
        // segment (well clear of the 3m noise floor) — net displacement
        // across the whole thing is ~0.
        for (var lap = 0; lap < 4; lap++) {
          point(10);
          point(0);
        }

        expect(engine.metrics.distanceMeters, greaterThan(65));
      },
    );
  });

  group('ActivityMode.cycling raises both plausibility thresholds', () {
    test('accepts a segment fast enough to be rejected in running mode', () {
      // 20 m/s (72 km/h) is a plausible fast descent on a bike, but well
      // past running mode's 12 m/s cap.
      final runningEngine = MetricsEngine();
      final cyclingEngine = MetricsEngine(mode: ActivityMode.cycling);
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      for (final engine in [runningEngine, cyclingEngine]) {
        engine.addPoint(_pointAtMeters(0, start));
        engine.addPoint(
          _pointAtMeters(200, start.add(const Duration(seconds: 10))),
        );
      }

      expect(
        runningEngine.metrics.distanceMeters,
        0,
        reason: 'running mode should reject a 20 m/s segment',
      );
      expect(
        cyclingEngine.metrics.distanceMeters,
        closeTo(200, 1),
        reason: 'cycling mode should accept a 20 m/s segment',
      );
    });

    test('tolerates a larger sparse-fix gap than running mode allows', () {
      // 30km in 25 minutes implies 20 m/s â€” plausible for cycling mode's
      // higher speed cap, and comfortably under its 40km segment cap, but
      // beyond running mode's 20km segment cap regardless of speed.
      final runningEngine = MetricsEngine();
      final cyclingEngine = MetricsEngine(mode: ActivityMode.cycling);
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      for (final engine in [runningEngine, cyclingEngine]) {
        engine.addPoint(_pointAtMeters(0, start));
        engine.addPoint(
          _pointAtMeters(30000, start.add(const Duration(minutes: 25))),
        );
      }

      expect(
        runningEngine.metrics.distanceMeters,
        0,
        reason: 'running mode\'s 20km segment cap should reject this gap',
      );
      expect(
        cyclingEngine.metrics.distanceMeters,
        closeTo(30000, 1),
        reason: 'cycling mode\'s 40km segment cap should accept this gap',
      );
    });

    test('still rejects a jump too far for cycling, however long the gap', () {
      // Mirrors the running-mode "rejects a jump too far for any gap" case
      // above, scaled past cycling mode's 40km cap â€” the cap has to have
      // a ceiling somewhere, not just a higher one than running.
      final engine = MetricsEngine(mode: ActivityMode.cycling);
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(
        _pointAtMeters(100000, start.add(const Duration(hours: 2))),
      );

      expect(engine.metrics.distanceMeters, 0);
    });
  });

  group('resetSegmentAnchor', () {
    test('prevents a pause gap from being counted as movement', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(
        _pointAtMeters(100, start.add(const Duration(seconds: 20))),
      );

      engine.resetSegmentAnchor();

      // Resume far later and further away â€” without the reset this would
      // be treated as one huge fast segment.
      final resumeTime = start.add(const Duration(minutes: 10));
      engine.addPoint(_pointAtMeters(100, resumeTime));
      engine.addPoint(
        _pointAtMeters(150, resumeTime.add(const Duration(seconds: 10))),
      );

      expect(engine.metrics.distanceMeters, closeTo(150, 1));
      expect(engine.metrics.elapsed, const Duration(seconds: 30));
    });
  });

  group('maxSpeedMps', () {
    test('is null before any segment is accepted', () {
      final engine = MetricsEngine();
      engine.addPoint(_pointAtMeters(0, DateTime(2026, 1, 1, 0, 0, 0)));

      expect(engine.metrics.maxSpeedMps, isNull);
    });

    test('tracks the highest accepted segment speed, not the latest', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      // 10 m/s, then 5 m/s, then 8 m/s - max should stay at 10, not follow
      // the most recent segment.
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(
        _pointAtMeters(100, start.add(const Duration(seconds: 10))),
      );
      engine.addPoint(
        _pointAtMeters(150, start.add(const Duration(seconds: 20))),
      );
      engine.addPoint(
        _pointAtMeters(230, start.add(const Duration(seconds: 30))),
      );

      expect(engine.metrics.maxSpeedMps, closeTo(10, 0.01));
    });

    test('a rejected implausible jump does not count toward max speed', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(
        _pointAtMeters(100, start.add(const Duration(seconds: 10))),
      );
      // 65km in 19s - rejected as implausible, must not become the max.
      engine.addPoint(
        _pointAtMeters(65100, start.add(const Duration(seconds: 29))),
      );

      expect(engine.metrics.maxSpeedMps, closeTo(10, 0.01));
    });

    test('is unaffected by resetSegmentAnchor (pause/resume)', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(
        _pointAtMeters(100, start.add(const Duration(seconds: 10))),
      );

      engine.resetSegmentAnchor();

      final resumeTime = start.add(const Duration(minutes: 5));
      engine.addPoint(_pointAtMeters(100, resumeTime));
      engine.addPoint(
        _pointAtMeters(120, resumeTime.add(const Duration(seconds: 10))),
      );

      // The post-pause segment (2 m/s) is slower than the pre-pause one
      // (10 m/s) - max speed should still reflect the earlier, faster one.
      expect(engine.metrics.maxSpeedMps, closeTo(10, 0.01));
    });
  });

  group('elevationGainMeters', () {
    test('is zero when no points carry elevation', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start));
      engine.addPoint(
        _pointAtMeters(100, start.add(const Duration(seconds: 20))),
      );

      expect(engine.metrics.elevationGainMeters, 0);
    });

    test(
      'accumulates only positive altitude changes between accepted points',
      () {
        final engine = MetricsEngine();
        final start = DateTime(2026, 1, 1, 0, 0, 0);
        engine.addPoint(_pointAtMeters(0, start, elevationMeters: 100));
        // +10m climb.
        engine.addPoint(
          _pointAtMeters(
            100,
            start.add(const Duration(seconds: 20)),
            elevationMeters: 110,
          ),
        );
        // -5m descent - ignored, not subtracted.
        engine.addPoint(
          _pointAtMeters(
            200,
            start.add(const Duration(seconds: 40)),
            elevationMeters: 105,
          ),
        );
        // +8m climb.
        engine.addPoint(
          _pointAtMeters(
            300,
            start.add(const Duration(seconds: 60)),
            elevationMeters: 113,
          ),
        );

        expect(engine.metrics.elevationGainMeters, closeTo(18, 0.01));
      },
    );

    test('a leg with a null elevation reading contributes no gain', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start, elevationMeters: 100));
      // No elevation reading on this fix.
      engine.addPoint(
        _pointAtMeters(100, start.add(const Duration(seconds: 20))),
      );
      // Elevation resumes, but the gap across the null-elevation leg isn't
      // bridged - only point-to-point deltas where both ends have a reading
      // count.
      engine.addPoint(
        _pointAtMeters(
          200,
          start.add(const Duration(seconds: 40)),
          elevationMeters: 130,
        ),
      );

      expect(engine.metrics.elevationGainMeters, 0);
    });

    test(
      'a rejected implausible jump does not count toward elevation gain',
      () {
        final engine = MetricsEngine();
        final start = DateTime(2026, 1, 1, 0, 0, 0);
        engine.addPoint(_pointAtMeters(0, start, elevationMeters: 100));
        // 65km jump with a huge elevation spike - rejected as implausible.
        engine.addPoint(
          _pointAtMeters(
            65000,
            start.add(const Duration(seconds: 19)),
            elevationMeters: 5000,
          ),
        );

        expect(engine.metrics.elevationGainMeters, 0);
      },
    );

    test('is unaffected by resetSegmentAnchor (pause/resume)', () {
      final engine = MetricsEngine();
      final start = DateTime(2026, 1, 1, 0, 0, 0);
      engine.addPoint(_pointAtMeters(0, start, elevationMeters: 100));
      engine.addPoint(
        _pointAtMeters(
          100,
          start.add(const Duration(seconds: 20)),
          elevationMeters: 110,
        ),
      );

      engine.resetSegmentAnchor();

      final resumeTime = start.add(const Duration(minutes: 5));
      engine.addPoint(_pointAtMeters(100, resumeTime, elevationMeters: 110));
      engine.addPoint(
        _pointAtMeters(
          150,
          resumeTime.add(const Duration(seconds: 10)),
          elevationMeters: 115,
        ),
      );

      expect(engine.metrics.elevationGainMeters, closeTo(15, 0.01));
    });
  });
}
