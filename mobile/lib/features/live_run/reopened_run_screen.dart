import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/units/units.dart';
import '../../domain/models/run_record.dart';
import '../../domain/models/run_record_summary.dart';
import '../../domain/tracking/activity_mode.dart';
import '../export_help/export_help_screen.dart';
import 'confirm_delete_run_record.dart';
import 'live_run_screen.dart' show MetricGrid, SplitsPanel;
import 'run_insights.dart';

/// Reopens a locally-recorded run's finished summary (issue #106) from its
/// persisted [RunRecord] — reached from Settings' activity list, after the
/// live finished screen has long since been left and
/// [LiveRunController]'s state reset to idle. Deliberately never touches
/// [LiveRunController]: this is a pure read of on-disk data, so it can't
/// interfere with (or be interfered with by) an actually-in-progress run
/// elsewhere in the app.
///
/// Renders the same tile grid/splits list the live finished screen uses —
/// [MetricGrid]/[SplitsPanel], fed by a [ReopenedRunSummary] built from the
/// record — so a reopened run reads the same as it did when first finished,
/// including split targets/verdict tint, max speed, and elevation gain.
/// Controls are specific to a *past* run (Close, "Where's my file?",
/// Delete) rather than the live screen's Home/New run/Pause/Stop, which only
/// make sense for [LiveRunController]'s live state machine.
///
/// Pops with `true` if the record was deleted from this screen, `null`/
/// `false` otherwise — Settings' activity list (the only place this is
/// pushed from today) uses that to know it needs to refresh its own list,
/// since deleting here doesn't go through the same code path Settings' own
/// delete button does and so can't invalidate Settings' list provider
/// directly (that provider is private to settings_screen.dart).
class ReopenedRunScreen extends ConsumerWidget {
  final RunRecord record;

  const ReopenedRunScreen({required this.record, super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final reopened = reopenedRunSummaryFrom(record);
    final metrics = reopened.metrics;
    final isCycling = record.activityMode == ActivityMode.cycling;
    final speedUnit = SpeedUnit.initialFor(reopened.distanceUnit);

    return Scaffold(
      appBar: AppBar(title: const Text('Activity summary')),
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) {
            final unit = constraints.maxHeight / 100;

            return Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    SizedBox(height: unit * 2),
                    MetricGrid(
                      metrics: metrics,
                      speedUnit: speedUnit,
                      unit: unit,
                      activityMode: record.activityMode,
                    ),
                    if (!isCycling)
                      SplitsPanel(
                        completedSplits: metrics.completedSplits,
                        speedUnit: speedUnit,
                        unit: unit,
                      ),
                    RunSyncSection(clientRunId: record.clientRunId),
                    SizedBox(height: unit * 2),
                    _Controls(record: record),
                    SizedBox(height: unit * 3),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _Controls extends StatelessWidget {
  final RunRecord record;

  const _Controls({required this.record});

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            OutlinedButton(
              onPressed: () => Navigator.of(context).pop(),
              style: OutlinedButton.styleFrom(minimumSize: const Size(120, 56)),
              child: const Text('Close'),
            ),
            const SizedBox(width: 16),
            Consumer(
              builder: (context, ref, _) => OutlinedButton(
                onPressed: () => _confirmAndDelete(context, ref),
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size(120, 56),
                  foregroundColor: Theme.of(context).colorScheme.error,
                ),
                child: const Text('Delete'),
              ),
            ),
          ],
        ),
        TextButton(
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute(
              // Not persisted (see ReopenedRunSummary's doc) — the screen
              // already handles a null exportedTo with generic
              // platform-specific instructions.
              builder: (_) => const ExportHelpScreen(exportedTo: null),
            ),
          ),
          child: const Text("Where's my file?"),
        ),
      ],
    );
  }

  Future<void> _confirmAndDelete(BuildContext context, WidgetRef ref) async {
    final deleted = await confirmAndDeleteRunRecord(context, ref, record);
    if (deleted && context.mounted) Navigator.of(context).pop(true);
  }
}
