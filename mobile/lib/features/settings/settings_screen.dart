import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/api/api_exception.dart';
import '../../core/auth/auth_state.dart';
import '../../core/auth/auth_state_controller.dart';
import '../../core/sync/file_run_store.dart';
import '../../core/sync/sync_service.dart';
import '../../domain/models/run_record.dart';
import '../../domain/models/sync_status.dart';

/// Re-fetches the run queue on every SyncService status change, so the
/// summary below stays live while a pass is running — a StreamProvider
/// rather than polling, matching the "service stream → state" convention.
final _syncQueueProvider = StreamProvider<List<RunRecord>>((ref) async* {
  final runStore = ref.read(runStoreProvider);
  final syncService = ref.read(syncServiceProvider);
  yield await runStore.listAll();
  await for (final _ in syncService.statusChanges) {
    yield await runStore.listAll();
  }
});

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authStateControllerProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            authState.when(
              data: (state) => _AuthSection(state: state),
              loading: () => const Center(
                child: Padding(
                  padding: EdgeInsets.all(24),
                  child: CircularProgressIndicator(),
                ),
              ),
              error: (error, _) => _ErrorBanner(message: _messageFor(error)),
            ),
            const SizedBox(height: 24),
            const Divider(),
            const SizedBox(height: 16),
            const _SyncQueueSection(),
          ],
        ),
      ),
    );
  }

  static String _messageFor(Object error) =>
      error is ApiException ? error.message : error.toString();
}

class _ErrorBanner extends StatelessWidget {
  final String message;

  const _ErrorBanner({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.errorContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        message,
        style: TextStyle(color: Theme.of(context).colorScheme.onErrorContainer),
      ),
    );
  }
}

class _AuthSection extends ConsumerStatefulWidget {
  final AuthState state;

  const _AuthSection({required this.state});

  @override
  ConsumerState<_AuthSection> createState() => _AuthSectionState();
}

class _AuthSectionState extends ConsumerState<_AuthSection> {
  late final _serverUrlController = TextEditingController(
    text: widget.state.serverUrl ?? '',
  );
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _deviceNameController = TextEditingController();

  @override
  void dispose() {
    _serverUrlController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    _deviceNameController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Server', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        TextField(
          controller: _serverUrlController,
          decoration: const InputDecoration(
            labelText: 'Server URL',
            hintText: 'https://runner.example.com',
          ),
          keyboardType: TextInputType.url,
          enabled: !state.isSignedIn,
        ),
        if (state.isCleartext) ...[
          const SizedBox(height: 8),
          Row(
            children: [
              Icon(
                Icons.warning_amber,
                color: Theme.of(context).colorScheme.error,
                size: 18,
              ),
              const SizedBox(width: 6),
              const Expanded(
                child: Text(
                  'This is an unencrypted connection. Fine on a trusted LAN; use https:// '
                  'for anything else.',
                  style: TextStyle(fontSize: 12),
                ),
              ),
            ],
          ),
        ],
        const SizedBox(height: 16),
        if (state.isSignedIn)
          _SignedInView(email: state.email)
        else
          _SignInForm(
            serverUrlController: _serverUrlController,
            emailController: _emailController,
            passwordController: _passwordController,
            deviceNameController: _deviceNameController,
          ),
      ],
    );
  }
}

class _SignedInView extends ConsumerWidget {
  final String? email;

  const _SignedInView({required this.email});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Expanded(child: Text('Signed in as ${email ?? 'unknown'}')),
        OutlinedButton(
          onPressed: () =>
              ref.read(authStateControllerProvider.notifier).signOut(),
          child: const Text('Sign out'),
        ),
      ],
    );
  }
}

class _SignInForm extends ConsumerStatefulWidget {
  final TextEditingController serverUrlController;
  final TextEditingController emailController;
  final TextEditingController passwordController;
  final TextEditingController deviceNameController;

  const _SignInForm({
    required this.serverUrlController,
    required this.emailController,
    required this.passwordController,
    required this.deviceNameController,
  });

  @override
  ConsumerState<_SignInForm> createState() => _SignInFormState();
}

class _SignInFormState extends ConsumerState<_SignInForm> {
  bool _submitting = false;
  String? _error;

