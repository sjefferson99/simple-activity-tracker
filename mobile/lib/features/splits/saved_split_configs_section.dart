import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/dto/split_config_dto.dart';
import '../../core/auth/auth_state.dart';
import '../../core/auth/auth_state_controller.dart';
import '../../core/tracking/split_plan_controller.dart';
import '../../domain/tracking/split_plan.dart';
import '../../domain/tracking/split_preference.dart';
import '../settings/settings_screen.dart';

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
  return ref.read(_savedSplitConfigsProvider.future);
}

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

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Saved configs', style: Theme.of(context).textTheme.titleMedium),
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
        return Column(
          children: [
            for (final config in list)
              ListTile(
                contentPadding: EdgeInsets.zero,
                dense: true,
                title: Text(config.name),
                subtitle: Text(_summarize(config.plan)),
                trailing: const Icon(Icons.download_outlined),
                onTap: () async {
                  await ref
                      .read(splitPlanControllerProvider.notifier)
                      .select(config.plan);
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('Loaded "${config.name}"')),
                    );
                  }
                },
              ),
          ],
        );
      },
    );
  }

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
    final name = await _promptForName(context, initialValue: '');
    if (name == null || name.trim().isEmpty) return;
    if (!context.mounted) return;
    await _save(context, name.trim(), overwrite: false);
  }

  Future<String?> _promptForName(
    BuildContext context, {
    required String initialValue,
  }) {
    final controller = TextEditingController(text: initialValue);
    return showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Save split config as'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Name'),
          onSubmitted: (value) => Navigator.of(context).pop(value),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(controller.text),
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
      await ref
          .read(apiClientProvider)
          .saveSplitConfig(
            baseUrl: baseUrl,
            token: token,
            request: SplitConfigSaveRequestDto(
              name: name,
              plan: plan,
              overwrite: overwrite,
            ),
          );
      ref.invalidate(_savedSplitConfigsProvider);
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Saved "$name"')));
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
          await _save(context, name, overwrite: true);
          return;
        }
      } else if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not save: ${_describeConfigsError(e)}')),
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
