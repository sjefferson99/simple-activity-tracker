import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/dto/split_config_dto.dart';
import '../../core/auth/auth_state.dart';
import '../../core/auth/auth_state_controller.dart';
import '../../core/tracking/split_plan_controller.dart';
import '../../core/version/api_compat.dart';
import '../../domain/tracking/split_plan.dart';
import '../../domain/tracking/split_preference.dart';
import '../settings/settings_screen.dart';
import 'split_library_screen.dart';

/// The signed-in server credentials a saved-configs call needs, or null when
/// not signed in / no server configured — used by both sections below to
/// decide whether to show their real content or a "sign in" prompt.
class _ServerCreds {
  final String baseUrl;
  final String token;

  const _ServerCreds({required this.baseUrl, required this.token});
}

_ServerCreds? _credsFrom(AsyncValue<AuthState> authState) {
  final auth = authState.value;
  if (auth == null) return null;
  final baseUrl = auth.serverUrl;
  final token = auth.token;
  if (baseUrl == null || token == null) return null;
  return _ServerCreds(baseUrl: baseUrl, token: token);
}

/// Saved split configs arrived in server v1.2.4, which is still API level 0,
/// so the app can't gate on the level — a 404 from the list/save endpoint
/// means "this server is too old", not a failure (docs/VERSIONING.md §3.2).
/// Only for those two calls: a 404 from delete means the config is gone.
String _describeConfigsError(Object error) {
  if (error is ApiRejectedException && error.statusCode == 404) {
    return 'this server is too old for saved configs — update the server to use them.';
  }
  return error is ApiException ? error.message : '$error';
}

/// Fetches the signed-in user's saved split configs fresh every time it's
/// read — never cached locally (docs/SPLIT-CONFIGS-PLAN.md O3), same
/// reasoning as [activityDetailProvider]. `autoDispose` so leaving the
/// screen and coming back re-fetches rather than showing a stale list.
final _savedSplitConfigsProvider =
    FutureProvider.autoDispose<List<SplitConfigDto>>((ref) async {
      final auth = await ref.watch(authStateControllerProvider.future);
      final baseUrl = auth.serverUrl;
      final token = auth.token;
      if (baseUrl == null || token == null) {
        return const [];
      }
      return ref
          .read(apiClientProvider)
          .listSplitConfigs(baseUrl: baseUrl, token: token);
    });

/// Re-fetches the saved split configs list from the server — used by the
/// Splits screen's pull-to-refresh gesture (`RefreshIndicator`) so "reload
/// from server" isn't limited to the small in-section retry icon shown on
/// error. Awaiting the invalidated provider's `.future` lets the
/// RefreshIndicator's spinner stay up for the actual duration of the
/// refetch, not just until the invalidation itself returns.
Future<void> refreshSavedSplitConfigs(WidgetRef ref) {
  ref.invalidate(_savedSplitConfigsProvider);
  ref.invalidate(_serverApiLevelProvider);
  return ref.read(_savedSplitConfigsProvider.future);
}

/// The signed-in server's API level, which decides whether the split
/// library (folders, the Library screen; issue #143) is offered. Level 0
/// when not signed in or it can't be fetched: the section then works
/// exactly as it does against an older server.
final _serverApiLevelProvider = FutureProvider.autoDispose<int>((ref) async {
  final auth = await ref.watch(authStateControllerProvider.future);
  final baseUrl = auth.serverUrl;
  final token = auth.token;
  if (baseUrl == null || token == null) return kLegacyServerApiLevel;
  try {
    return await _serverApiLevel(ref.read(apiClientProvider), baseUrl, token);
  } on ApiException {
    return kLegacyServerApiLevel;
  }
});

bool _hasLibrary(WidgetRef ref) =>
    (ref.watch(_serverApiLevelProvider).value ?? kLegacyServerApiLevel) >=
    ApiLevels.splitLibrary;

/// "Load from saved" and "Save as..." — issue #126. Picking a saved config
/// just copies its plan into the current one (SplitPlanController); nothing
/// remembers which saved config the current plan came from (O5), so this
/// section never re-renders because the current plan changed elsewhere.
class SavedSplitConfigsSection extends ConsumerWidget {
  const SavedSplitConfigsSection({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authStateControllerProvider);
    final creds = _credsFrom(authState);

    final hasLibrary = creds != null && _hasLibrary(ref);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text('Saved configs', style: Theme.of(context).textTheme.titleMedium),
            ),
            if (hasLibrary)
              TextButton.icon(
                onPressed: () async {
                  await Navigator.of(
                    context,
                  ).push(MaterialPageRoute(builder: (_) => const SplitLibraryScreen()));
                  ref.invalidate(_savedSplitConfigsProvider);
                },
                icon: const Icon(Icons.library_books_outlined),
                label: const Text('Library'),
              ),
          ],
        ),
        const SizedBox(height: 8),
        if (creds == null)
          TextButton(
            onPressed: () => Navigator.of(
              context,
            ).push(MaterialPageRoute(builder: (_) => const SettingsScreen())),
            child: const Text('Sign in to load or save split configs'),
          )
        else ...[
          const _LoadFromSavedList(),
          const SizedBox(height: 12),
          const _SaveAsButton(),
        ],
      ],
    );
  }
}