  Future<void> _submit() async {
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      await ref
          .read(authStateControllerProvider.notifier)
          .setServerUrl(widget.serverUrlController.text.trim());
      await _signIn();
    } on Object catch (e) {
      // Deliberately caught here, not routed through authStateControllerProvider's
      // state — an AsyncError there would replace this whole form (and the
      // server URL/email the user just typed) with a bare error message.
      if (mounted) {
        setState(() => _error = e is ApiException ? e.message : e.toString());
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _signIn() async {
    try {
      await ref
          .read(authStateControllerProvider.notifier)
          .signIn(
            email: widget.emailController.text.trim(),
            password: widget.passwordController.text,
            deviceName: widget.deviceNameController.text.trim(),
          );
    } on ApiCertificateException catch (e) {
      final trusted = mounted ? await _confirmCertificateTrust(e) : false;
      if (!trusted) rethrow;
      // The dialog already wrote the pin to CertTrustStore — retry once,
      // now that the handshake will succeed.
      await ref
          .read(authStateControllerProvider.notifier)
          .signIn(
            email: widget.emailController.text.trim(),
            password: widget.passwordController.text,
            deviceName: widget.deviceNameController.text.trim(),
          );
    }
  }

  /// Trust-on-first-use: shows the presented certificate's fingerprint and
  /// asks the user to confirm it out of band (e.g. against what
  /// generate-cert.sh printed) before pinning it in CertTrustStore. Returns
  /// whether the user confirmed.
  Future<bool> _confirmCertificateTrust(ApiCertificateException e) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text("Can't verify this server's identity"),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(e.message),
            const SizedBox(height: 16),
            const Text(
              'Certificate fingerprint (SHA-256):',
              style: TextStyle(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 4),
            SelectableText(
              e.fingerprint,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            ),
            const SizedBox(height: 12),
            const Text(
              'Compare this to the fingerprint shown when the certificate was generated, '
              'or in a browser\'s certificate viewer for this server. Only trust it if it matches.',
              style: TextStyle(fontSize: 12),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Trust this certificate'),
          ),
        ],
      ),
    );
    if (confirmed != true) return false;
    await ref.read(certTrustStoreProvider).trust(e.host, e.fingerprint);
    return true;
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (_error != null) ...[
          _ErrorBanner(message: _error!),
          const SizedBox(height: 8),
        ],
        TextField(
          controller: widget.emailController,
          decoration: const InputDecoration(labelText: 'Email'),
          keyboardType: TextInputType.emailAddress,
        ),
        const SizedBox(height: 8),
        TextField(
          controller: widget.passwordController,
          decoration: const InputDecoration(labelText: 'Password'),
          obscureText: true,
        ),
        const SizedBox(height: 8),
        TextField(
          controller: widget.deviceNameController,
          decoration: const InputDecoration(
            labelText: 'Device name',
            hintText: 'e.g. My Phone',
          ),
        ),
        const SizedBox(height: 12),
        FilledButton(
          onPressed: _submitting ? null : _submit,
          child: _submitting
              ? const SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Sign in'),
        ),
      ],
    );
  }
}

class _SyncQueueSection extends ConsumerWidget {
  const _SyncQueueSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final queue = ref.watch(_syncQueueProvider);
    final failedCount = queue.value
            ?.where((r) => r.syncStatus is SyncStatusFailed)
            .length ??
        0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Sync queue', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        queue.when(
          data: (records) => _QueueSummary(records: records),
          loading: () => const LinearProgressIndicator(),
          error: (error, _) => Text('$error'),
        ),
        const SizedBox(height: 12),
        Row(
          children: [
            OutlinedButton(
              onPressed: () => ref.read(syncServiceProvider).retryNow(),
              child: const Text('Retry now'),
            ),
            if (failedCount > 0) ...[
              const SizedBox(width: 12),
              OutlinedButton(
                onPressed: () => _confirmAndClear(context, ref, failedCount),
                child: const Text('Clear failed'),
              ),
            ],
          ],
        ),
      ],
    );
  }

  /// Discarding a failed record deletes its local GPX/sidecar for good — the
  /// activity's data doesn't exist anywhere else, so confirm before doing it.
  Future<void> _confirmAndClear(
    BuildContext context,
    WidgetRef ref,
    int failedCount,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Clear failed activities?'),
        content: Text(
          'This permanently deletes the $failedCount failed '
          '${failedCount == 1 ? 'activity' : 'activities'} in the queue, '
          'including its local GPX track. This cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Clear'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await ref.read(runStoreProvider).clearFailed();
      // clearFailed() doesn't go through SyncService, so _syncQueueProvider's
      // statusChanges trigger never fires for it — force a re-read.
      ref.invalidate(_syncQueueProvider);
    }
  }
}

class _QueueSummary extends StatelessWidget {
  final List<RunRecord> records;

  const _QueueSummary({required this.records});

  @override
  Widget build(BuildContext context) {
    if (records.isEmpty) {
      return const Text('No activities recorded yet.');
    }

    var pending = 0;
    var uploading = 0;
    var uploaded = 0;
    var failed = 0;
    for (final record in records) {
      switch (record.syncStatus) {
        case SyncStatusPending():
          pending++;
        case SyncStatusUploading():
          uploading++;
        case SyncStatusUploaded():
          uploaded++;
        case SyncStatusFailed():
          failed++;
      }
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '$uploaded uploaded, $pending queued, $failed failed'
          '${uploading > 0 ? ', $uploading uploading' : ''}',
        ),
        if (failed > 0) ...[
          const SizedBox(height: 8),
          ...records
              .whereType<RunRecord>()
              .where((r) => r.syncStatus is SyncStatusFailed)
              .map(
                (r) => Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    '• ${(r.syncStatus as SyncStatusFailed).error}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
              ),
        ],
      ],
    );
  }
}
