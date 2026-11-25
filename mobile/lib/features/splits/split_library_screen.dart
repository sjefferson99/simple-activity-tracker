import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';

import '../../core/api/api_client.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/dto/split_source_dto.dart';
import '../../core/auth/auth_state_controller.dart';
import '../../core/files/run_export_service.dart';

/// Picks a split config file and returns its bytes, or null if the user
/// cancelled. A provider so tests can stand in for the system picker.
final splitFilePickerProvider = Provider<Future<Uint8List?> Function()>(
  (ref) => () async {
    final picked = await FilePicker.pickFiles(
      dialogTitle: 'Choose a split config file',
      type: FileType.custom,
      allowedExtensions: const ['json'],
    );
    if (picked.isEmpty) return null;
    final file = picked.first;
    final length = file.lengthSync() ?? await file.length();
    if (length != null && length > _maxImportBytes) {
      throw const FormatException('That file is too large to be a split config file');
    }
    return file.readAsBytes();
  },
);

const _maxImportBytes = 2 * 1024 * 1024;

/// Saves an export where the user can find it, returning where (for the
/// confirmation), or null if it couldn't be saved. Android: Downloads via
/// MediaStore, same as a run's GPX. Elsewhere: the app's Documents folder,
/// which iOS shows in the Files app.
final splitExportSaverProvider = Provider<Future<String?> Function(String, String)>(
  (ref) => (filename, contents) async {
    final temp = File('${(await getTemporaryDirectory()).path}/$filename');
    await temp.writeAsString(contents);
    try {
      if (Platform.isAndroid) {
        return await RunExportService().exportToPublicStorage(temp);
      }
      final documents = await getApplicationDocumentsDirectory();
      await temp.copy('${documents.path}/$filename');
      return 'Files › Simple Activity Tracker';
    } finally {
      if (await temp.exists()) await temp.delete();
    }
  },
);

final _splitSourcesProvider = FutureProvider.autoDispose<SplitSourceListDto>((ref) async {
  final auth = await ref.watch(authStateControllerProvider.future);
  if (!auth.isSignedIn || !auth.hasServerUrl) {
    return const SplitSourceListDto(sources: []);
  }
  return ref.read(apiClientProvider).listSplitSources(baseUrl: auth.serverUrl!, token: auth.token!);
});

/// The split library (issue #143, docs/SPLIT-LIBRARY-PLAN.md L2): the same
/// controls as the web Library page. Split repos with their folder switches,
/// adding/editing/removing a repo, syncing, and import/export of the user's
/// own configs. Only opened for a server at ApiLevels.splitLibrary or later.
class SplitLibraryScreen extends ConsumerStatefulWidget {
  const SplitLibraryScreen({super.key});

  @override
  ConsumerState<SplitLibraryScreen> createState() => _SplitLibraryScreenState();
}

