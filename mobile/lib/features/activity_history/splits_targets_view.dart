import 'package:flutter/material.dart';

import '../../core/api/tolerant_json.dart';
import '../../core/units/units.dart';
import '../../domain/tracking/split_target.dart';

/// Renders the `splits` array from a server `AnalysisOut.result` (issue
/// #101) as a table: index, distance, duration, avg pace/speed, and — only
/// when any split has a target (mirroring the web app's `has_targets` gate,
/// `server/app/templates/partials/splits_table.html`) — a target column with
/// the same green/red verdict colouring and delta arrow the live screen's
/// `_SplitRow` already uses (`live_run_screen.dart`). Reused by both the
/// activity detail screen (Slice A) and, once built, the post-Stop summary
/// screen's link-through (Slice C) — this widget is the one place that
/// renders a finished split's target/verdict, so the two screens never
/// duplicate the logic.
///
/// Unlike the live screen, a finished split's verdict is read directly from
/// the server's own `verdict` string (`"on_target"|"too_fast"|"too_slow"`,
/// already computed server-side with no grace period — `server/app/analysis/v1.py`)
/// rather than recomputed from `splitVerdict()`, which is for a live,
/// still-in-progress split.
class SplitsTargetsView extends StatelessWidget {
  final Map<String, dynamic> analysisResult;

  const SplitsTargetsView({required this.analysisResult, super.key});

  @override
  Widget build(BuildContext context) {
    // A split missing a field this row needs is skipped rather than crashing
    // the screen — docs/VERSIONING.md §3.3.
    final splits = readMapList(analysisResult, 'splits')
        .where(
          (s) =>
              readInt(s, 'index') != null &&
              readDouble(s, 'distance_m') != null &&
              readDouble(s, 'duration_seconds') != null,
        )
        .toList();
    if (splits.isEmpty) return const SizedBox.shrink();

    final targetsAs = readString(analysisResult, 'split_targets_as');
    final speedUnit = _speedUnitFor(
      splitType: readString(analysisResult, 'split_type'),
      targetsAs: targetsAs,
    );
    final hasTargets = splits.any((s) => readDouble(s, 'target_speed_mps') != null);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Splits', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        for (final split in splits)
          _SplitTargetRow(
            split: split,
            speedUnit: speedUnit,
            showTarget: hasTargets,
          ),
      ],
    );
  }

  /// The distance unit for pace/speed formatting comes from the activity's
  /// own `split_type` (present on every analysed activity, targeted or not);
  /// pace-vs-speed comes from `split_targets_as`, present only when a plan
  /// with targets was uploaded. A `null`/unrecognised `split_targets_as`
  /// defaults to plain speed in the split's own distance unit, matching how
  /// an activity with no targets at all still shows plain speed/pace.
  SpeedUnit _speedUnitFor({required String? splitType, required String? targetsAs}) {
    final distanceUnit = splitType == 'distance_mi' ? DistanceUnit.mi : DistanceUnit.km;
    if (targetsAs == 'pace') {
      return distanceUnit == DistanceUnit.mi ? SpeedUnit.minMi : SpeedUnit.minKm;
    }
    return SpeedUnit.initialFor(distanceUnit);
  }
}

class _SplitTargetRow extends StatelessWidget {
  final Map<String, dynamic> split;
  final SpeedUnit speedUnit;
  final bool showTarget;

  const _SplitTargetRow({
    required this.split,
    required this.speedUnit,
    required this.showTarget,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    // Presence of the first three is checked by SplitsTargetsView's filter.
    final index = readInt(split, 'index')!;
    final distanceM = readDouble(split, 'distance_m')!;
    final durationS = readDouble(split, 'duration_seconds')!;
    final avgSpeedMps = readDouble(split, 'avg_speed_mps');
    final targetSpeedMps = readDouble(split, 'target_speed_mps');
    final verdictName = readString(split, 'verdict');

    final verdict = switch (verdictName) {
      'on_target' => SplitVerdict.onTarget,
      'too_fast' => SplitVerdict.tooFast,
      'too_slow' => SplitVerdict.tooSlow,
      _ => null,
    };
    final valueColor = switch (verdict) {
      SplitVerdict.onTarget => Colors.green.shade700,
      SplitVerdict.tooFast || SplitVerdict.tooSlow => theme.colorScheme.error,
      null => theme.colorScheme.onSurface,
    };

    final distanceText = speedUnit.distanceUnit == DistanceUnit.mi
        ? '${formatDistanceMi(distanceM)} mi'
        : '${formatDistanceKm(distanceM)} km';

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text('#$index', style: TextStyle(color: theme.colorScheme.onSurfaceVariant)),
          Text(distanceText),
          Text(formatDuration(Duration(seconds: durationS.round()))),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                formatSpeedOrPace(avgSpeedMps, speedUnit),
                style: TextStyle(fontWeight: FontWeight.w500, color: valueColor),
              ),
              if (showTarget)
                Text(
                  targetSpeedMps == null || avgSpeedMps == null
                      ? '—'
                      : formatSpeedDelta(avgSpeedMps, targetSpeedMps, speedUnit),
                  style: TextStyle(fontSize: 12, color: valueColor),
                ),
            ],
          ),
        ],
      ),
    );
  }
}
