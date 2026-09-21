import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';

import '../../core/tracking/activity_mode_controller.dart';
import '../../core/tracking/split_plan_controller.dart';
import '../../core/units/units.dart';
import '../../domain/models/live_metrics.dart';
import '../../domain/models/split.dart' as domain;
import '../../domain/tracking/activity_mode.dart';
import '../../domain/tracking/run_phase.dart';
import '../../domain/tracking/split_plan.dart';
import '../../domain/tracking/split_preference.dart' show SplitKind;
import '../../domain/tracking/split_target.dart';
import '../activity_history/activity_list_screen.dart';
import '../export_help/export_help_screen.dart';
import '../settings/settings_screen.dart';
import '../splits/splits_screen.dart';
import 'live_run_controller.dart';
import 'live_run_state.dart';
import 'metric_spec.dart';
import 'run_insights.dart';

/// The live run screen's speed/pace toggle. Starts at null (meaning: not yet
/// pinned to a run) and is set to the run's initial [SpeedUnit] — derived
/// from the run's split preference (issue #94) and its "targets as
/// pace/speed" preference (issue #99) — the moment a run reaches
/// [LiveRunActive]/[LiveRunFinished], via [_SpeedUnitNotifier.startRun].
/// From there, tapping the toggle only ever cycles speed ⇄ pace within that
/// run's distance unit (km-based or mile-based) — it never switches between
/// km and miles mid-run, matching [LiveRunActive.distanceUnit]/
/// [LiveRunActive.activityMode] being fixed for a run's whole duration.
class _SpeedUnitNotifier extends Notifier<SpeedUnit?> {
  @override
  SpeedUnit? build() => null;

  /// Resets the toggle to [unit]'s speed or pace member, per [prefersPace] —
  /// called once per run, when the run's distance unit becomes known.
  void startRun(DistanceUnit unit, bool prefersPace) {
    final speedFirst = SpeedUnit.initialFor(unit);
    state = prefersPace ? speedFirst.toggled : speedFirst;
  }

  void toggle() {
    final current = state;
    if (current != null) state = current.toggled;
  }
}

final _speedUnitProvider = NotifierProvider<_SpeedUnitNotifier, SpeedUnit?>(
  _SpeedUnitNotifier.new,
);

class _SplitsExpandedNotifier extends Notifier<bool> {
  @override
  bool build() => false;

  void toggle() => state = !state;
}

/// Collapsed by default so the fixed, non-scrolling live-run layout doesn't
/// start out crowded — most of a run has few enough splits that the reader
/// only wants the list once there's something worth reviewing.
final _splitsExpandedProvider = NotifierProvider<_SplitsExpandedNotifier, bool>(
  _SplitsExpandedNotifier.new,
);

/// Run/Cycle segmented toggle, always on the home screen (not tucked into
/// Settings) since it changes how GPS is interpreted for the next run, not
/// just a display preference.
class _ActivityModeToggle extends ConsumerWidget {
  const _ActivityModeToggle();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(activityModeControllerProvider);

    return SegmentedButton<ActivityMode>(
      segments: const [
        ButtonSegment(value: ActivityMode.running, label: Text('Run')),
        ButtonSegment(value: ActivityMode.walking, label: Text('Walk')),
        ButtonSegment(value: ActivityMode.cycling, label: Text('Cycle')),
      ],
      selected: {mode},
      showSelectedIcon: false,
      onSelectionChanged: (selected) => ref
          .read(activityModeControllerProvider.notifier)
          .select(selected.first),
      style: const ButtonStyle(visualDensity: VisualDensity.compact),
    );
  }
}

/// A one-line summary of the current split plan, tappable to open the
/// Splits screen (issue #99 D3) — same reasoning as [_ActivityModeToggle]
/// living on the home screen: it changes how the next run is captured, not
/// just how it's displayed.
class _SplitsSummaryRow extends ConsumerWidget {
  const _SplitsSummaryRow();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final plan = ref.watch(splitPlanControllerProvider);
    final unit = plan.targetsAsPace
        ? SpeedUnit.initialFor(plan.base.effectiveDistanceUnit).toggled
        : SpeedUnit.initialFor(plan.base.effectiveDistanceUnit);

