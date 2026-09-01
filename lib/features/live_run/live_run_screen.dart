import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';

import '../../core/units/units.dart';
import 'live_run_controller.dart';
import 'live_run_state.dart';

class LiveRunScreen extends ConsumerWidget {
  const LiveRunScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(liveRunControllerProvider);
    final controller = ref.read(liveRunControllerProvider.notifier);

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _SpeedReadout(state: state),
              const SizedBox(height: 16),
              _StatusLine(state: state),
              const SizedBox(height: 48),
              FilledButton(
                onPressed: controller.toggle,
                style: FilledButton.styleFrom(
                  minimumSize: const Size(160, 56),
                ),
                child: Text(controller.isActive ? 'Stop' : 'Start'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SpeedReadout extends StatelessWidget {
  final LiveRunState state;

  const _SpeedReadout({required this.state});

  @override
  Widget build(BuildContext context) {
    final speedMps = state is LiveRunActive ? (state as LiveRunActive).speedMps : null;
    final text = speedMps != null ? formatKmh(speedMps) : '--.-';

    return Column(
      children: [
        Text(text, style: Theme.of(context).textTheme.displayLarge),
        Text('km/h', style: Theme.of(context).textTheme.titleMedium),
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
      LiveRunActive(:final accuracyMeters) =>
        'Accuracy: ±${accuracyMeters.toStringAsFixed(0)} m',
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
