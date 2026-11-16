// Replays real captured GPX files through the live speed readout's actual
// estimators (issue #153): the 6 s DisplaySpeedWindow that drove the tile
// before, and CalibratedDisplaySpeed that drives it now. Compares each with
// a non-causal reference, a centred 30 s path speed, over fixes where the
// reference says you're moving (>= 1 m/s).
//
// Columns:
// - dPace: mean change in displayed pace (s/km) between consecutive
//   readings, with its 95th percentile. Lower = steadier.
// - bias: mean displayed speed ÷ mean reference speed. 1.000 = agrees with
//   position-derived distance, which is what Distance/Avg/splits use.
// - stopped: mean displayed km/h where the reference is under 0.2 m/s.
//
// Usage (from mobile/):
//   dart run tool/replay_display_speed.dart [--mode running|cycling|walking] <path.gpx>...
//
// ignore_for_file: avoid_print — a CLI diagnostic tool's whole job is to
// print its findings; a logging framework would be pure ceremony here.
import 'dart:io';

import 'package:simple_activity_tracker/domain/geo_math.dart';
import 'package:simple_activity_tracker/domain/models/track_point.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';
import 'package:simple_activity_tracker/domain/tracking/calibrated_display_speed.dart';
import 'package:simple_activity_tracker/domain/tracking/display_speed_window.dart';

void main(List<String> args) {
  var mode = ActivityMode.running;
  final paths = <String>[];
  for (var i = 0; i < args.length; i++) {
    if (args[i] == '--mode' && i + 1 < args.length) {
      mode = ActivityMode.values.byName(args[++i]);
    } else {
      paths.add(args[i]);
    }
  }
  if (paths.isEmpty) {
    stderr.writeln(
      'Usage: dart run tool/replay_display_speed.dart '
      '[--mode running|cycling|walking] <path.gpx>...',
    );
    exit(1);
  }

  print('mode: ${mode.name}');
  print('${'file'.padRight(28)} moving |  6 s window dPace  p95  bias  stopped'
      ' | calibrated dPace  p95  bias  stopped');
  for (final path in paths) {
    final points = _parseTrackPoints(File(path).readAsStringSync());
    final window = DisplaySpeedWindow();
    final calibrated = CalibratedDisplaySpeed.forMode(mode);
    final before = [for (final p in points) window.addPoint(p)];
    final after = [for (final p in points) calibrated.addPoint(p)];
    final reference = _centredPathSpeeds(points, halfWindowSeconds: 15);

    final b = _Stats.of(before, reference);
    final a = _Stats.of(after, reference);
    final name = path.split(RegExp(r'[\\/]')).last;
    print('${name.padRight(28)} ${b.movingFixes.toString().padLeft(6)} | '
        '${b.format()} | ${a.format()}');
  }
}

class _Stats {
  _Stats(this.movingFixes, this.meanDPace, this.p95DPace, this.bias,
      this.stoppedKmh);

  final int movingFixes;
  final double meanDPace, p95DPace, bias, stoppedKmh;

  static _Stats of(List<double?> shown, List<double?> reference) {
    final dPace = <double>[];
    var shownSum = 0.0, referenceSum = 0.0, stoppedSum = 0.0;
    var moving = 0, stopped = 0;
    for (var i = 0; i < shown.length; i++) {
      final r = reference[i], s = shown[i];
      if (r == null || s == null) continue;
      if (r < 0.2) {
        stoppedSum += s;
        stopped++;
      }
      if (r < 1.0) continue;
      moving++;
      shownSum += s;
      referenceSum += r;
      final previous = i > 0 ? shown[i - 1] : null;
      if (previous != null && previous >= 0.5 && s >= 0.5) {
        dPace.add((1000 / previous - 1000 / s).abs());
      }
    }
    dPace.sort();
    return _Stats(
      moving,
      dPace.isEmpty ? double.nan : dPace.reduce((x, y) => x + y) / dPace.length,
      dPace.isEmpty ? double.nan : dPace[(dPace.length * 0.95).floor()],
      referenceSum == 0 ? double.nan : shownSum / referenceSum,
      stopped == 0 ? double.nan : stoppedSum / stopped * 3.6,
    );
  }

  String format() => '${meanDPace.toStringAsFixed(1).padLeft(16)} '
      '${p95DPace.toStringAsFixed(0).padLeft(4)} '
      '${bias.toStringAsFixed(3)} '
      '${stoppedKmh.toStringAsFixed(2).padLeft(8)}';
}

/// Path length ÷ time over ±[halfWindowSeconds] around each fix.
List<double?> _centredPathSpeeds(
  List<TrackPoint> points, {
  required int halfWindowSeconds,
}) {
  final cumulative = <double>[0];
  for (var i = 1; i < points.length; i++) {
    cumulative.add(
      cumulative.last + haversineDistanceMeters(points[i - 1], points[i]),
    );
  }
  double seconds(int from, int to) =>
      points[to].timestamp.difference(points[from].timestamp).inMilliseconds /
      1000;

  final result = <double?>[];
  var lo = 0, hi = 0;
  for (var i = 0; i < points.length; i++) {
    while (seconds(lo, i) > halfWindowSeconds) {
      lo++;
    }
    if (hi < i) hi = i;
    while (hi + 1 < points.length && seconds(i, hi + 1) <= halfWindowSeconds) {
      hi++;
    }
    final dt = seconds(lo, hi);
    result.add(dt <= 0 ? null : (cumulative[hi] - cumulative[lo]) / dt);
  }
  return result;
}

String? _extractTag(String xml, String tag) =>
    RegExp('<$tag>(.*?)</$tag>').firstMatch(xml)?.group(1);

List<TrackPoint> _parseTrackPoints(String xml) {
  final trkptPattern = RegExp(
    r'<trkpt lat="([^"]+)" lon="([^"]+)">(.*?)</trkpt>',
    dotAll: true,
  );
  return [
    for (final m in trkptPattern.allMatches(xml))
      TrackPoint(
        latitude: double.parse(m.group(1)!),
        longitude: double.parse(m.group(2)!),
        timestamp: DateTime.parse(_extractTag(m.group(3)!, 'time')!),
        accuracyMeters:
            double.tryParse(_extractTag(m.group(3)!, 'sat:accuracy') ?? '') ??
                9999,
        hasAccuracy: _extractTag(m.group(3)!, 'sat:has_accuracy') == 'true',
        speedMps: double.tryParse(_extractTag(m.group(3)!, 'sat:speed') ?? ''),
        hasSpeed: _extractTag(m.group(3)!, 'sat:has_speed') == 'true',
      ),
  ];
}