    final summary = plan.isCustom
        ? 'Splits: custom, ${plan.customSplits.length} splits'
        : plan.rollingTargetSpeedMps != null
        ? 'Splits: every ${_rollingSizeLabel(plan)} '
              '@ ${formatTargetForEditing(plan.rollingTargetSpeedMps!, unit)} ${unit.suffix}'
        : 'Splits: every ${_rollingSizeLabel(plan)}';

    return InkWell(
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => const SplitsScreen()),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          mainAxisSize: MainAxisSize.min,
          children: [
            Flexible(
              child: Text(
                summary,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ),
            Icon(
              Icons.chevron_right,
              size: 18,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ],
        ),
      ),
    );
  }

  double _rollingSizeMeters(SplitPlan plan) => switch (plan.base.kind) {
    SplitKind.distanceKm => plan.base.value * 1000.0,
    SplitKind.distanceMi => plan.base.value * metersPerMile,
    SplitKind.timeMin => 0, // unused: time kind formats via _rollingSizeLabel
  };

  String _rollingSizeLabel(SplitPlan plan) => plan.base.kind == SplitKind.timeMin
      ? '${plan.base.value} min'
      : formatSplitSizeMeters(_rollingSizeMeters(plan), plan.base.effectiveDistanceUnit);
}

class LiveRunScreen extends ConsumerWidget {
  const LiveRunScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(liveRunControllerProvider);
    final controller = ref.read(liveRunControllerProvider.notifier);

    // The mode a run is actually recorded under — the source of truth once a
    // run has started/finished, since LiveRunController fixes it at start()
    // and it must not change mid-run even if the (now-hidden) home screen
    // toggle's own state moved on. Before a run starts, this falls back to
    // the toggle's live value so the idle screen's tile-less UI has
    // something to key off of if it ever needs to.
    final runActivityMode = switch (state) {
      LiveRunActive(:final activityMode) => activityMode,
      LiveRunFinished(:final activityMode) => activityMode,
      _ => ref.watch(activityModeControllerProvider),
    };
    final isCycling = runActivityMode == ActivityMode.cycling;

    // The distance unit this run's splits (and therefore its speed/pace/
    // elevation display) use — fixed once the run starts, same rationale as
    // runActivityMode (issue #94). Before a run starts, falls back to the
    // live split plan setting.
    final runDistanceUnit = switch (state) {
      LiveRunActive(:final distanceUnit) => distanceUnit,
      LiveRunFinished(:final distanceUnit) => distanceUnit,
      _ => ref.watch(splitPlanControllerProvider).base.effectiveDistanceUnit,
    };

    // Pins the toggle to this run's distance unit and pace/speed preference
    // the moment they become available, so a run started with mile splits
    // opens on mph rather than whatever unit a previous running-mode session
    // left the toggle on. Runs (never fired for the idle/acquiring states
    // this reaches before a run has one) — _speedUnitProvider only resets
    // here, so a manual tap via toggle() persists across ticks within the
    // same run.
    ref.listen(liveRunControllerProvider, (previous, next) {
      final (unit, prefersPace) = switch (next) {
        LiveRunActive(:final distanceUnit, :final prefersPace) => (
          distanceUnit,
          prefersPace,
        ),
        LiveRunFinished(:final distanceUnit, :final prefersPace) => (
          distanceUnit,
          prefersPace,
        ),
        _ => (null, true),
      };
      final wasActive =
          previous is LiveRunActive || previous is LiveRunFinished;
      if (unit != null && !wasActive) {
        ref.read(_speedUnitProvider.notifier).startRun(unit, prefersPace);
      }
    });

    // Cycling has no pace concept — the toggle is forced to the speed-only
    // member and hidden rather than just disabled, so a run started in
    // cycling mode never shows a pace readout even if the toggle was left on
    // pace from a previous running-mode session. Falls back to this run's
    // initial unit until the listener above has fired at least once (e.g.
    // the very first frame of LiveRunActive).
    final speedUnit =
        ref.watch(_speedUnitProvider) ?? SpeedUnit.initialFor(runDistanceUnit);
    final effectiveUnit = isCycling
        ? (speedUnit.distanceUnit == DistanceUnit.mi
              ? SpeedUnit.mph
              : SpeedUnit.kmh)
        : speedUnit;

