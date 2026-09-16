import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_state_controller.dart';
import '../../core/sync/file_run_store.dart';
import '../../core/sync/sync_service.dart';
import '../../domain/models/run_record.dart';
import '../../domain/models/sync_status.dart';
import '../activity_history/activity_detail_screen.dart';
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
          if (record.syncStatus case SyncStatusUploaded(:final serverRunId)) ...[
            const SizedBox(height: 16),
            _AnalysisLink(
              serverRunId: serverRunId,
              analysisResult: record.analysisResult,
              analysisFailed: record.analysisFailed,
            ),
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

/// Replaces the old inline "Insights" section (issue #97/#101, Slice C) with
/// a thin link into the activity detail screen (Slice A), which already
/// renders the same server analysis/splits/targets — this widget never
/// duplicates that rendering, only a pending/failed/done state check. See
/// docs/ACTIVITY-HISTORY-PLAN.md D5 for why: an in-place inline section here
/// would either show a second, separate splits/targets view or need to
/// import Slice A's widget anyway, so linking through avoids maintaining two
/// paths to the same data.
class _AnalysisLink extends StatelessWidget {
  final String serverRunId;
  final Map<String, dynamic>? analysisResult;
  final bool analysisFailed;

  const _AnalysisLink({
    required this.serverRunId,
    required this.analysisResult,
    required this.analysisFailed,
  });

  @override
  Widget build(BuildContext context) {
    if (analysisResult != null) {
      return TextButton(
        onPressed: () => Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => ActivityDetailScreen(activityId: serverRunId),
          ),
        ),
        child: const Text('View full summary'),
      );
    }
    if (analysisFailed) {
      return const Text(
        'Analysis failed',
        style: TextStyle(fontStyle: FontStyle.italic),
      );
    }
    return const Text(
      'Analysis not available yet',
      style: TextStyle(fontStyle: FontStyle.italic),
    );
  }
}
