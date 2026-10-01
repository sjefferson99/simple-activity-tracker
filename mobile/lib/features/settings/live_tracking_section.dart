import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/auth/auth_state_controller.dart';
import '../../core/sync/live_upload_settings.dart';
import 'live_sharing_controller.dart';

/// Settings → Live tracking (issue #130 D3/D4): the Live upload switch, and
/// who can watch live. Every change applies at once, mid-run included.
class LiveTrackingSection extends ConsumerStatefulWidget {
  const LiveTrackingSection({super.key});

  @override
  ConsumerState<LiveTrackingSection> createState() => _LiveTrackingSectionState();
}

class _LiveTrackingSectionState extends ConsumerState<LiveTrackingSection> {
  /// A rejected change, shown next to the controls rather than replacing
  /// them (CLAUDE.md: never route a user-input error into the provider).
  String? _changeError;

  Future<void> _apply(Future<void> Function() change) async {
    setState(() => _changeError = null);
    try {
      await change();
    } on ApiException catch (e) {
      if (mounted) setState(() => _changeError = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant);
    final uploadEnabled = ref.watch(liveUploadEnabledProvider);
    final signedIn = ref.watch(authStateControllerProvider).value?.isSignedIn ?? false;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Live tracking', style: theme.textTheme.titleMedium),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('Live upload'),
          subtitle: const Text(
            'While you record, upload your route about once a minute: a backup if '
            'your phone dies, and how people you share with can follow along. '
            'Turn off to save mobile data.',
          ),
          value: uploadEnabled,
          onChanged: (value) => ref.read(liveUploadEnabledProvider.notifier).set(value),
        ),
        if (!signedIn)
          Text('Sign in to a server to use live upload and sharing.', style: muted)
        else
          _LiveSharingControls(
            uploadEnabled: uploadEnabled,
            onChange: _apply,
            changeError: _changeError,
          ),
      ],
    );
  }
}

class _LiveSharingControls extends ConsumerWidget {
  final bool uploadEnabled;
  final Future<void> Function(Future<void> Function()) onChange;
  final String? changeError;

  const _LiveSharingControls({
    required this.uploadEnabled,
    required this.onChange,
    required this.changeError,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final muted = theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant);
    final sharing = ref.watch(liveSharingControllerProvider);
    final controller = ref.read(liveSharingControllerProvider.notifier);

    return sharing.when(
      loading: () => const Padding(
        padding: EdgeInsets.all(8),
        child: Center(child: CircularProgressIndicator()),
      ),
      error: (error, _) => Row(
        children: [
          Expanded(
            child: Text(
              "Couldn't load live sharing: ${error is ApiException ? error.message : error}",
              style: muted,
            ),
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: 'Try again',
            onPressed: () => ref.invalidate(liveSharingControllerProvider),
          ),
        ],
      ),
      data: (view) {
        if (view == null) return const SizedBox.shrink();
        if (view.unsupported) {
          return Text(
            'Live upload and sharing need a newer server. Update the server to use them.',
            style: muted,
          );
        }
        final snapshot = view.snapshot;
        final users = snapshot.users.entries.toList()
          ..sort((a, b) => a.value.toLowerCase().compareTo(b.value.toLowerCase()));
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (!uploadEnabled)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text('Live sharing needs Live upload on.', style: muted),
              ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text("Don't live share"),
              subtitle: Text(
                snapshot.paused
                    ? 'Nobody can watch you live. Your list below is kept.'
                    : 'Turn on to stop everyone watching, without changing your list.',
              ),
              value: snapshot.paused,
              onChanged: uploadEnabled
                  ? (paused) => onChange(() => controller.setPaused(paused))
                  : null,
            ),
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text('Live share with', style: theme.textTheme.titleSmall),
            ),
            if (users.isEmpty)
              Text('There are no other users on this server yet.', style: muted),
            for (final user in users)
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                title: Text(user.value),
                value: snapshot.liveViewerIds.contains(user.key),
                onChanged: uploadEnabled
                    ? (on) => onChange(() => controller.setViewer(user.key, on ?? false))
                    : null,
              ),
            Text(
              'History sharing, and sharing a single activity, are on the web app.',
              style: muted,
            ),
            if (view.offline)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text("Offline: showing your last known settings.", style: muted),
              ),
            if (view.pendingSync)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  "Saved on this phone. It reaches the server as soon as you're "
                  'back online, before any more of your route does.',
                  style: muted,
                ),
              ),
            if (changeError != null)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  changeError!,
                  style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.error),
                ),
              ),
          ],
        );
      },
    );
  }
}
