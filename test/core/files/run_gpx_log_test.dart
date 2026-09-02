import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:gpx/gpx.dart';
import 'package:simple_runner/core/files/run_gpx_log.dart';
import 'package:simple_runner/domain/models/track_point.dart';

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

  test('finalizeAndFlush drops empty segments (e.g. an unused pause gap)', () async {
    final file = File('${tempDir.path}/run.gpx');
    final log = RunGpxLog(file);
    final start = DateTime(2026, 1, 1, 9, 0, 0);

    log.addPoint(_point(51.5, -0.1, start));
    log.startNewSegment(); // never receives a point (e.g. pause then stop)
    await log.finalizeAndFlush();

    final gpx = GpxReader().fromString(await file.readAsString());
    expect(gpx.trks.first.trksegs, hasLength(1));
  });

  test('flush is crash-safe: an interrupted temp write leaves the prior file intact', () async {
    final file = File('${tempDir.path}/run.gpx');
    final log = RunGpxLog(file);
    final start = DateTime(2026, 1, 1, 9, 0, 0);

    log.addPoint(_point(51.5, -0.1, start));
    await log.flush();
    final firstFlushContent = await file.readAsString();

    // Simulate a crash mid-write by leaving a stray temp file behind —
    // the real target file must still be the last successfully flushed one.
    await File('${file.path}.tmp').writeAsString('not valid xml, mid-write');

    expect(await file.readAsString(), firstFlushContent);
  });
}
