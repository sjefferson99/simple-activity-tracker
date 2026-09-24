import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/dto/server_info_dto.dart';
import '../../core/auth/auth_state_controller.dart';
import '../../core/version/api_compat.dart';
import '../../core/version/app_version.dart';

/// The signed-in server's version and API level, or null when not signed in
/// (docs/VERSIONING.md §4). Fetched fresh each time Settings opens.
final serverInfoProvider = FutureProvider.autoDispose<ServerInfoDto?>((ref) async {
  final auth = await ref.watch(authStateControllerProvider.future);
  if (!auth.isSignedIn || !auth.hasServerUrl) return null;
  return ref
      .read(apiClientProvider)
      .getServerInfo(baseUrl: auth.serverUrl!, token: auth.token!);
});

/// A line under the versions: a warning when uploads are paused, a neutral
/// note otherwise, or null when there's nothing worth saying.
typedef CompatibilityNote = ({String message, bool isWarning});

/// docs/VERSIONING.md §4's table. Pure, so it's unit-testable.
CompatibilityNote? compatibilityNote(AppVersion app, ServerInfoDto server) {
  switch (server.compatibility) {
    case ServerCompatibility.appTooOld:
      return (
        message: 'This app is too old for the server. Update the app — uploads are '
            'paused until then.',
        isWarning: true,
      );
    case ServerCompatibility.serverTooOld:
      return (
        message: 'The server is too old for this app. Update the server — uploads '
            'are paused until then.',
        isWarning: true,
      );
    case ServerCompatibility.compatible:
      break;
  }
  if (server.isLegacy) {
    return (
      message: 'This server predates version reporting. Everything uploads, but '
          'some newer features need the server to be updated.',
      isWarning: false,
    );
  }
  // Compare release versions only — "1.3.0+4.gabc1234" is a main build past
  // 1.3.0, and a dev build of either side has nothing meaningful to compare.
  final serverRelease = server.version!.split('+').first;
  if (app.isDevBuild || serverRelease == 'dev' || serverRelease == app.version) {
    return null;
  }
  return (message: 'Matching versions are recommended.', isWarning: false);
}

class AboutSection extends ConsumerWidget {
  const AboutSection({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final appVersion = ref.watch(appVersionProvider);
    final serverInfo = ref.watch(serverInfoProvider);
    final theme = Theme.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('About', style: theme.textTheme.titleMedium),
        const SizedBox(height: 8),
        _VersionRow(
          label: 'App',
          value: appVersion.when(
            data: (version) => '${version.display} · API level $kAppApiLevel',
            loading: () => '…',
            error: (_, _) => 'unknown · API level $kAppApiLevel',
          ),
        ),
        ...serverInfo.when(
          data: (info) => info == null
              ? const <Widget>[]
              : [
                  _VersionRow(
                    label: 'Server',
                    value: info.isLegacy
                        ? 'v1.2.4 or older'
                        : '${info.version} · API level ${info.apiLevel}',
                  ),
                  if (appVersion.value case final app?)
                    if (compatibilityNote(app, info) case final note?)
                      _NoteLine(note: note),
                ],
          loading: () => const [_VersionRow(label: 'Server', value: 'checking…')],
          error: (error, _) => [
            Row(
              children: [
                Expanded(
                  child: _VersionRow(
                    label: 'Server',
                    value:
                        "couldn't check (${error is ApiException ? error.message : error})",
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.refresh),
                  tooltip: 'Check again',
                  onPressed: () => ref.invalidate(serverInfoProvider),
                ),
              ],
            ),
          ],
        ),
      ],
    );
  }
}

class _VersionRow extends StatelessWidget {
  final String label;
  final String value;

  const _VersionRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 64, child: Text(label, style: Theme.of(context).textTheme.bodySmall)),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}

class _NoteLine extends StatelessWidget {
  final CompatibilityNote note;

  const _NoteLine({required this.note});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            note.isWarning ? Icons.warning_amber : Icons.info_outline,
            color: note.isWarning ? scheme.error : scheme.onSurfaceVariant,
            size: 18,
          ),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              note.message,
              style: TextStyle(
                fontSize: 12,
                color: note.isWarning ? scheme.error : scheme.onSurfaceVariant,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