class _LoadFromSavedList extends ConsumerWidget {
  const _LoadFromSavedList();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final configs = ref.watch(_savedSplitConfigsProvider);

    return configs.when(
      loading: () => const Padding(
        padding: EdgeInsets.symmetric(vertical: 8),
        child: LinearProgressIndicator(),
      ),
      error: (error, _) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          children: [
            Expanded(
              child: Text(
                'Could not load saved configs: ${_describeConfigsError(error)}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
            IconButton(
              icon: const Icon(Icons.refresh),
              tooltip: 'Retry',
              onPressed: () => ref.invalidate(_savedSplitConfigsProvider),
            ),
          ],
        ),
      ),
      data: (list) {
        if (list.isEmpty) {
          return const Padding(
            padding: EdgeInsets.symmetric(vertical: 4),
            child: Text(
              'No saved configs yet — build a plan below, then Save as…',
            ),
          );
        }
        final groups = groupSplitConfigs(list);
        // An older server has no folders or templates: the flat list, as before.
        if (groups.length == 1 && groups.single.title == null) {
          return Column(children: [for (final config in list) _tile(context, ref, config)]);
        }
        return Column(
          children: [
            for (final group in groups)
              ExpansionTile(
                key: PageStorageKey('split-group-${group.key}'),
                tilePadding: EdgeInsets.zero,
                childrenPadding: const EdgeInsets.only(left: 8),
                initiallyExpanded: !group.isTemplate,
                title: Text(group.title ?? 'My splits'),
                subtitle: Text(
                  [
                    '${group.configs.length} config${group.configs.length == 1 ? '' : 's'}',
                    if (group.sourceName != null) 'templates from ${group.sourceName}',
                  ].join(' · '),
                ),
                children: [for (final config in group.configs) _tile(context, ref, config)],
              ),
          ],
        );
      },
    );
  }

  Widget _tile(BuildContext context, WidgetRef ref, SplitConfigDto config) => ListTile(
    contentPadding: EdgeInsets.zero,
    dense: true,
    title: Text(config.name),
    subtitle: Text(
      config.readOnly ? 'Template · ${_summarize(config.plan)}' : _summarize(config.plan),
    ),
    trailing: const Icon(Icons.download_outlined),
    onTap: () async {
      await ref.read(splitPlanControllerProvider.notifier).select(config.plan);
      if (context.mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Loaded "${config.name}"')));
      }
    },
  );

  String _summarize(SplitPlan plan) {
    if (plan.isCustom) {
      final count = plan.customSplits.length;
      return 'Custom, $count split${count == 1 ? '' : 's'}';
    }
    final unit = switch (plan.base.kind) {
      SplitKind.distanceKm => 'km',
      SplitKind.distanceMi => 'mi',
      SplitKind.timeMin => 'min',
    };
    return 'Rolling, every ${plan.base.value} $unit'
        '${plan.rollingTargetSpeedMps != null ? ' with a target' : ''}';
  }
}

/// One group in the saved-config picker (issue #143).
class SplitConfigGroup {
  /// Null for the user's own configs that aren't in a folder.
  final String? title;
  final String? sourceName;
  final List<SplitConfigDto> configs;

  const SplitConfigGroup({required this.title, required this.configs, this.sourceName});

  bool get isTemplate => sourceName != null;

  String get key => '${sourceName ?? ''}/${title ?? ''}';
}

/// Own configs first (unfiled, then by folder), then templates by repo and
/// folder, each in natural order ("week 2" before "week 10"). A list with
/// no folders or templates (an older server) is one untitled group.
List<SplitConfigGroup> groupSplitConfigs(List<SplitConfigDto> configs) {
  final own = <String?, List<SplitConfigDto>>{};
  final templates = <(String, String), List<SplitConfigDto>>{};
  for (final config in configs) {
    if (config.readOnly) {
      final key = (config.sourceName ?? 'Templates', config.folderName ?? 'General');
      templates.putIfAbsent(key, () => []).add(config);
    } else {
      own.putIfAbsent(config.folderName, () => []).add(config);
    }
  }
  int byName(SplitConfigDto a, SplitConfigDto b) => naturalCompare(a.name, b.name);
  final groups = <SplitConfigGroup>[
    if (own.containsKey(null)) SplitConfigGroup(title: null, configs: own[null]!..sort(byName)),
    for (final folder in own.keys.whereType<String>().toList()..sort(naturalCompare))
      SplitConfigGroup(title: folder, configs: own[folder]!..sort(byName)),
    for (final key in templates.keys.toList()
      ..sort((a, b) {
        final bySource = naturalCompare(a.$1, b.$1);
        return bySource != 0 ? bySource : naturalCompare(a.$2, b.$2);
      }))
      SplitConfigGroup(
        title: key.$2,
        sourceName: key.$1,
        configs: templates[key]!..sort(byName),
      ),
  ];
  return groups;
}

