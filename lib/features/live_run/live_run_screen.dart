import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';

import '../../core/units/units.dart';
import '../../domain/models/live_metrics.dart';
import '../../domain/tracking/run_phase.dart';
import '../export_help/export_help_screen.dart';
import 'live_run_controller.dart';
import 'live_run_state.dart';
import 'metric_spec.dart';

class _UseKmhNotifier extends Notifier<bool> {
  @override
  bool build() => true;

  void toggle() => state = !state;
}

final _useKmhProvider = NotifierProvider<_UseKmhNotifier, bool>(_UseKmhNotifier.new);

class LiveRunScreen extends ConsumerWidget {
  const LiveRunScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(liveRunControllerProvider);
    final controller = ref.read(liveRunControllerProvider.notifier);
    final useKmh = ref.watch(_useKmhProvider);

    // Before a run starts there is no reading to show or unit to toggle, so
    // the idle screen is just its Start button. The same applies to the
    // states that replace it when a run can't begin (no permission, location
    // services off) — those carry a message and a retry, not a readout.
    final showsReadout = state is LiveRunAcquiring ||
        state is LiveRunActive ||
        state is LiveRunFinished;

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Align(
              alignment: Alignment.topRight,
              child: showsReadout
                  ? TextButton(
                      onPressed: ref.read(_useKmhProvider.notifier).toggle,
                      child: Text(useKmh ? 'km/h' : 'min/km'),
                    )
                  // Holds the row's height so the content below doesn't
                  // shift up when the toggle appears on starting a run.
                  : const SizedBox(height: 48),
            ),
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
                              useKmh: useKmh,
                              unit: unit,
                            ),
                          )
                        else
                          const Spacer(),
                        _StatusLine(state: state, unit: unit),
                        if (metrics != null)
                          Expanded(
                            flex: 5,
                            child: _MetricGrid(
                              metrics: metrics,
                              useKmh: useKmh,
                              unit: unit,
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
  final bool useKmh;
  final double unit;

  const _PrimarySpeedReadout({
    required this.state,
    required this.useKmh,
    required this.unit,
  });

  @override
  Widget build(BuildContext context) {
    final speedMps = state is LiveRunActive ? (state as LiveRunActive).speedMps : null;
    final text = speedMps != null
        ? (useKmh ? formatKmh(speedMps) : formatPace(paceSecPerKmFromMps(speedMps)))
        : (useKmh ? '--.-' : '--:--');

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
                fontSize: unit * 15,
                fontWeight: FontWeight.w300,
                height: 1.1,
                color: Theme.of(context).colorScheme.onSurface,
              ),
            ),
          ),
        ),
        Text(
          useKmh ? 'km/h' : 'min/km',
          style: TextStyle(
            fontSize: unit * 4,
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
      LiveRunAcquiring() => 'Acquiring GPS…',
      LiveRunActive(phase: RunPhase.paused) => 'Paused',
      LiveRunActive(:final accuracyMeters) =>
        'Accuracy: ±${accuracyMeters.toStringAsFixed(0)} m',
      LiveRunFinished() => 'Run finished',
      LiveRunServiceDisabled() => 'Location services are turned off',
      LiveRunPermissionDenied(forever: true) =>
        'Location permission permanently denied',
      LiveRunPermissionDenied(forever: false) => 'Location permission denied',
    };

    final showSettingsAction = state is LiveRunPermissionDenied &&
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
  final bool useKmh;
  final double unit;

  const _MetricGrid({
    required this.metrics,
    required this.useKmh,
    required this.unit,
  });

  @override
  Widget build(BuildContext context) {
    // Two per row, so each tile gets half the width to grow into. An odd
    // spec count leaves the last tile centred on its own row rather than
    // stretched across the full width, which would make it read as more
    // important than the others.
    final rows = <List<MetricSpec>>[
      for (var i = 0; i < defaultMetricSpecs.length; i += 2)
        defaultMetricSpecs.sublist(
            i, (i + 2).clamp(0, defaultMetricSpecs.length)),
    ];

    return Column(
      mainAxisAlignment: MainAxisAlignment.spaceEvenly,
      children: [
        for (final row in rows)
          Row(
            children: [
              // Half-width padding either side keeps a lone final tile
              // centred and the same width as the tiles above it.
              if (row.length == 1) const Spacer(),
              for (final spec in row)
                Expanded(
                  flex: 2,
                  child: _MetricTile(
                    label: spec.label,
                    value: spec.valueOf(metrics, null, useKmh),
                    unit: unit,
                  ),
                ),
              if (row.length == 1) const Spacer(),
            ],
          ),
      ],
    );
  }
}

class _MetricTile extends StatelessWidget {
  final String label;
  final String value;
  final double unit;

  const _MetricTile({
    required this.label,
    required this.value,
    required this.unit,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Padding(
      padding: EdgeInsets.symmetric(horizontal: unit * 0.5),
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
              maxLines: 1,
              style: TextStyle(
                fontSize: unit * 7,
                fontWeight: FontWeight.w400,
                height: 1.1,
                color: theme.colorScheme.onSurface,
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
      LiveRunPermissionDenied() =>
        FilledButton(
          onPressed: controller.start,
          style: FilledButton.styleFrom(minimumSize: const Size(160, 56)),
          child: const Text('Start'),
        ),
      LiveRunFinished(:final exportedTo) => Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            FilledButton(
              onPressed: controller.startNewRun,
              style: FilledButton.styleFrom(minimumSize: const Size(160, 56)),
              child: const Text('New run'),
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
            const FilledButton(
              onPressed: null,
              child: Text('Acquiring…'),
            ),
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
              onPressed: phase == RunPhase.paused ? controller.resume : controller.pause,
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
        onPressed: () => ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Hold to stop')),
        ),
        style: FilledButton.styleFrom(minimumSize: const Size(120, 56)),
        child: const Text('Stop'),
      ),
    );
  }
}
