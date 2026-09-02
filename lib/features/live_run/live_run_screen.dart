import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';

import '../../core/units/units.dart';
import '../../domain/models/live_metrics.dart';
import '../../domain/tracking/run_phase.dart';
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

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Align(
              alignment: Alignment.topRight,
              child: TextButton(
                onPressed: ref.read(_useKmhProvider.notifier).toggle,
                child: Text(useKmh ? 'km/h' : 'min/km'),
              ),
            ),
            Expanded(
              child: Center(
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _PrimarySpeedReadout(state: state, useKmh: useKmh),
                      const SizedBox(height: 8),
                      _StatusLine(state: state),
                      const SizedBox(height: 24),
                      if (state is LiveRunActive)
                        _MetricGrid(metrics: state.metrics, useKmh: useKmh),
                      if (state is LiveRunFinished)
                        _MetricGrid(metrics: state.metrics, useKmh: useKmh),
                      const SizedBox(height: 32),
                      _Controls(state: state, controller: controller),
                    ],
                  ),
                ),
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

  const _PrimarySpeedReadout({required this.state, required this.useKmh});

  @override
  Widget build(BuildContext context) {
    final speedMps = state is LiveRunActive ? (state as LiveRunActive).speedMps : null;
    final text = speedMps != null
        ? (useKmh ? formatKmh(speedMps) : formatPace(paceSecPerKmFromMps(speedMps)))
        : (useKmh ? '--.-' : '--:--');

    return Column(
      children: [
        Text(text, style: Theme.of(context).textTheme.displayLarge),
        Text(useKmh ? 'km/h' : 'min/km', style: Theme.of(context).textTheme.titleMedium),
      ],
    );
  }
}

class _StatusLine extends StatelessWidget {
  final LiveRunState state;

  const _StatusLine({required this.state});

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
        Text(message, style: Theme.of(context).textTheme.bodyMedium),
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

  const _MetricGrid({required this.metrics, required this.useKmh});

  @override
  Widget build(BuildContext context) {
    return Wrap(
      alignment: WrapAlignment.center,
      spacing: 24,
      runSpacing: 16,
      children: [
        for (final spec in defaultMetricSpecs)
          _MetricTile(
            label: spec.label,
            value: spec.valueOf(metrics, null, useKmh),
          ),
      ],
    );
  }
}

class _MetricTile extends StatelessWidget {
  final String label;
  final String value;

  const _MetricTile({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 140,
      child: Column(
        children: [
          Text(value, style: Theme.of(context).textTheme.headlineSmall),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
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
      LiveRunFinished() => FilledButton(
          onPressed: controller.startNewRun,
          style: FilledButton.styleFrom(minimumSize: const Size(160, 56)),
          child: const Text('New run'),
        ),
      LiveRunAcquiring() => const FilledButton(
          onPressed: null,
          child: Text('Acquiring…'),
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
