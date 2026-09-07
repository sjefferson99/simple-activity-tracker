import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:gpx/gpx.dart';
import 'package:simple_activity_tracker/core/files/run_gpx_log.dart';
import 'package:simple_activity_tracker/domain/models/track_point.dart';

TrackPoint _point(double lat, double lon, DateTime time) => TrackPoint(
  latitude: lat,
  longitude: lon,
  timestamp: time,
  accuracyMeters: 5,
);

void main() {
  late Directory tempDir;

  setUp(() async {
    tempDir = await Directory.systemTemp.createTemp('run_gpx_log_test');
  });

  tearDown(() async {
    if (await tempDir.exists()) {
      await tempDir.delete(recursive: true);
    }
  });

  test('flush writes a valid GPX file with the accepted points', () async {
    final file = File('${tempDir.path}/run.gpx');
    final log = RunGpxLog(file);
    final start = DateTime(2026, 1, 1, 9, 0, 0);

    log.addPoint(_point(51.5, -0.1, start));
    log.addPoint(_point(51.51, -0.11, start.add(const Duration(seconds: 10))));
    await log.flush();

    expect(await file.exists(), isTrue);
    final gpx = GpxReader().fromString(await file.readAsString());
    expect(gpx.trks, hasLength(1));
    expect(gpx.trks.first.trksegs, hasLength(1));
    expect(gpx.trks.first.trksegs.first.trkpts, hasLength(2));
    expect(gpx.trks.first.trksegs.first.trkpts.first.lat, 51.5);
  });

  test('startNewSegment begins a new trkseg for the next points', () async {
    final file = File('${tempDir.path}/run.gpx');
    final log = RunGpxLog(file);
    final start = DateTime(2026, 1, 1, 9, 0, 0);

    log.addPoint(_point(51.5, -0.1, start));
    log.startNewSegment();
    log.addPoint(_point(51.6, -0.2, start.add(const Duration(minutes: 5))));
    await log.finalizeAndFlush();

    final gpx = GpxReader().fromString(await file.readAsString());
    expect(gpx.trks.first.trksegs, hasLength(2));
    expect(gpx.trks.first.trksegs[0].trkpts, hasLength(1));
    expect(gpx.trks.first.trksegs[1].trkpts, hasLength(1));
  });

  test(
    'finalizeAndFlush drops empty segments (e.g. an unused pause gap)',
    () async {
      final file = File('${tempDir.path}/run.gpx');
      final log = RunGpxLog(file);
      final start = DateTime(2026, 1, 1, 9, 0, 0);

      log.addPoint(_point(51.5, -0.1, start));
      log.startNewSegment(); // never receives a point (e.g. pause then stop)
      await log.finalizeAndFlush();

      final gpx = GpxReader().fromString(await file.readAsString());
      expect(gpx.trks.first.trksegs, hasLength(1));
    },
  );

  test(
    'concurrent flushes do not clobber each other and keep every point',
    () async {
      final file = File('${tempDir.path}/run.gpx');
      final log = RunGpxLog(file);
      final start = DateTime(2026, 1, 1, 9, 0, 0);

      log.addPoint(_point(51.5, -0.1, start));
      // Kick off a periodic-style flush and immediately finalize, the exact
      // overlap that previously raced on the shared .tmp path.
      final periodic = log.flush();
      log.addPoint(
        _point(51.51, -0.11, start.add(const Duration(seconds: 10))),
      );
      final finalFlush = log.finalizeAndFlush();

      await Future.wait([periodic, finalFlush]);

      final gpx = GpxReader().fromString(await file.readAsString());
      final points = gpx.trks
          .expand((t) => t.trksegs)
          .expand((s) => s.trkpts)
          .toList();
      expect(points, hasLength(2));
    },
  );

  test(
    'addPoint writes accuracy/speed diagnostics as GPX extensions',
    () async {
      final file = File('${tempDir.path}/run.gpx');
      final log = RunGpxLog(file);
      final start = DateTime(2026, 1, 1, 9, 0, 0);

      log.addPoint(
        TrackPoint(
          latitude: 51.5,
          longitude: -0.1,
          timestamp: start,
          accuracyMeters: 12.5,
          hasAccuracy: true,
          speedMps: 1.7,
          hasSpeed: true,
        ),
      );
      log.addPoint(
        TrackPoint(
          latitude: 51.51,
          longitude: -0.11,
          timestamp: start.add(const Duration(seconds: 1)),
          accuracyMeters: 40,
          hasAccuracy: false,
          hasSpeed: false,
        ),
      );
      await log.flush();

      final gpx = GpxReader().fromString(await file.readAsString());
      final points = gpx.trks.first.trksegs.first.trkpts;
      expect(points, hasLength(2));

      expect(points[0].extensions['sat:accuracy'], '12.5');
      expect(points[0].extensions['sat:has_accuracy'], 'true');
      expect(points[0].extensions['sat:speed'], '1.7');
      expect(points[0].extensions['sat:has_speed'], 'true');

      expect(points[1].extensions['sat:accuracy'], '40.0');
      expect(points[1].extensions['sat:has_accuracy'], 'false');
      expect(points[1].extensions.containsKey('sat:speed'), isFalse);
      expect(points[1].extensions['sat:has_speed'], 'false');
    },
  );

  test('flush is crash-safe: an interrupted temp write leaves the prior file intact', () async {
    final file = File('${tempDir.path}/run.gpx');
    final log = RunGpxLog(file);
    final start = DateTime(2026, 1, 1, 9, 0, 0);

    log.addPoint(_point(51.5, -0.1, start));
    await log.flush();
    final firstFlushContent = await file.readAsString();

    // Simulate a crash mid-write by leaving a stray temp file behind â€”
    // the real target file must still be the last successfully flushed one.
    await File('${file.path}.tmp').writeAsString('not valid xml, mid-write');

    expect(await file.readAsString(), firstFlushContent);
  });
}