class _SplitLibraryScreenState extends ConsumerState<SplitLibraryScreen> {
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final sources = ref.watch(_splitSourcesProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Split library')),
      // SafeArea like the other screens, so the last buttons (import and
      // export) aren't hidden behind the system navigation bar.
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () {
            ref.invalidate(_splitSourcesProvider);
            return ref.read(_splitSourcesProvider.future);
          },
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (_busy) const LinearProgressIndicator(),
              Text(
                'Templates come from git repos. Switch a folder on to see its splits when '
                'you load a saved config, or off to hide it. Templates update from their '
                "repo about once a day and can't be edited.",
                style: Theme.of(context).textTheme.bodyMedium,
              ),
              const SizedBox(height: 12),
              ...sources.when(
                loading: () => const [
                  Padding(
                    padding: EdgeInsets.all(24),
                    child: Center(child: CircularProgressIndicator()),
                  ),
                ],
                error: (error, _) => [
                  Text('Could not load split repos: ${_describe(error)}'),
                  TextButton(
                    onPressed: () => ref.invalidate(_splitSourcesProvider),
                    child: const Text('Retry'),
                  ),
                ],
                data: (list) => [
                  if (list.sources.isEmpty) const Text('No split repos yet.'),
                  for (final source in list.sources) _sourceCard(context, source),
                  if (list.canAdd)
                    Align(
                      alignment: Alignment.centerLeft,
                      child: OutlinedButton.icon(
                        onPressed: _busy ? null : () => _addRepo(context),
                        icon: const Icon(Icons.add),
                        label: const Text('Add a split repo'),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 24),
              Text('Import and export', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 4),
              const Text(
                'Export your own split configs to back them up, move them to another server or '
                'share them. Importing a file adds its configs to yours.',
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                children: [
                  OutlinedButton.icon(
                    onPressed: _busy ? null : () => _export(context),
                    icon: const Icon(Icons.upload_file),
                    label: const Text('Export my configs'),
                  ),
                  OutlinedButton.icon(
                    onPressed: _busy ? null : () => _import(context),
                    icon: const Icon(Icons.file_open_outlined),
                    label: const Text('Import a file'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _sourceCard(BuildContext context, SplitSourceDto source) {
    final theme = Theme.of(context);
    final location = [
      source.url,
      source.ref,
      if (source.path.isNotEmpty) '${source.path}/',
      if (source.hasToken) 'private',
    ].join(' · ');
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SwitchListTile(
              key: ValueKey('source-${source.id}'),
              title: Text(source.isDefault ? '${source.name} (default)' : source.name),
              subtitle: Text(location),
              value: source.enabled,
              onChanged: _busy
                  ? null
                  : (on) => _mutate(
                      context,
                      (api, url, token) => api.updateSplitSource(
                        baseUrl: url,
                        token: token,
                        sourceId: source.id,
                        update: SplitSourceUpdateDto(enabled: on),
                      ),
                    ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Text(
                source.lastSyncedAt == null
                    ? 'Not synced yet'
                    : 'Last synced ${MaterialLocalizations.of(context).formatShortDate(source.lastSyncedAt!.toLocal())}',
                style: theme.textTheme.bodySmall,
              ),
            ),
            if (source.lastError != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
                child: Text(
                  'Last sync failed: ${source.lastError}',
                  style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.error),
                ),
              ),
            if (source.warnings.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
                child: Text(
                  '${source.warnings.length} file(s) skipped on the last sync',
                  style: theme.textTheme.bodySmall,
                ),
              ),
            for (final folder in source.folders)
              SwitchListTile(
                key: ValueKey('folder-${folder.id}'),
                dense: true,
                contentPadding: const EdgeInsets.only(left: 32, right: 16),
                title: Text(folder.name),
                subtitle: Text(
                  [
                    '${folder.templateCount} split${folder.templateCount == 1 ? '' : 's'}',
                    ?folder.description,
                  ].join(' · '),
                ),
                value: folder.enabled,
                onChanged: _busy || !source.enabled
                    ? null
                    : (on) => _mutate(
                        context,
                        (api, url, token) => api.setSplitFolderEnabled(
                          baseUrl: url,
                          token: token,
                          sourceId: source.id,
                          folderId: folder.id,
                          enabled: on,
                        ),
                      ),
              ),
            OverflowBar(
              alignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed: _busy ? null : () => _sync(context, source),
                  child: const Text('Sync now'),
                ),
                if (!source.isDefault) ...[
                  TextButton(
                    onPressed: _busy ? null : () => _editRepo(context, source),
                    child: const Text('Edit'),
                  ),
                  TextButton(
                    onPressed: _busy ? null : () => _removeRepo(context, source),
                    child: const Text('Remove'),
                  ),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }

  /// Runs one server call with the signed-in credentials, then reloads the
  /// list. Returns the call's result, or null after showing its error.
  Future<T?> _mutate<T>(
    BuildContext context,
    Future<T> Function(ApiClient api, String baseUrl, String token) call,
  ) async {
    setState(() => _busy = true);
    try {
      final auth = await ref.read(authStateControllerProvider.future);
      if (!auth.isSignedIn || !auth.hasServerUrl) throw StateError('Not signed in');
      final result = await call(ref.read(apiClientProvider), auth.serverUrl!, auth.token!);
      ref.invalidate(_splitSourcesProvider);
      return result;
    } on Object catch (e) {
      if (context.mounted) _snack(context, _describe(e));
      return null;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _sync(BuildContext context, SplitSourceDto source) async {
    final result = await _mutate(
      context,
      (api, url, token) => api.syncSplitSource(baseUrl: url, token: token, sourceId: source.id),
    );
    if (result != null && context.mounted) {
      _snack(
        context,
        result.ok ? '${source.name} synced: ${result.summary}.' : '${source.name}: ${result.error}',
      );
    }
  }

  Future<void> _addRepo(BuildContext context) async {
    final request = await showDialog<SplitSourceCreateDto>(
      context: context,
      builder: (_) => const _AddRepoDialog(),
    );
    if (request == null || !context.mounted) return;
    final result = await _mutate(
      context,
      (api, url, token) => api.addSplitSource(baseUrl: url, token: token, request: request),
    );
    if (result != null && context.mounted) {
      final name = result.source?.name ?? 'Repo';
      _snack(
        context,
        result.ok
            ? '$name added: ${result.summary}.'
            : '$name added, but the sync failed: ${result.error}',
      );
    }
  }

  Future<void> _editRepo(BuildContext context, SplitSourceDto source) async {
    final update = await showDialog<SplitSourceUpdateDto>(
      context: context,
      builder: (_) => _EditRepoDialog(source: source),
    );
    if (update == null || !context.mounted) return;
    await _mutate(
      context,
      (api, url, token) =>
          api.updateSplitSource(baseUrl: url, token: token, sourceId: source.id, update: update),
    );
  }

  Future<void> _removeRepo(BuildContext context, SplitSourceDto source) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Remove ${source.name}?'),
        content: const Text('Its templates go too. Configs you copied from it stay.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (confirmed != true || !context.mounted) return;
    await _mutate(
      context,
      (api, url, token) => api.deleteSplitSource(baseUrl: url, token: token, sourceId: source.id),
    );
  }

  Future<void> _export(BuildContext context) async {
    final contents = await _mutate(
      context,
      (api, url, token) => api.exportSplitConfigs(baseUrl: url, token: token),
    );
    if (contents == null || !context.mounted) return;
    setState(() => _busy = true);
    try {
      final date = DateTime.now().toIso8601String().substring(0, 10);
      final where = await ref.read(splitExportSaverProvider)('split-configs-$date.json', contents);
      if (context.mounted) {
        _snack(context, where == null ? 'Could not save the export file' : 'Exported to $where');
      }
    } on Object catch (e) {
      if (context.mounted) _snack(context, 'Could not save the export file: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _import(BuildContext context) async {
    final Map<String, dynamic> document;
    try {
      final bytes = await ref.read(splitFilePickerProvider)();
      if (bytes == null) return;
      final decoded = jsonDecode(utf8.decode(bytes));
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('not a split config file');
      }
      document = decoded;
    } on Object catch (e) {
      if (context.mounted) {
        _snack(context, "Couldn't read that file: ${e is FormatException ? e.message : e}");
      }
      return;
    }
    if (!context.mounted) return;
    final result = await _mutate(
      context,
      (api, url, token) => api.importSplitConfigs(baseUrl: url, token: token, document: document),
    );
    if (result != null && context.mounted) {
      final extra = [
        if (result.renamed.isNotEmpty) '${result.renamed.length} renamed',
        if (result.errors.isNotEmpty) '${result.errors.length} skipped',
      ];
      _snack(
        context,
        'Imported: ${result.created} new, ${result.updated} replaced'
        '${extra.isEmpty ? '' : ' (${extra.join(', ')})'}.',
      );
    }
  }

  void _snack(BuildContext context, String message) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
}

String _describe(Object error) => switch (error) {
  ApiException(:final message) => message,
  StateError(:final message) => message,
  _ => '$error',
};

class _AddRepoDialog extends StatefulWidget {
  const _AddRepoDialog();

  @override
  State<_AddRepoDialog> createState() => _AddRepoDialogState();
}

class _AddRepoDialogState extends State<_AddRepoDialog> {
  final _url = TextEditingController();
  final _ref = TextEditingController(text: 'main');
  final _path = TextEditingController(text: 'splits');
  final _name = TextEditingController();
  final _token = TextEditingController();
  String? _hostKind;

  @override
  void dispose() {
    for (final c in [_url, _ref, _path, _name, _token]) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Add a split repo'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _url,
              keyboardType: TextInputType.url,
              autocorrect: false,
              decoration: const InputDecoration(
                labelText: 'Repo URL',
                hintText: 'https://github.com/owner/repo',
              ),
            ),
            DropdownButtonFormField<String?>(
              initialValue: _hostKind,
              decoration: const InputDecoration(labelText: 'Host'),
              items: const [
                DropdownMenuItem(value: null, child: Text('Work it out from the URL')),
                DropdownMenuItem(value: 'github', child: Text('GitHub')),
                DropdownMenuItem(value: 'gitlab', child: Text('GitLab')),
                DropdownMenuItem(value: 'gitea', child: Text('Gitea / Forgejo')),
              ],
              onChanged: (value) => setState(() => _hostKind = value),
            ),
            TextField(
              controller: _ref,
              decoration: const InputDecoration(labelText: 'Branch or tag'),
            ),
            TextField(
              controller: _path,
              decoration: const InputDecoration(labelText: 'Folder in repo'),
            ),
            TextField(
              controller: _name,
              decoration: const InputDecoration(labelText: 'Name (optional)'),
            ),
            TextField(
              controller: _token,
              obscureText: true,
              autocorrect: false,
              decoration: const InputDecoration(labelText: 'Access token (private repos)'),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(
          onPressed: () {
            if (_url.text.trim().isEmpty) return;
            Navigator.of(context).pop(
              SplitSourceCreateDto(
                url: _url.text,
                hostKind: _hostKind,
                ref: _ref.text,
                path: _path.text,
                name: _name.text,
                token: _token.text,
              ),
            );
          },
          child: const Text('Add and sync'),
        ),
      ],
    );
  }
}

class _EditRepoDialog extends StatefulWidget {
  final SplitSourceDto source;

  const _EditRepoDialog({required this.source});

  @override
  State<_EditRepoDialog> createState() => _EditRepoDialogState();
}

class _EditRepoDialogState extends State<_EditRepoDialog> {
  late final _name = TextEditingController(text: widget.source.name);
  late final _ref = TextEditingController(text: widget.source.ref);
  late final _path = TextEditingController(text: widget.source.path);
  final _token = TextEditingController();
  bool _clearToken = false;

  @override
  void dispose() {
    for (final c in [_name, _ref, _path, _token]) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text('Edit ${widget.source.name}'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _name,
              decoration: const InputDecoration(labelText: 'Name'),
            ),
            TextField(
              controller: _ref,
              decoration: const InputDecoration(labelText: 'Branch or tag'),
            ),
            TextField(
              controller: _path,
              decoration: const InputDecoration(labelText: 'Folder in repo'),
            ),
            TextField(
              controller: _token,
              obscureText: true,
              autocorrect: false,
              decoration: InputDecoration(
                labelText: 'New access token',
                helperText: widget.source.hasToken ? 'Blank keeps the current one' : null,
              ),
            ),
            if (widget.source.hasToken)
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: _clearToken,
                onChanged: (value) => setState(() => _clearToken = value ?? false),
                title: const Text('Remove the access token'),
              ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(
            SplitSourceUpdateDto(
              name: _name.text.trim().isEmpty ? null : _name.text.trim(),
              ref: _ref.text.trim(),
              path: _path.text.trim(),
              token: _token.text.trim().isEmpty ? null : _token.text.trim(),
              clearToken: _clearToken,
            ),
          ),
          child: const Text('Save'),
        ),
      ],
    );
  }
}
