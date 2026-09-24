import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/sync/file_run_store.dart';
import '../../domain/models/run_record.dart';
import '../../domain/models/sync_status.dart';

/// Confirms with the user, then deletes [record]'s local GPX/sidecar for
/// good — its only copy on this phone. Deleting here never touches the
/// server (issue #74: the two are managed independently once uploaded), but
/// is still permanent locally, so this always confirms first. Shared between
/// Settings' activity list and the reopened-run summary screen (issue #106)
/// so both present the exact same warning rather than two copies that could
/// drift apart.
///
/// Returns true if the record was deleted, false if the user cancelled.
Future<bool> confirmAndDeleteRunRecord(
  BuildContext context,
  WidgetRef ref,
  RunRecord record,
) async {
  final isUploaded = record.syncStatus is SyncStatusUploaded;
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('Delete this activity?'),
      content: Text(
        isUploaded
            ? 'This removes the activity from this phone only. The copy '
                  'already uploaded to the server is not affected. This '
                  'cannot be undone.'
            : 'This permanently deletes the activity and its local GPX '
                  'track from this phone. This cannot be undone.',
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(true),
          child: const Text('Delete'),
        ),
      ],
    ),
  );
  if (confirmed == true) {
    await ref.read(runStoreProvider).deleteRecord(record.clientRunId);
    return true;
  }
  return false;
}
