import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/api_client.dart';
import 'package:simple_activity_tracker/core/api/dto/activity_list_item_dto.dart';
import 'package:simple_activity_tracker/core/auth/auth_state.dart';
import 'package:simple_activity_tracker/core/auth/auth_state_controller.dart';
import 'package:simple_activity_tracker/features/activity_history/activity_list_screen.dart';

import '../../fakes/fake_api_client.dart';

class _SignedInAuthController extends AuthStateController {
  @override
  Future<AuthState> build() async =>
      const AuthState(serverUrl: 'https://example.com', token: 't', email: 'runner@example.com');
}

ActivityListItemDto _item(String id) => ActivityListItemDto(
  id: id,
  activityType: 'running',
  startedAt: DateTime.utc(2026, 1, 1),
  endedAt: DateTime.utc(2026, 1, 1, 0, 30),
  title: null,
  distanceMeters: 1000,
  movingSeconds: 300,
  tags: const [],
);

void main() {
  test('loadMore appends the next page and updates the cursor', () async {
    final fake = FakeApiClient()
      ..listActivitiesHandler = ({required baseUrl, required token, cursor, limit = 50}) async {
        if (cursor == null) {
          return ActivityListResponseDto(activities: [_item('a1')], nextCursor: 'page-2');
        }
        expect(cursor, 'page-2');
        return ActivityListResponseDto(activities: [_item('a2')], nextCursor: null);
      };

    final container = ProviderContainer(
      overrides: [
        apiClientProvider.overrideWithValue(fake),
        authStateControllerProvider.overrideWith(_SignedInAuthController.new),
      ],
    );
    addTearDown(container.dispose);

    await container.read(activityListProvider.future);
    await container.read(activityListProvider.notifier).loadMore();

    final page = container.read(activityListProvider).value!;
    expect(page.activities.map((a) => a.id), ['a1', 'a2']);
    expect(page.hasMore, isFalse);
  });

  test('loadMore is a no-op once there is no further page', () async {
    var callCount = 0;
    final fake = FakeApiClient()
      ..listActivitiesHandler = ({required baseUrl, required token, cursor, limit = 50}) async {
        callCount++;
        return ActivityListResponseDto(activities: [_item('a1')], nextCursor: null);
      };

    final container = ProviderContainer(
      overrides: [
        apiClientProvider.overrideWithValue(fake),
        authStateControllerProvider.overrideWith(_SignedInAuthController.new),
      ],
    );
    addTearDown(container.dispose);

    await container.read(activityListProvider.future);
    await container.read(activityListProvider.notifier).loadMore();

    expect(callCount, 1);
  });
}