/// Case-insensitive, with runs of digits compared as numbers.
int naturalCompare(String a, String b) {
  final pattern = RegExp(r'\d+|\D+');
  final left = pattern.allMatches(a.toLowerCase()).map((m) => m[0]!).toList();
  final right = pattern.allMatches(b.toLowerCase()).map((m) => m[0]!).toList();
  for (var i = 0; i < left.length && i < right.length; i++) {
    final l = int.tryParse(left[i]);
    final r = int.tryParse(right[i]);
    final order = l != null && r != null ? l.compareTo(r) : left[i].compareTo(right[i]);
    if (order != 0) return order;
  }
  return left.length.compareTo(right.length);
}

/// The server's API level, decided per save (issue #233). If it can't be
/// fetched, assume level 0 and send the flat plan every server accepts.
Future<int> _serverApiLevel(ApiClient api, String baseUrl, String token) async {
  try {
    final info = await api.getServerInfo(baseUrl: baseUrl, token: token);
    return info.apiLevel;
  } on ApiUnauthorizedException {
    rethrow;
  } on ApiException {
    return kLegacyServerApiLevel;
  }
}

class _SaveAsButton extends ConsumerStatefulWidget {
  const _SaveAsButton();

  @override
  ConsumerState<_SaveAsButton> createState() => _SaveAsButtonState();
}

class _SaveAsButtonState extends ConsumerState<_SaveAsButton> {
  bool _saving = false;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: _saving ? null : () => _promptAndSave(context),
      icon: const Icon(Icons.save_outlined),
      label: const Text('Save as…'),
    );
  }

  Future<void> _promptAndSave(BuildContext context) async {
    final withFolder = _hasLibrary(ref);
    final answer = await _promptForName(context, withFolder: withFolder);
    if (answer == null || answer.name.trim().isEmpty) return;
    if (!context.mounted) return;
    await _save(context, answer.name.trim(), overwrite: false, folder: answer.folder);
  }

  /// The name, and the folder when the server has folders (issue #143):
  /// null there means "don't send one" (an older server), blank "none".
  Future<({String name, String? folder})?> _promptForName(
    BuildContext context, {
    required bool withFolder,
  }) {
    final name = TextEditingController();
    final folder = TextEditingController();
    ({String name, String? folder}) answer() =>
        (name: name.text, folder: withFolder ? folder.text : null);
    return showDialog<({String name, String? folder})>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Save split config as'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: name,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Name'),
              onSubmitted: (_) => Navigator.of(context).pop(answer()),
            ),
            if (withFolder)
              TextField(
                controller: folder,
                decoration: const InputDecoration(labelText: 'Folder (optional)'),
                onSubmitted: (_) => Navigator.of(context).pop(answer()),
              ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(answer()),
            child: const Text('Save'),
          ),
        ],
      ),
    );
  }

  Future<void> _save(
    BuildContext context,
    String name, {
    required bool overwrite,
    String? folder,
  }) async {
    setState(() => _saving = true);
    try {
      final auth = await ref.read(authStateControllerProvider.future);
      final baseUrl = auth.serverUrl;
      final token = auth.token;
      if (baseUrl == null || token == null) {
        throw StateError('Not signed in');
      }
      final plan = ref.read(splitPlanControllerProvider);
      final api = ref.read(apiClientProvider);
      final request = SplitConfigSaveRequestDto(
        name: name,
        plan: plan,
        overwrite: overwrite,
        // A folder only ever comes from a dialog that knew the server has
        // the library, so that level stands in for asking again.
        serverApiLevel: folder != null
            ? ApiLevels.splitLibrary
            : plan.hasRepeatBlocks
            ? await _serverApiLevel(api, baseUrl, token)
            : kLegacyServerApiLevel,
        folder: folder,
      );
      await api.saveSplitConfig(
        baseUrl: baseUrl,
        token: token,
        request: request,
      );
      ref.invalidate(_savedSplitConfigsProvider);
      if (context.mounted) {
        // An older server keeps the splits but not how they're grouped.
        final note = plan.hasRepeatBlocks && !request.sendsLayout
            ? ' (without its repeat groups: this server is too old to store them)'
            : '';
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Saved "$name"$note')));
      }
    } on ApiRejectedException catch (e) {
      if (e.statusCode == 409 && context.mounted) {
        final replace = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Config already exists'),
            content: Text(
              'A split config named "$name" already exists. Replace it?',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(context).pop(false),
                child: const Text('Cancel'),
              ),
              FilledButton(
                onPressed: () => Navigator.of(context).pop(true),
                child: const Text('Replace'),
              ),
            ],
          ),
        );
        if (replace == true && context.mounted) {
          await _save(context, name, overwrite: true, folder: folder);
          return;
        }
      } else if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Could not save: ${_describeConfigsError(e)}'),
          ),
        );
      }
    } on Object catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Could not save: ${e is ApiException ? e.message : e}',
            ),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }
}
