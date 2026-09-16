import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/api/dto/activity_list_item_dto.dart';
import '../../core/auth/auth_state_controller.dart';
import '../../core/units/units.dart';
import '../settings/settings_screen.dart';
import 'activity_detail_screen.dart';

/// One page of the server's activity list, loaded so far — cursor-based per
/// the API (issue #101, D2: no page-number UI like the web app's richer
/// #75/#76 list, which this endpoint doesn't support). Deliberately not
/// cached beyond this Notifier's own lifetime (D3) — a fresh screen open
/// always starts from page one.
class ActivityListPage {
  final List<ActivityListItemDto> activities;
  final String? nextCursor;
  final bool isLoadingMore;

  const ActivityListPage({
    required this.activities,
    required this.nextCursor,
    this.isLoadingMore = false,
  });

  bool get hasMore => nextCursor != null;

  ActivityListPage copyWith({
    List<ActivityListItemDto>? activities,
    String? nextCursor,
    bool clearNextCursor = false,
    bool? isLoadingMore,
  }) => ActivityListPage(
    activities: activities ?? this.activities,
    nextCursor: clearNextCursor ? null : (nextCursor ?? this.nextCursor),
    isLoadingMore: isLoadingMore ?? this.isLoadingMore,
  );
}

final activityListProvider = AsyncNotifierProvider<ActivityListController, ActivityListPage>(
  ActivityListController.new,
);

class ActivityListController extends AsyncNotifier<ActivityListPage> {
  @override
  Future<ActivityListPage> build() => _fetchFirstPage();

  Future<ActivityListPage> _fetchFirstPage() async {
    final auth = await ref.watch(authStateControllerProvider.future);
    final baseUrl = auth.serverUrl;
    final token = auth.token;
    if (baseUrl == null || token == null) {
      throw StateError('Not signed in');
    }
    final response = await ref.read(apiClientProvider).listActivities(
          baseUrl: baseUrl,
          token: token,
        );
    return ActivityListPage(
      activities: response.activities,
      nextCursor: response.nextCursor,
    );
  }

  /// Appends the next page. A no-op if there is no further page or a load
  /// is already in flight — guards against a double-tap/double-scroll
  /// triggering two concurrent requests for the same page.
  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || !current.hasMore || current.isLoadingMore) return;

    state = AsyncData(current.copyWith(isLoadingMore: true));
    try {
      final auth = await ref.read(authStateControllerProvider.future);
      final baseUrl = auth.serverUrl;
      final token = auth.token;
      if (baseUrl == null || token == null) {
        state = AsyncData(current.copyWith(isLoadingMore: false));
        return;
      }

      final response = await ref.read(apiClientProvider).listActivities(
            baseUrl: baseUrl,
            token: token,
            cursor: current.nextCursor,
          );
      state = AsyncData(
        current.copyWith(
          activities: [...current.activities, ...response.activities],
          nextCursor: response.nextCursor,
          clearNextCursor: response.nextCursor == null,
          isLoadingMore: false,
        ),
      );
    } on Object {
      // A failed page-2+ fetch must not strand isLoadingMore at true — that
      // would permanently block every further scroll-triggered load (the
      // no-op guard above checks exactly this flag) and spin the
      // bottom-of-list indicator forever with no way to recover short of
      // pull-to-refresh, which isn't discoverable from a stuck spinner.
      // Falls back to the already-loaded first page rather than losing it.
      state = AsyncData(current.copyWith(isLoadingMore: false));
    }
  }

  Future<void> refresh() async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(_fetchFirstPage);
  }
}

/// The server-backed activity list (issue #101) — every activity on the
/// server for the signed-in user, regardless of which device recorded it.
/// Deliberately separate from Settings' local pending/failed/uploaded list
/// (`_SyncQueueSection`), which manages only runs recorded on this device
/// and is unaffected by this screen.
class ActivityListScreen extends ConsumerWidget {
  const ActivityListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authStateControllerProvider);
    final isSignedIn = auth.value?.isSignedIn ?? false;

    return Scaffold(
      appBar: AppBar(title: const Text('Activity history')),
      body: !isSignedIn
          ? _SignedOutState()
          : RefreshIndicator(
              onRefresh: () => ref.read(activityListProvider.notifier).refresh(),
              child: _ActivityListBody(),
            ),
    );
  }
}

class _SignedOutState extends StatelessWidget {
  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Text('Sign in to see your activity history'),
        const SizedBox(height: 12),
        TextButton(
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute(builder: (_) => const SettingsScreen()),
          ),
          child: const Text('Sign in'),
        ),
      ],
    ),
  );
}

class _ActivityListBody extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final page = ref.watch(activityListProvider);

    return page.when(
      data: (data) {
        if (data.activities.isEmpty) {
          return const Center(child: Text('No activities yet'));
        }
        return NotificationListener<ScrollNotification>(
          onNotification: (notification) {
            if (notification.metrics.pixels >=
                notification.metrics.maxScrollExtent - 200) {
              ref.read(activityListProvider.notifier).loadMore();
            }
            return false;
          },
          child: ListView.builder(
            itemCount: data.activities.length + (data.hasMore ? 1 : 0),
            itemBuilder: (context, index) {
              if (index >= data.activities.length) {
                return const Padding(
                  padding: EdgeInsets.all(16),
                  child: Center(child: CircularProgressIndicator()),
                );
              }
              return _ActivityListTile(item: data.activities[index]);
            },
          ),
        );
      },
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (error, _) => Center(child: Text('Could not load activities: $error')),
    );
  }
}

class _ActivityListTile extends StatelessWidget {
  final ActivityListItemDto item;

  const _ActivityListTile({required this.item});

  @override
  Widget build(BuildContext context) {
    final dateText = formatActivityDate(item.startedAt.toLocal());
    // The date always shows, even when a title is set — otherwise a named
    // activity would show no date at all, making two same-named activities
    // (or just "which day was this?") impossible to tell apart in the list.
    final title = item.title ?? dateText;
    final subtitle =
        '${item.title != null ? '$dateText · ' : ''}'
        '${formatDistanceKm(item.distanceMeters)} km · '
        '${formatDuration(Duration(seconds: item.movingSeconds.round()))}';

    return ListTile(
      title: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text(subtitle),
      trailing: item.tags.isNotEmpty
          ? Icon(Icons.label_outline, size: 18, color: Theme.of(context).colorScheme.onSurfaceVariant)
          : null,
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => ActivityDetailScreen(activityId: item.id)),
      ),
    );
  }
}
