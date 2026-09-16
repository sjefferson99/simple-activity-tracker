import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/api_client.dart';
import 'package:simple_activity_tracker/core/api/dto/activity_list_item_dto.dart';
import 'package:simple_activity_tracker/core/auth/auth_state.dart';
import 'package:simple_activity_tracker/core/auth/auth_state_controller.dart';
import 'package:simple_activity_tracker/features/activity_history/activity_detail_screen.dart';
import 'package:simple_activity_tracker/features/activity_history/activity_list_screen.dart';

import '../../fakes/fake_api_client.dart';

class _SignedInAuthController extends AuthStateController {
  @override
  Future<AuthState> build() async =>
      const AuthState(serverUrl: 'https://example.com', token: 't', email: 'runner@example.com');
}

class _SignedOutAuthController extends AuthStateController {
  @override
  Future<AuthState> build() async => AuthState.empty;
}

ActivityListItemDto _item(String id, {String? title}) => ActivityListItemDto(
  id: id,
  activityType: 'running',
  startedAt: DateTime.utc(2026, 1, 1, 7),
  endedAt: DateTime.utc(2026, 1, 1, 7, 30),
  title: title,
  distanceMeters: 5000,
  movingSeconds: 1500,
  tags: const [],
);

Widget _wrap(FakeApiClient fakeApiClient, {bool signedIn = true}) => ProviderScope(
  overrides: [
    apiClientProvider.overrideWithValue(fakeApiClient),
    authStateControllerProvider.overrideWith(
      signedIn ? _SignedInAuthController.new : _SignedOutAuthController.new,
    ),
  ],
  child: const MaterialApp(home: ActivityListScreen()),
);

void main() {
  testWidgets('shows a sign-in prompt when signed out', (tester) async {
    await tester.pumpWidget(_wrap(FakeApiClient(), signedIn: false));
    await tester.pumpAndSettle();

    expect(find.text('Sign in to see your activity history'), findsOneWidget);
  });

  testWidgets('shows an empty state with no activities', (tester) async {
    final fake = FakeApiClient()
      ..listActivitiesHandler = ({required baseUrl, required token, cursor, limit = 50}) async =>
          const ActivityListResponseDto(activities: [], nextCursor: null);

    await tester.pumpWidget(_wrap(fake));
    await tester.pumpAndSettle();

    expect(find.text('No activities yet'), findsOneWidget);
  });

  testWidgets('shows an error message when the fetch fails', (tester) async {
    final fake = FakeApiClient()
      ..listActivitiesHandler = ({required baseUrl, required token, cursor, limit = 50}) =>
          Future.error(StateError('boom'));

    await tester.pumpWidget(_wrap(fake));
    await tester.pumpAndSettle();

    expect(find.textContaining('Could not load activities'), findsOneWidget);
  });

  testWidgets('renders each activity and navigates to its detail screen on tap', (tester) async {
    final fake = FakeApiClient()
      ..listActivitiesHandler = ({required baseUrl, required token, cursor, limit = 50}) async =>
          ActivityListResponseDto(
            activities: [_item('a1', title: 'Morning run')],
            nextCursor: null,
          );

    await tester.pumpWidget(_wrap(fake));
    await tester.pumpAndSettle();

    expect(find.text('Morning run'), findsOneWidget);

    await tester.tap(find.text('Morning run'));
    await tester.pumpAndSettle();

    expect(find.byType(ActivityDetailScreen), findsOneWidget);
  });

  testWidgets('falls back to the started-at timestamp when title is null', (tester) async {
    final fake = FakeApiClient()
      ..listActivitiesHandler = ({required baseUrl, required token, cursor, limit = 50}) async =>
          ActivityListResponseDto(activities: [_item('a1')], nextCursor: null);

    await tester.pumpWidget(_wrap(fake));
    await tester.pumpAndSettle();

    expect(find.textContaining('2026'), findsWidgets);
  });

  testWidgets(
    'still shows the date in the subtitle when a title is set '
    '(regression: a titled activity used to hide its date entirely)',
    (tester) async {
      final fake = FakeApiClient()
        ..listActivitiesHandler = ({required baseUrl, required token, cursor, limit = 50}) async =>
            ActivityListResponseDto(
              activities: [_item('a1', title: 'Morning run')],
              nextCursor: null,
            );

      await tester.pumpWidget(_wrap(fake));
      await tester.pumpAndSettle();

      expect(find.text('Morning run'), findsOneWidget);
      expect(find.textContaining('2026'), findsOneWidget);
    },
  );
}
