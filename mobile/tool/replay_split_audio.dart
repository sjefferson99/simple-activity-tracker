// Replays a real captured GPX file through the actual MetricsEngine +
// detectSplitAudioCue logic (issue #125), printing every cue that would
// fire and its verdict/beep-count — used to diagnose a real on-device bug
// (two GPX captures from a walk where the too-fast/too-slow beep pattern
// only ever played once, not 2/3 times) against the exact production code
// path, not a synthetic reproduction. Reads the plan/target straight out of
// the GPX's own sat:split_plan/sat:split_target extensions, same as the
// server's parser does.
//
// Stamps each tick's verdict with LiveSplitVerdictTracker, exactly as
// LiveRunController does, and also counts how many verdict cues the plain
// band (no hysteresis, issue #154) would have produced, for tuning.
//
// Usage (from mobile/): dart run tool/replay_split_audio.dart [--quiet] <path.gpx>...
//
// ignore_for_file: avoid_print — a CLI diagnostic tool's whole job is to
// print its findings; a logging framework would be pure ceremony here.
import 'dart:io';

import 'package:simple_activity_tracker/domain/models/live_metrics.dart';
import 'package:simple_activity_tracker/domain/models/track_point.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';
import 'package:simple_activity_tracker/domain/tracking/live_split_verdict.dart';
import 'package:simple_activity_tracker/domain/tracking/metrics_engine.dart';
import 'package:simple_activity_tracker/domain/tracking/split_audio_cue.dart';
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';
import 'package:simple_activity_tracker/domain/tracking/split_target.dart';

void main(List<String> args) {
  final quiet = args.contains('--quiet');
  final paths = args.where((a) => a != '--quiet').toList();
  if (paths.isEmpty) {
    stderr.writeln('Usage: dart run tool/replay_split_audio.dart [--quiet] <path.gpx>...');
    exit(1);
  }
  var totalLive = 0;
  var totalPlain = 0;
  var totalSplits = 0;
  for (final path in paths) {
    final (live, plain, splits) = _replay(path, quiet: quiet);
    totalLive += live;
    totalPlain += plain;
    totalSplits += splits;
  }
  if (paths.length > 1) {
    print(
      '\nAll ${paths.length} files, $totalSplits targeted splits: verdict cues '
      '$totalLive with hysteresis vs $totalPlain with the plain band',
    );
  }
}

/// Returns (verdict cues with hysteresis, verdict cues with the plain band,
/// targeted splits seen).
(int, int, int) _replay(String path, {required bool quiet}) {
  void say(String line) {
    if (!quiet) print(line);
  }

  final xml = File(path).readAsStringSync();

  final splitType = _extractTag(xml, 'sat:split_type');
  final splitValue = _extractTag(xml, 'sat:split_value');
  final splitPlanRaw = _extractTag(xml, 'sat:split_plan');
  final rollingTarget = double.tryParse(_extractTag(xml, 'sat:split_target') ?? '');
  say('split_type=$splitType split_value=$splitValue split_plan=$splitPlanRaw split_target=$rollingTarget');

  final kind = switch (splitType) {
    'distance_km' => SplitKind.distanceKm,
    'distance_mi' => SplitKind.distanceMi,
    'time_min' => SplitKind.timeMin,
    _ => SplitKind.distanceKm,
  };
  final base = SplitPreference(kind: kind, value: int.parse(splitValue ?? '1'));
  final customSplits = <PlannedSplit>[];
  if (splitPlanRaw != null && splitPlanRaw.isNotEmpty) {
    for (final entry in splitPlanRaw.split(';')) {
      final parts = entry.split('@');
      final size = double.parse(parts[0]);
      final target = parts.length > 1 ? double.parse(parts[1]) : null;
      customSplits.add(PlannedSplit(size: size, targetSpeedMps: target));
    }
  }
  final plan = SplitPlan(
    base: base,
    customSplits: customSplits,
    rollingTargetSpeedMps: customSplits.isEmpty ? rollingTarget : null,
  );
  say(
    'Parsed plan: ${plan.customSplits.length} custom splits, '
    'base ${plan.base.kind.name}=${plan.base.value}',
  );
  for (var i = 0; i < plan.customSplits.length; i++) {
    say('  split ${i + 1}: size=${plan.sizeOf(i)} target=${plan.targetOf(i)}');
  }

  final points = _parseTrackPoints(xml);
  say('Parsed ${points.length} track points\n');

  final engine = MetricsEngine(mode: ActivityMode.running, splitPlan: plan);
  final tracker = LiveSplitVerdictTracker();
  LiveMetrics? previous;
  LiveMetrics? previousPlain;
  var cueCount = 0;
  var liveVerdictCues = 0;
  var plainVerdictCues = 0;
  final targetedSplits = <int>{};

  for (final point in points) {
    engine.addPoint(point);
    final raw = engine.metrics;
    final current = raw.withCurrentSplitVerdict(tracker.update(raw));
    if (raw.currentSplit.targetSpeedMps != null) targetedSplits.add(raw.currentSplit.index);

    // The same tick judged by the plain band, for comparison only.
    final plain = raw.withCurrentSplitVerdict(
      splitVerdict(
        avgSpeedMps: _avgSpeedMps(raw),
        targetSpeedMps: raw.currentSplit.targetSpeedMps,
        elapsedInSplit: raw.currentSplitElapsed,
      ),
    );
    if (detectSplitAudioCue(previous: previousPlain, current: plain)?.kind == SplitAudioCueKind.verdict) {
      plainVerdictCues++;
    }
    previousPlain = plain;

    final cue = detectSplitAudioCue(previous: previous, current: current);
    if (cue != null) {
      cueCount++;
      if (cue.kind == SplitAudioCueKind.verdict) liveVerdictCues++;
      final beepDesc = switch (cue.kind) {
        SplitAudioCueKind.splitChanged => '1 beep (splitChanged)',
        SplitAudioCueKind.verdict => switch (cue.verdict!) {
            SplitVerdict.tooFast => '2 beeps (tooFast)',
            SplitVerdict.tooSlow => '3 beeps (tooSlow)',
            SplitVerdict.onTarget => '1 long beep (onTarget)',
          },
      };
      say(
        '[cue #$cueCount] t=${point.timestamp.toIso8601String()} '
        'splitIndex=${current.currentSplit.index} '
        'progress=${currentSplitProgress(current).toStringAsFixed(2)} '
        'avgSpeedMps=${_avgSpeedMps(current)?.toStringAsFixed(3)} '
        'target=${current.currentSplit.targetSpeedMps} '
        '-> $beepDesc',
      );
    }
    previous = current;
  }

  print(
    '$path: ${targetedSplits.length} targeted splits, verdict cues '
    '$liveVerdictCues with hysteresis vs $plainVerdictCues plain',
  );
  return (liveVerdictCues, plainVerdictCues, targetedSplits.length);
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