    // Before a run starts there is no reading to show or unit to toggle, so
    // the idle screen is just its Start button. The same applies to the
    // states that replace it when a run can't begin (no permission, location
    // services off) — those carry a message and a retry, not a readout.
    final showsReadout =
        state is LiveRunAcquiring ||
        state is LiveRunActive ||
        state is LiveRunFinished;

    // The activity mode is fixed once a run starts (LiveRunController reads
    // it only at start()), so switching it mid-run wouldn't do anything —
    // the toggle is only shown while that would actually take effect.
    final canSwitchActivityMode = !showsReadout;

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            // Stacked rather than a single spaceBetween Row: with unequal
            // side elements (a fixed-width icon vs. a variable-width or
            // empty right slot), spaceBetween centres the middle child on
            // the *leftover space between its neighbours*, not on the
            // screen — visibly off-centre by about the icon's width. The
            // toggle is centred on the row itself here instead, independent
            // of what the side elements measure.
            Stack(
              alignment: Alignment.center,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        IconButton(
                          onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => const SettingsScreen(),
                            ),
                          ),
                          icon: const Icon(Icons.settings_outlined),
                        ),
                        IconButton(
                          onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                              builder: (_) => const ActivityListScreen(),
                            ),
                          ),
                          icon: const Icon(Icons.history),
                          tooltip: 'Activity history',
                        ),
                      ],
                    ),
                    // Cycling never shows a unit toggle at all — pace isn't a
                    // cycling concept, so there's nothing to switch to.
                    showsReadout && !isCycling
                        ? TextButton(
                            onPressed: ref
                                .read(_speedUnitProvider.notifier)
                                .toggle,
                            // Shows what tapping switches *to*, not the
                            // current unit — e.g. while displaying km/h,
                            // this reads "min/km".
                            child: Text(effectiveUnit.toggled.suffix),
                          )
                        // Holds the row's height so the content below doesn't
                        // shift up when the toggle appears on starting a run.
                        : const SizedBox(height: 48),
                  ],
                ),
                if (canSwitchActivityMode) const _ActivityModeToggle(),
              ],
            ),
            // Only meaningful before a run starts (the plan is fixed for a
            // run's whole duration, same as activity mode/distance unit) and
            // only for running — cycling hides splits entirely (issue #99
            // D8), so a row promising split configuration here would be
            // misleading in cycling mode.
            if (canSwitchActivityMode && !isCycling) const _SplitsSummaryRow(),
            Expanded(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  final metrics = switch (state) {
                    LiveRunActive(:final metrics) => metrics,
                    LiveRunFinished(:final metrics) => metrics,
                    _ => null,
                  };

                  // One type scale for the whole screen, derived from the
                  // space available, so the display grows into whatever
                  // screen it's on instead of floating at a fixed size.
                  // Sizing each number to its own string instead would make
                  // tiles disagree with each other and resize as values
                  // change (a 3-digit pace shrinking the moment it ticks
                  // over from 2 digits).
                  final unit = constraints.maxHeight / 100;

                  return Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    child: Column(
                      children: [
                        if (showsReadout)
                          Expanded(
                            // With no grid to show, the readout takes the
                            // space the grid would have had.
                            flex: metrics == null ? 5 : 3,
                            child: _PrimarySpeedReadout(
                              state: state,
                              unit: effectiveUnit,
                              sizeUnit: unit,
                            ),
                          )
                        else
                          const Spacer(),
                        _StatusLine(state: state, unit: unit),
                        if (metrics != null)
                          Expanded(
                            flex: 5,
                            // Scrollable rather than a bare Column: a tile
                            // showing both a target and a settled delta (or
                            // two such tiles adjacent) can be taller than
                            // this shared type scale expects, and the
                            // available height itself differs between the
                            // live-tracking and run-finished layouts (extra
                            // controls/upload status below). A real
                            // vertical-overflow error banner was found
                            // on-device in exactly that combination — this
                            // makes it scroll instead of physically unable
                            // to overflow, rather than trying to keep
                            // shrinking tile content to guess-fit every case.
                            child: SingleChildScrollView(
                              child: Column(
                                children: [
                                  _MetricGrid(
                                    metrics: metrics,
                                    speedUnit: effectiveUnit,
                                    unit: unit,
                                    activityMode: runActivityMode,
                                  ),
                                  if (!isCycling)
                                    _SplitsPanel(
                                      completedSplits: metrics.completedSplits,
                                      speedUnit: effectiveUnit,
                                      unit: unit,
                                    ),
                                ],
                              ),
                            ),
                          ),
                        SizedBox(height: unit * 3),
                        _Controls(state: state, controller: controller),
                        if (showsReadout)
                          SizedBox(height: unit * 3)
                        else
                          const Spacer(),
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _PrimarySpeedReadout extends StatelessWidget {
  final LiveRunState state;
  final SpeedUnit unit;
  final double sizeUnit;

  const _PrimarySpeedReadout({
    required this.state,
    required this.unit,
    required this.sizeUnit,
  });

  @override
  Widget build(BuildContext context) {
    final speedMps = state is LiveRunActive
        ? (state as LiveRunActive).speedMps
        : null;
    final text = speedMps == null
        ? (unit.isPace ? '--:--' : '--.-')
        : unit.isPace
        ? formatPace(
            unit == SpeedUnit.minMi
                ? paceSecPerMileFromMps(speedMps)
                : paceSecPerKmFromMps(speedMps),
          )
        : unit == SpeedUnit.mph
        ? formatMph(speedMps)
        : formatKmh(speedMps);

    // The number you read at arm's length mid-run, so it gets the largest
    // size on the screen. scaleDown only shrinks if a value would not
    // otherwise fit, so the size stays put as the reading changes.
    return Column(
      mainAxisAlignment: MainAxisAlignment.end,
      children: [
        Flexible(
          child: FittedBox(
            fit: BoxFit.scaleDown,
            child: Text(
              text,
              style: TextStyle(
                fontSize: sizeUnit * 15,
                fontWeight: FontWeight.w300,
                height: 1.1,
                color: Theme.of(context).colorScheme.onSurface,
              ),
            ),
          ),
        ),
        Text(
          unit.suffix,
          style: TextStyle(
            fontSize: sizeUnit * 4,
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
      ],
    );
  }
}

class _StatusLine extends StatelessWidget {
  final LiveRunState state;
  final double unit;

  const _StatusLine({required this.state, required this.unit});

  @override
  Widget build(BuildContext context) {
    final message = switch (state) {
      LiveRunIdle() => 'Press Start to begin tracking',
      LiveRunAcquiring(timedOut: true) =>
        'Still waiting for GPS — check Location mode and Wi-Fi',
      LiveRunAcquiring() => 'Acquiring GPS…',
      LiveRunActive(phase: RunPhase.paused) => 'Paused',
      LiveRunActive(:final accuracyMeters) =>
        'Accuracy: ±${accuracyMeters.toStringAsFixed(0)} m',
      LiveRunFinished() => 'Activity finished',
      LiveRunServiceDisabled() => 'Location services are turned off',
      LiveRunPermissionDenied(forever: true) =>
        'Location permission permanently denied',
      LiveRunPermissionDenied(forever: false) => 'Location permission denied',
    };

    final showSettingsAction =
        state is LiveRunPermissionDenied &&
        (state as LiveRunPermissionDenied).forever;

    return Column(
      children: [
        Text(
          message,
          textAlign: TextAlign.center,
          style: TextStyle(
            fontSize: unit * 2.8,
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
        if (showSettingsAction)
          TextButton(
            onPressed: Geolocator.openAppSettings,
            child: const Text('Open app settings'),
          ),
      ],
    );
  }
}

class _MetricGrid extends StatelessWidget {
  final LiveMetrics metrics;
  final SpeedUnit speedUnit;
  final double unit;
  final ActivityMode activityMode;

  const _MetricGrid({
    required this.metrics,
    required this.speedUnit,
    required this.unit,
    required this.activityMode,
  });

  @override
  Widget build(BuildContext context) {
    final specs = metricSpecsFor(activityMode);

    // Two per row, so each tile gets half the width to grow into. An odd
    // spec count leaves the last tile centred on its own row rather than
    // stretched across the full width, which would make it read as more
    // important than the others.
    final rows = <List<MetricSpec>>[
      for (var i = 0; i < specs.length; i += 2)
        specs.sublist(i, (i + 2).clamp(0, specs.length)),
    ];

    return Column(
      // Explicit gaps rather than mainAxisAlignment.spaceEvenly: this
      // Column now lives inside a SingleChildScrollView (to fix a real
      // vertical-overflow bug — see the caller), which gives it unbounded
      // height, and spaceEvenly can't distribute infinite space.
      mainAxisSize: MainAxisSize.min,
      children: [
        for (final row in rows) ...[
          if (row != rows.first) SizedBox(height: unit * 1.5),
          Row(
            children: [
              // Half-width padding either side keeps a lone final tile
              // centred and the same width as the tiles above it.
              if (row.length == 1) const Spacer(),
              for (final spec in row)
                Expanded(
                  flex: 2,
                  child: _MetricTile(
                    label: spec.label(speedUnit),
                    description: spec.description,
                    value: spec.valueOf(metrics, null, speedUnit),
                    detail: spec.detail?.call(metrics, speedUnit),
                    verdict: spec.verdict?.call(metrics),
                    unit: unit,
                  ),
                ),
              if (row.length == 1) const Spacer(),
            ],
          ),
        ],
      ],
    );
  }
}

/// Collapsed row below the metric grid that expands into a scrollable list
/// of every completed split. Hidden entirely for cycling (no split-pace
/// concept — see the cycling [MetricSpec] layout) and while there are no
/// completed splits yet, so it never claims space with nothing to show.
class _SplitsPanel extends ConsumerWidget {
  final List<domain.Split> completedSplits;
  final SpeedUnit speedUnit;
  final double unit;

  const _SplitsPanel({
    required this.completedSplits,
    required this.speedUnit,
    required this.unit,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (completedSplits.isEmpty) return const SizedBox.shrink();

    final expanded = ref.watch(_splitsExpandedProvider);
    final theme = Theme.of(context);

    return Column(
      children: [
        InkWell(
          onTap: ref.read(_splitsExpandedProvider.notifier).toggle,
          child: Padding(
            padding: EdgeInsets.symmetric(vertical: unit * 1.2),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'Splits (${completedSplits.length})',
                  style: TextStyle(
                    fontSize: unit * 2.8,
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                Icon(
                  expanded ? Icons.expand_less : Icons.expand_more,
                  color: theme.colorScheme.onSurfaceVariant,
                  size: unit * 3.2,
                ),
              ],
            ),
          ),
        ),
        if (expanded)
          ConstrainedBox(
            constraints: BoxConstraints(maxHeight: unit * 22),
            child: ListView.separated(
              shrinkWrap: true,
              itemCount: completedSplits.length,
              // Most recent split first — the one the runner just finished
              // is what they want to check without scrolling.
              itemBuilder: (context, index) => _SplitRow(
                split: completedSplits[completedSplits.length - 1 - index],
                speedUnit: speedUnit,
                unit: unit,
              ),
              separatorBuilder: (context, index) =>
                  Divider(height: 1, color: theme.colorScheme.outlineVariant),
            ),
          ),
      ],
    );
  }
}

class _SplitRow extends StatelessWidget {
  final domain.Split split;
  final SpeedUnit speedUnit;
  final double unit;

  const _SplitRow({
    required this.split,
    required this.speedUnit,
    required this.unit,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final paceOrSpeed = formatSpeedOrPace(split.avgSpeedMps, speedUnit);
    final distanceText = speedUnit.distanceUnit == DistanceUnit.mi
        ? '${formatDistanceMi(split.distanceMeters)} mi'
        : '${formatDistanceKm(split.distanceMeters)} km';

    // No grace period here — a completed split's average is already its
    // final, settled figure (see MetricSpec's _lastSplitSpec.verdict doc).
    final target = split.targetSpeedMps;
    final verdict = target == null
        ? null
        : splitVerdict(
            avgSpeedMps: split.avgSpeedMps,
            targetSpeedMps: target,
            elapsedInSplit: split.duration,
          );
    final paceColor = switch (verdict) {
      SplitVerdict.onTarget => Colors.green.shade700,
      SplitVerdict.tooFast || SplitVerdict.tooSlow => theme.colorScheme.error,
      null => theme.colorScheme.onSurface,
    };

    return Padding(
      padding: EdgeInsets.symmetric(horizontal: unit * 2, vertical: unit * 1.4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            '#${split.index}',
            style: TextStyle(
              fontSize: unit * 2.8,
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          Text(distanceText, style: TextStyle(fontSize: unit * 2.8)),
          Text(
            formatDuration(split.duration),
            style: TextStyle(fontSize: unit * 2.8),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                paceOrSpeed,
                style: TextStyle(
                  fontSize: unit * 2.8,
                  fontWeight: FontWeight.w500,
                  color: paceColor,
                ),
              ),
              if (target != null)
                Text(
                  formatSpeedDelta(split.avgSpeedMps, target, speedUnit),
                  style: TextStyle(
                    fontSize: unit * 2.2,
                    color: paceColor,
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _MetricTile extends StatelessWidget {
  final String label;
  final String description;
  final String value;
  final double unit;

  /// A second line under [value] — the split's size/target and, once a
  /// verdict is available, the delta text (issue #99). Null for every tile
  /// except the split tiles.
  final String? detail;

  /// Whether this tile's split is on/off target, tinting the tile's
  /// background (issue #99) — null for no target/no tile-level target.
  final SplitVerdict? verdict;

  const _MetricTile({
    required this.label,
    required this.description,
    required this.value,
    required this.unit,
    this.detail,
    this.verdict,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    // Distance shows both km and mi stacked (issue #94: both are used by
    // runners at the same time, and two shorter lines fit the tile better
    // than one long "X km / Y mi" line) — every other tile's value is a
    // single line. A split tile with a detail line (issue #99) is also
    // multi-line, so the value gets the smaller two-line size in both cases.
    final valueLines = value.split('\n').length;
    final hasDetail = detail != null;
    // A tile with both a two-line detail (target + delta once judged) and a
    // verdict tint is taller than every other tile at this screen's shared
    // type scale — found on-device as a real vertical overflow once the
    // target line was added back alongside the delta. Trimming this
    // specific combination's detail size/padding keeps every tile within
    // the grid's fixed row height without shrinking anything else.
    final hasTwoLineDetail = hasDetail && detail!.contains('\n');
    final isTallTintedTile = hasTwoLineDetail && verdict != null;

    // A fixed green/red pair rather than theme tokens — Material's
    // ColorScheme has no "success" role, and error/onErrorContainer alone
    // isn't distinguishable from "too fast" vs "too slow" without also
    // conveying "good". Chosen at a fixed alpha over the surface so both
    // themes stay legible.
    final tintColor = switch (verdict) {
      SplitVerdict.onTarget => Colors.green,
      SplitVerdict.tooFast || SplitVerdict.tooSlow => theme.colorScheme.error,
      null => null,
    };

    // Tap (not long-press, which is reserved for Stop) shows what the
    // number measures, then fades — no modal to dismiss mid-run.
    return Tooltip(
      message: description,
      triggerMode: TooltipTriggerMode.tap,
      showDuration: const Duration(seconds: 5),
      margin: const EdgeInsets.symmetric(horizontal: 24),
      textStyle: TextStyle(
        fontSize: unit * 2.6,
        color: theme.colorScheme.onInverseSurface,
      ),
      child: Container(
        decoration: tintColor == null
            ? null
            : BoxDecoration(
                color: tintColor.withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(unit * 1.5),
              ),
        padding: EdgeInsets.symmetric(
          horizontal: unit * 0.5,
          vertical: tintColor == null ? 0 : (isTallTintedTile ? unit * 0.4 : unit * 0.8),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Every tile shares one size off the screen's type scale, so the
            // metrics read as peers and don't resize as their values change.
            // scaleDown is the safety net for an unusually wide value on a
            // narrow screen, not the thing choosing the size.
            FittedBox(
              fit: BoxFit.scaleDown,
              child: Text(
                value,
                textAlign: TextAlign.center,
                maxLines: valueLines,
                style: TextStyle(
                  fontSize: (valueLines > 1 || hasDetail) ? unit * 4.5 : unit * 7,
                  fontWeight: FontWeight.w400,
                  height: 1.15,
                  color: theme.colorScheme.onSurface,
                ),
              ),
            ),
            if (detail != null)
              Padding(
                padding: EdgeInsets.only(top: unit * 0.3),
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Text(
                    detail!,
                    textAlign: TextAlign.center,
                    maxLines: 2,
                    style: TextStyle(
                      fontSize: isTallTintedTile ? unit * 2.0 : unit * 2.4,
                      height: isTallTintedTile ? 1.0 : null,
                      color: tintColor != null
                          ? theme.colorScheme.onSurface
                          : theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                ),
              ),
            FittedBox(
              fit: BoxFit.scaleDown,
              child: Text(
                label,
                maxLines: 1,
                style: TextStyle(
                  fontSize: unit * 2.6,
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Controls extends StatelessWidget {
  final LiveRunState state;
  final LiveRunController controller;

  const _Controls({required this.state, required this.controller});

  @override
  Widget build(BuildContext context) {
    return switch (state) {
      LiveRunIdle() ||
      LiveRunServiceDisabled() ||
      LiveRunPermissionDenied() => FilledButton(
        onPressed: controller.start,
        style: FilledButton.styleFrom(minimumSize: const Size(160, 56)),
        child: const Text('Start'),
      ),
      LiveRunFinished(
        :final exportedTo,
        :final clientRunId,
        :final activityMode,
      ) =>
        Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (clientRunId != null) RunSyncSection(clientRunId: clientRunId),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                // Back to the idle screen — the only way to reach the
                // run/cycle toggle again, which the home screen hides once a
                // run is active or finished.
                OutlinedButton(
                  onPressed: controller.goToIdle,
                  style: OutlinedButton.styleFrom(
                    minimumSize: const Size(120, 56),
                  ),
                  child: const Text('Home'),
                ),
                const SizedBox(width: 16),
                FilledButton(
                  onPressed: controller.startNewRun,
                  style: FilledButton.styleFrom(
                    minimumSize: const Size(120, 56),
                  ),
                  child: Text(
                    switch (activityMode) {
                      ActivityMode.cycling => 'New ride',
                      ActivityMode.walking => 'New walk',
                      ActivityMode.running => 'New run',
                    },
                  ),
                ),
              ],
            ),
            TextButton(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => ExportHelpScreen(exportedTo: exportedTo),
                ),
              ),
              child: const Text("Where's my file?"),
            ),
          ],
        ),
      // GPS may never get a fix (indoors, hardware issue). Offer a way out —
      // the wakelock and flush timer are already running by this point.
      LiveRunAcquiring() => Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const FilledButton(onPressed: null, child: Text('Acquiring…')),
          const SizedBox(width: 16),
          OutlinedButton(
            onPressed: controller.stop,
            style: OutlinedButton.styleFrom(minimumSize: const Size(120, 56)),
            child: const Text('Cancel'),
          ),
        ],
      ),
      LiveRunActive(:final phase) => Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          FilledButton(
            onPressed: phase == RunPhase.paused
                ? controller.resume
                : controller.pause,
            style: FilledButton.styleFrom(minimumSize: const Size(120, 56)),
            child: Text(phase == RunPhase.paused ? 'Resume' : 'Pause'),
          ),
          const SizedBox(width: 16),
          _StopButton(controller: controller),
        ],
      ),
    };
  }
}

/// Requires a long-press to stop, so a run isn't ended by an accidental tap.
class _StopButton extends StatelessWidget {
  final LiveRunController controller;

  const _StopButton({required this.controller});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onLongPress: controller.stop,
      child: FilledButton.tonal(
        onPressed: () {
          // A bottom SnackBar sits right over this button on most layouts,
          // obscuring the very thing the hint is explaining how to use — a
          // MaterialBanner anchors to the top of the screen instead, so it
          // never covers the Stop button.
          final messenger = ScaffoldMessenger.of(context);
          messenger.clearMaterialBanners();
          messenger.showMaterialBanner(
            MaterialBanner(
              content: const Text('Press and hold to stop'),
              actions: [
                TextButton(
                  onPressed: messenger.hideCurrentMaterialBanner,
                  child: const Text('OK'),
                ),
              ],
            ),
          );
          Future.delayed(const Duration(seconds: 2), () {
            if (context.mounted) messenger.hideCurrentMaterialBanner();
          });
        },
        style: FilledButton.styleFrom(minimumSize: const Size(120, 56)),
        child: const Text('Stop'),
      ),
    );
  }
}
