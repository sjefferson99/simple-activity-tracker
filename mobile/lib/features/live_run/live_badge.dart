import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/sync/live_sharing_store.dart';
import '../../core/sync/live_upload_service.dart';

/// The run screen's live-upload indicator (issue #130 §2.5): the runner
/// always sees whether their route is going up and how many people are
/// allowed to watch it. It can't know whether anyone actually has the live
/// page open. Hidden when live upload can't apply to this run at all (signed
/// out, or a server too old for it).
class LiveBadge extends ConsumerWidget {
  final double fontSize;

  const LiveBadge({super.key, required this.fontSize});

  /// Pure, so the wording is unit-testable without a widget tree. Null hides
  /// the badge.
  static ({String text, bool active})? describe(LiveUploadPhase phase, int watchingCount) =>
      switch (phase) {
        LiveUploadPhase.off => (text: 'Live upload off', active: false),
        LiveUploadPhase.waiting => (text: 'Live · waiting for signal', active: false),
        LiveUploadPhase.upToDate when watchingCount > 0 => (
          text: 'Live · shared with $watchingCount',
          active: true,
        ),
        LiveUploadPhase.upToDate => (text: 'Live · not shared', active: true),
        LiveUploadPhase.idle || LiveUploadPhase.unavailable || LiveUploadPhase.closed => null,
      };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final phase = ref.watch(liveUploadStatusProvider).value?.phase ?? LiveUploadPhase.idle;
    final watching = ref.watch(liveSharingSnapshotProvider).value?.watchingCount ?? 0;
    final badge = describe(phase, watching);
    if (badge == null) return const SizedBox.shrink();

    final scheme = Theme.of(context).colorScheme;
    final color = badge.active ? scheme.primary : scheme.onSurfaceVariant;
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            badge.active ? Icons.sensors : Icons.sensors_off,
            size: fontSize * 1.2,
            color: color,
          ),
          const SizedBox(width: 6),
          Text(badge.text, style: TextStyle(fontSize: fontSize, color: color)),
        ],
      ),
    );
  }
}
