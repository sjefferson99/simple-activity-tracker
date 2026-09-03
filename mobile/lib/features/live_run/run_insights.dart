import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_state_controller.dart';
import '../../core/sync/file_run_store.dart';
import '../../core/sync/sync_service.dart';
import '../../core/units/units.dart';
import '../../domain/models/run_record.dart';
import '../../domain/models/sync_status.dart';
import '../settings/settings_screen.dart';

/// Tracks one run's [RunRecord] across its whole upload/analysis lifecycle,
/// re-fetching on every SyncService status change — the summary screen
/// watches this rather than polling.
final _runRecordProvider = StreamProvider.family<RunRecord?, String>((ref, clientRunId) async* {
  final runStore = ref.read(runStoreProvider);
  final syncService = ref.read(syncServiceProvider);

  Future<RunRecord?> fetch() async {
    for (final record in await runStore.listAll()) {
      if (record.clientRunId == clientRunId) return record;
    }
    return null;
  }

  yield await fetch();
  await for (final _ in syncService.statusChanges) {
    yield await fetch();
  }
});

/// The run summary screen's sync status line and, once the server has
/// finished analysing the upload, an "Insights" section — docs/WEB-PLAN.md
/// §6.3.
class RunSyncSection extends ConsumerWidget {
  final String clientRunId;

  const RunSyncSection({required this.clientRunId, super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final record = ref.watch(_runRecordProvider(clientRunId)).value;
    if (record == null) return const SizedBox.shrink();

    final isSignedIn = ref.watch(authStateControllerProvider).value?.isSignedIn ?? true;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Column(
        children: [
          _SyncStatusLine(status: record.syncStatus, isSignedIn: isSignedIn),
          if (record.syncStatus is SyncStatusUploaded) ...[
            const SizedBox(height: 16),
            _Insights(analysisResult: record.analysisResult),
          ],
        ],
      ),
    );
  }
}

class _SyncStatusLine extends StatelessWidget {
  final SyncStatus status;
  final bool isSignedIn;

  const _SyncStatusLine({required this.status, required this.isSignedIn});

  @override
  Widget build(BuildContext context) {
    if (!isSignedIn && status is! SyncStatusUploaded) {
      return TextButton(
        onPressed: () => Navigator.of(context).push(
          MaterialPageRoute(builder: (_) => const SettingsScreen()),
        ),
        child: const Text('Sign in to upload'),
      );
    }

    final text = switch (status) {
      SyncStatusPending() => 'Queued for upload',
      SyncStatusUploading() => 'Uploading…',
      SyncStatusUploaded() => 'Uploaded',
      SyncStatusFailed(:final retryable, :final error) =>
        retryable ? 'Upload failed, will retry' : 'Upload failed: $error',
    };

    return Text(text, style: Theme.of(context).textTheme.bodyMedium);
  }
}

class _Insights extends StatelessWidget {
  final Map<String, dynamic>? analysisResult;

  const _Insights({required this.analysisResult});

  @override
  Widget build(BuildContext context) {
    final result = analysisResult;
    if (result == null) {
      return const Text('Analysis pending', style: TextStyle(fontStyle: FontStyle.italic));
    }

    final elevation = result['elevation'] as Map<String, dynamic>?;
    final gainM = (elevation?['gain_m'] as num?)?.toDouble();
    final lossM = (elevation?['loss_m'] as num?)?.toDouble();
    final bestEfforts = (result['best_efforts'] as List<dynamic>?) ?? const [];
    final best1km = _bestEffortFor(bestEfforts, 1000);
    final best5km = _bestEffortFor(bestEfforts, 5000);
    final serverDistanceM = (result['distance_meters'] as num?)?.toDouble();
    final serverMovingS = (result['moving_seconds'] as num?)?.toDouble();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Insights', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 8),
        if (gainM != null) Text('Elevation gain: ${gainM.toStringAsFixed(0)} m'),
        if (lossM != null) Text('Elevation loss: ${lossM.toStringAsFixed(0)} m'),
        if (best1km != null) Text('Best 1 km: ${formatDuration(best1km)}'),
        if (best5km != null) Text('Best 5 km: ${formatDuration(best5km)}'),
        if (serverDistanceM != null)
          Text('Distance (server): ${formatDistanceKm(serverDistanceM)} km'),
        if (serverMovingS != null)
          Text('Moving time (server): ${formatDuration(Duration(seconds: serverMovingS.round()))}'),
      ],
    );
  }

  Duration? _bestEffortFor(List<dynamic> bestEfforts, double targetDistanceMeters) {
    for (final entry in bestEfforts) {
      final map = entry as Map<String, dynamic>;
      if ((map['distance_meters'] as num).toDouble() == targetDistanceMeters) {
        return Duration(seconds: (map['duration_seconds'] as num).round());
      }
    }
    return null;
  }
}
