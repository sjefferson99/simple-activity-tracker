// Replays a real captured GPX file through the actual MetricsEngine +
// detectSplitAudioCue logic (issue #125), printing every cue that would
// fire and its verdict/beep-count — used to diagnose a real on-device bug
// (two GPX captures from a walk where the too-fast/too-slow beep pattern
// only ever played once, not 2/3 times) against the exact production code
// path, not a synthetic reproduction. Reads the plan/target straight out of
// the GPX's own sat:split_plan extension, same as the server's parser does.
//
// Usage (from mobile/): dart run tool/replay_split_audio.dart <path.gpx>
//
// ignore_for_file: avoid_print — a CLI diagnostic tool's whole job is to
// print its findings; a logging framework would be pure ceremony here.
import 'dart:io';

import 'package:simple_activity_tracker/domain/models/live_metrics.dart';
import 'package:simple_activity_tracker/domain/models/track_point.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';
import 'package:simple_activity_tracker/domain/tracking/metrics_engine.dart';
import 'package:simple_activity_tracker/domain/tracking/split_audio_cue.dart';
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';
import 'package:simple_activity_tracker/domain/tracking/split_target.dart';

void main(List<String> args) {
  if (args.isEmpty) {
    stderr.writeln('Usage: dart run tool/replay_split_audio.dart <path.gpx>');
    exit(1);
  }
  final xml = File(args[0]).readAsStringSync();

  final splitType = _extractTag(xml, 'sat:split_type');
  final splitValue = _extractTag(xml, 'sat:split_value');
  final splitPlanRaw = _extractTag(xml, 'sat:split_plan');
  print('split_type=$splitType split_value=$splitValue split_plan=$splitPlanRaw');

  final kind = switch (splitType) {
    'distance_km' => SplitKind.distanceKm,
    'distance_mi' => SplitKind.distanceMi,
    'time_min' => SplitKind.timeMin,
    _ => SplitKind.distanceKm,
  };
  final base = SplitPreference(kind: kind, value: int.parse(splitValue!));
  final customSplits = <PlannedSplit>[];
  if (splitPlanRaw != null && splitPlanRaw.isNotEmpty) {
    for (final entry in splitPlanRaw.split(';')) {
      final parts = entry.split('@');
      final size = double.parse(parts[0]);
      final target = parts.length > 1 ? double.parse(parts[1]) : null;
      customSplits.add(PlannedSplit(size: size, targetSpeedMps: target));
    }
  }
  final plan = SplitPlan(base: base, customSplits: customSplits);
  print(
    'Parsed plan: ${plan.customSplits.length} custom splits, '
    'base ${plan.base.kind.name}=${plan.base.value}',
  );
  for (var i = 0; i < plan.customSplits.length; i++) {
    print('  split ${i + 1}: size=${plan.sizeOf(i)} target=${plan.targetOf(i)}');
  }

  final points = _parseTrackPoints(xml);
  print('Parsed ${points.length} track points\n');

  final engine = MetricsEngine(mode: ActivityMode.running, splitPlan: plan);
  LiveMetrics? previous;
  var cueCount = 0;

  for (final point in points) {
    engine.addPoint(point);
    final current = engine.metrics;
    final cue = detectSplitAudioCue(previous: previous, current: current);
    if (cue != null) {
      cueCount++;
      final beepDesc = switch (cue.kind) {
        SplitAudioCueKind.splitChanged => '1 beep (splitChanged)',
        SplitAudioCueKind.verdict => switch (cue.verdict!) {
            SplitVerdict.tooFast => '2 beeps (tooFast)',
            SplitVerdict.tooSlow => '3 beeps (tooSlow)',
            SplitVerdict.onTarget => '1 long beep (onTarget)',
          },
      };
      print(
        '[cue #$cueCount] t=${point.timestamp.toIso8601String()} '
        'splitIndex=${current.currentSplit.index} '
        'currentSplitElapsed=${current.currentSplitElapsed} '
        'avgSpeedMps=${_avgSpeedMps(current)?.toStringAsFixed(3)} '
        'target=${current.currentSplit.targetSpeedMps} '
        '-> $beepDesc',
      );
    }
    previous = current;
  }

  print('\nTotal cues: $cueCount');
}

double? _avgSpeedMps(LiveMetrics m) {
  final s = m.currentSplitElapsed.inMilliseconds / 1000;
  return s <= 0 ? null : m.currentSplitDistanceMeters / s;
}

String? _extractTag(String xml, String tag) {
  final match = RegExp('<$tag>(.*?)</$tag>').firstMatch(xml);
  return match?.group(1);
}

List<TrackPoint> _parseTrackPoints(String xml) {
  final points = <TrackPoint>[];
  final trkptPattern = RegExp(
    r'<trkpt lat="([^"]+)" lon="([^"]+)">(.*?)</trkpt>',
    dotAll: true,
  );
  for (final m in trkptPattern.allMatches(xml)) {
    final lat = double.parse(m.group(1)!);
    final lon = double.parse(m.group(2)!);
    final body = m.group(3)!;
    final timeStr = _extractTag(body, 'time')!;
    final accuracyStr = _extractTag(body, 'sat:accuracy');
    final hasAccuracyStr = _extractTag(body, 'sat:has_accuracy');
    final speedStr = _extractTag(body, 'sat:speed');
    final hasSpeedStr = _extractTag(body, 'sat:has_speed');
    points.add(
      TrackPoint(
        latitude: lat,
        longitude: lon,
        timestamp: DateTime.parse(timeStr),
        accuracyMeters: double.tryParse(accuracyStr ?? '') ?? 9999,
        hasAccuracy: hasAccuracyStr == 'true',
        speedMps: double.tryParse(speedStr ?? ''),
        hasSpeed: hasSpeedStr == 'true',
      ),
    );
  }
  return points;
}
