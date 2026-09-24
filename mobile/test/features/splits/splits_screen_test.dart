import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/api_client.dart';
import 'package:simple_activity_tracker/core/auth/auth_state.dart';
import 'package:simple_activity_tracker/core/auth/auth_state_controller.dart';
import 'package:simple_activity_tracker/core/tracking/split_plan_controller.dart';
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';
import 'package:simple_activity_tracker/features/splits/splits_screen.dart';

import '../../fakes/fake_api_client.dart';

/// Signed-out by default — most of this screen's tests exercise the plan
/// editor, not the saved-configs section (issue #126), so the section
/// should just show its "sign in" prompt without making a real network
/// call. Tests that specifically exercise saved configs override this.
class _NotSignedInAuthController extends AuthStateController {
  @override
  Future<AuthState> build() async => AuthState.empty;
}

Future<void> _pumpScreen(WidgetTester tester) async {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform({});
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        authStateControllerProvider.overrideWith(
          _NotSignedInAuthController.new,
        ),
        apiClientProvider.overrideWithValue(FakeApiClient()),
      ],
      child: const MaterialApp(home: SplitsScreen()),
    ),
  );
  // Let the controller's async _load() resolve.
  await tester.pumpAndSettle();
}

/// Finds the rolling target field's TextFormField by locating the
/// _CommittingTextField wrapper via its stable key prefix (rather than by
/// its value-dependent text) and descending to the TextFormField inside it
/// — see splits_screen.dart's ValueKey comment.
Finder _rollingTargetField() {
  final wrapper = find.byWidgetPredicate(
    (widget) =>
        widget.key is ValueKey<String> &&
        (widget.key! as ValueKey<String>).value.startsWith('rolling_target-'),
  );
  return find.descendant(of: wrapper, matching: find.byType(TextFormField));
}

/// Finds the "Number of splits" count field. Unlike the rolling/custom
/// fields it has no stable key prefix, so locate it via the fixed "Number
/// of splits" label instead of by its (changing) current text.
Finder _splitCountField() {
  return find.descendant(
    of: find.ancestor(
      of: find.text('Number of splits'),
      matching: find.byType(Row),
    ),
    matching: find.byType(TextFormField),
  );
}

/// Finds the [index]th custom split row's size or target field by its key
/// prefix, same rationale as [_rollingTargetField].
Finder _customSplitField(int index, {required bool target}) {
  final prefix = target ? 'custom_target-$index-' : 'custom_size-$index-';
  final wrapper = find.byWidgetPredicate(
    (widget) =>
        widget.key is ValueKey<String> &&
        (widget.key! as ValueKey<String>).value.startsWith(prefix),
  );
  return find.descendant(of: wrapper, matching: find.byType(TextFormField));
}

/// Finds the [index]th custom split row's delete button, via the row's own
/// `ValueKey(index)` (splits_screen.dart's `_CustomSplitRow(key:
/// ValueKey(i), ...)`) rather than `find.byIcon(...).first`, which picks
/// whichever delete icon happens to be first in the tree — not necessarily
/// row 0's, and wrong once more than one row exists off-screen at once.
Finder _customSplitDeleteButton(int index) => find.descendant(
  of: find.byKey(ValueKey(index)),
  matching: find.byIcon(Icons.delete_outline),
);

/// Pumps the screen with [plan] already selected (issue #134 tests).
Future<void> _pumpWithPlan(WidgetTester tester, SplitPlan plan) async {
  final container = ProviderContainer(
    overrides: [
      authStateControllerProvider.overrideWith(_NotSignedInAuthController.new),
      apiClientProvider.overrideWithValue(FakeApiClient()),
    ],
  );
  addTearDown(container.dispose);
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform({});
  await container.read(splitPlanControllerProvider.notifier).select(plan);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: SplitsScreen()),
    ),
  );
  await tester.pumpAndSettle();
  await tester.dragUntilVisible(
    find.byKey(const ValueKey('custom_plan_totals')),
    find.byType(ListView),
    const Offset(0, -100),
  );
  await tester.pump();
}

void main() {
  testWidgets('custom distance plan shows per-split times and a summed total '
      '(issue #134)', (tester) async {
    await _pumpWithPlan(
      tester,
      const SplitPlan(
        base: SplitPreference.defaultPreference,
        customSplits: [
          PlannedSplit(size: 1000, targetSpeedMps: 1000 / 300),
          PlannedSplit(size: 2000, targetSpeedMps: 1000 / 330),
        ],
      ),
    );

    expect(find.text('= 5:00'), findsOneWidget);
    expect(find.text('= 11:00'), findsOneWidget);
    expect(find.text('Distance: 3 km'), findsOneWidget);
    expect(find.text('Time: 16:00'), findsOneWidget);
  });

  testWidgets('custom time plan sums distance; a missing target blanks it '
      '(issue #134)', (tester) async {
    await _pumpWithPlan(
      tester,
      const SplitPlan(
        base: SplitPreference(kind: SplitKind.timeMin, value: 1),
        customSplits: [
          PlannedSplit(size: 90, targetSpeedMps: 4),
          PlannedSplit(size: 30),
        ],
      ),
    );

    expect(find.text('= 360 m'), findsOneWidget);
    expect(find.text('Time: 2:00'), findsOneWidget);
    expect(find.text('Distance: — (1 split without a target)'), findsOneWidget);
  });
  testWidgets('setting a rolling target shows an equivalent-pace hint', (
    tester,
  ) async {
    await _pumpScreen(tester);
    await tester.dragUntilVisible(
      _rollingTargetField(),
      find.byType(ListView),
      const Offset(0, -100),
    );

    await tester.enterText(_rollingTargetField(), '5:00');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();

    expect(find.textContaining('= 5:00 per split'), findsOneWidget);
  });

  testWidgets('clearing a rolling target removes the hint', (tester) async {
    await _pumpScreen(tester);
    await tester.dragUntilVisible(
      _rollingTargetField(),
      find.byType(ListView),
      const Offset(0, -100),
    );

    await tester.enterText(_rollingTargetField(), '5:00');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(find.textContaining('per split'), findsOneWidget);

    await tester.tap(find.byTooltip('Clear target'));
    await tester.pumpAndSettle();

    expect(find.textContaining('per split'), findsNothing);
  });

  testWidgets('switching to Custom adds one split seeded from the base size', (
    tester,
  ) async {
    await _pumpScreen(tester);

    await tester.dragUntilVisible(
      find.text('Custom'),
      find.byType(ListView),
      const Offset(0, -100),
    );
    await tester.pump();
    await tester.tap(find.text('Custom'));
    await tester.pumpAndSettle();
    // The custom split row sits below the fold on the default test surface
    // size — scroll it into view before asserting on it.
    await tester.dragUntilVisible(
      find.text('Add split'),
      find.byType(ListView),
      const Offset(0, -100),
    );

    expect(find.text('#1'), findsOneWidget);
    expect(find.text('Add split'), findsOneWidget);
  });

  testWidgets(
    'changing split type while custom splits exist asks for confirmation',
    (tester) async {
      final container = ProviderContainer(
        overrides: [
          authStateControllerProvider.overrideWith(
            _NotSignedInAuthController.new,
          ),
          apiClientProvider.overrideWithValue(FakeApiClient()),
        ],
      );
      addTearDown(container.dispose);
      FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(
        {},
      );
      await container
          .read(splitPlanControllerProvider.notifier)
          .select(
            const SplitPlan(
              base: SplitPreference.defaultPreference,
              customSplits: [PlannedSplit(size: 400)],
            ),
          );

      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: SplitsScreen()),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.text('Miles'));
      await tester.pumpAndSettle();

      expect(find.text('Change split type?'), findsOneWidget);

      // Cancel: the plan must be unchanged.
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(
        container.read(splitPlanControllerProvider).customSplits,
        hasLength(1),
      );

      // Now confirm: the custom splits must be cleared.
      await tester.tap(find.text('Miles'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Change'));
      await tester.pumpAndSettle();

      expect(container.read(splitPlanControllerProvider).customSplits, isEmpty);
      expect(
        container.read(splitPlanControllerProvider).base.kind,
        SplitKind.distanceMi,
      );
    },
  );

  testWidgets('deleting a custom split removes only that row', (tester) async {
    final container = ProviderContainer(
      overrides: [
        authStateControllerProvider.overrideWith(
          _NotSignedInAuthController.new,
        ),
        apiClientProvider.overrideWithValue(FakeApiClient()),
      ],
    );
    addTearDown(container.dispose);
    FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(
      {},
    );
    await container
        .read(splitPlanControllerProvider.notifier)
        .select(
          const SplitPlan(
            base: SplitPreference.defaultPreference,
            customSplits: [PlannedSplit(size: 400), PlannedSplit(size: 200)],
          ),
        );

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: SplitsScreen()),
      ),
    );
    await tester.pumpAndSettle();
    // Scroll directly to row 0's own delete button (not just its "#1" text
    // label) so the tap below actually lands on it — the label alone can be
    // visible while the button beside it, further right/below, still isn't.
    await tester.dragUntilVisible(
      _customSplitDeleteButton(0),
      find.byType(ListView),
      const Offset(0, -100),
    );
    await tester.pump();

    expect(find.text('#1'), findsOneWidget);
    expect(find.text('#2'), findsOneWidget);

    await tester.tap(_customSplitDeleteButton(0));
    await tester.pumpAndSettle();

    final plan = container.read(splitPlanControllerProvider);
    expect(plan.customSplits, hasLength(1));
    expect(plan.customSplits.first.size, 200);
  });

  testWidgets(
    'shrinking the split count asks for confirmation before discarding splits',
    (tester) async {
      final container = ProviderContainer(
        overrides: [
          authStateControllerProvider.overrideWith(
            _NotSignedInAuthController.new,
          ),
          apiClientProvider.overrideWithValue(FakeApiClient()),
        ],
      );
      addTearDown(container.dispose);
      FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(
        {},
      );
      await container
          .read(splitPlanControllerProvider.notifier)
          .select(
            const SplitPlan(
              base: SplitPreference.defaultPreference,
              customSplits: [
                PlannedSplit(size: 400),
                PlannedSplit(size: 200),
                PlannedSplit(size: 100),
              ],
            ),
          );

      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: SplitsScreen()),
        ),
      );
      await tester.pumpAndSettle();

      final countField = _splitCountField();
      await tester.dragUntilVisible(
        countField,
        find.byType(ListView),
        const Offset(0, -100),
      );
      await tester.enterText(countField, '1');
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pumpAndSettle();

      expect(find.text('Remove splits?'), findsOneWidget);

      // Cancel: the plan must be unchanged.
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(
        container.read(splitPlanControllerProvider).customSplits,
        hasLength(3),
      );

      // Now confirm: the trailing splits must be discarded.
      await tester.enterText(countField, '1');
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Remove'));
      await tester.pumpAndSettle();

      expect(
        container.read(splitPlanControllerProvider).customSplits,
        hasLength(1),
      );
    },
  );

  testWidgets(
    'growing the split count from empty seeds a split sized for the plan kind, not a hardcoded 1000',
    (tester) async {
      final container = ProviderContainer(
        overrides: [
          authStateControllerProvider.overrideWith(
            _NotSignedInAuthController.new,
          ),
          apiClientProvider.overrideWithValue(FakeApiClient()),
        ],
      );
      addTearDown(container.dispose);
      FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(
        {},
      );
      // A mile-kind rolling plan of 2 miles with no custom splits yet —
      // growing the count should seed a split sized in metres-per-mile, not
      // the km-kind default of a bare 1000.
      await container
          .read(splitPlanControllerProvider.notifier)
          .select(
            const SplitPlan(
              base: SplitPreference(kind: SplitKind.distanceMi, value: 2),
            ),
          );

      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: SplitsScreen()),
        ),
      );
      await tester.pumpAndSettle();

      await tester.dragUntilVisible(
        find.text('Custom'),
        find.byType(ListView),
        const Offset(0, -100),
      );
      await tester.pump();
      await tester.tap(find.text('Custom'));
      await tester.pumpAndSettle();

      final countField = _splitCountField();
      await tester.dragUntilVisible(
        countField,
        find.byType(ListView),
        const Offset(0, -100),
      );
      await tester.pump();
      await tester.enterText(countField, '2');
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pumpAndSettle();

      final plan = container.read(splitPlanControllerProvider);
      expect(plan.customSplits, hasLength(2));
      expect(plan.customSplits.last.size, closeTo(2 * 1609.344, 0.001));
    },
  );

  testWidgets(
    'a size edit commits on focus loss even without pressing Done '
    '(regression: on-device bug where an edited field was silently lost on navigating away)',
    (tester) async {
      // Real on-device bug (2026-09-14): a custom split's size field showed
      // the newly typed value, but leaving the screen (back button/gesture)
      // without first pressing Done or tapping empty space discarded it —
      // onFieldSubmitted needs the keyboard's submit key, and onTapOutside
      // never fires for a route pop. The field committing on focus loss
      // itself (which a pop always causes, since the framework unfocuses a
      // field before disposing it) is what actually fixes this.
      final container = ProviderContainer(
        overrides: [
          authStateControllerProvider.overrideWith(
            _NotSignedInAuthController.new,
          ),
          apiClientProvider.overrideWithValue(FakeApiClient()),
        ],
      );
      addTearDown(container.dispose);
      FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(
        {},
      );
      await container
          .read(splitPlanControllerProvider.notifier)
          .select(
            const SplitPlan(
              base: SplitPreference(kind: SplitKind.timeMin, value: 1),
              targetsAsPace: false,
              customSplits: [PlannedSplit(size: 60, targetSpeedMps: 4 / 3.6)],
            ),
          );

      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: MaterialApp(
            home: Builder(
              builder: (context) => Scaffold(
                body: Center(
                  child: FilledButton(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => const SplitsScreen()),
                    ),
                    child: const Text('Open Splits'),
                  ),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Open Splits'));
      await tester.pumpAndSettle();
      await tester.dragUntilVisible(
        find.text('#1'),
        find.byType(ListView),
        const Offset(0, -300),
      );

      // Type a new size, but neither submit via the keyboard action nor tap
      // elsewhere on screen — go straight to popping the route, exactly as
      // tapping the AppBar back arrow or the system back gesture would.
      await tester.enterText(_customSplitField(0, target: false), '1:30');
      await tester.pump();

      final navigator = tester.state<NavigatorState>(find.byType(Navigator));
      navigator.pop();
      await tester.pumpAndSettle();

      expect(
        container.read(splitPlanControllerProvider).customSplits[0].size,
        90,
        reason: 'the edit was lost on navigating away without pressing Done',
      );
    },
  );

  testWidgets(
    'a target edit also commits on focus loss without pressing Done',
    (tester) async {
      final container = ProviderContainer(
        overrides: [
          authStateControllerProvider.overrideWith(
            _NotSignedInAuthController.new,
          ),
          apiClientProvider.overrideWithValue(FakeApiClient()),
        ],
      );
      addTearDown(container.dispose);
      FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(
        {},
      );
      await container
          .read(splitPlanControllerProvider.notifier)
          .select(
            const SplitPlan(
              base: SplitPreference(kind: SplitKind.timeMin, value: 1),
              targetsAsPace: false,
              customSplits: [PlannedSplit(size: 60, targetSpeedMps: 4 / 3.6)],
            ),
          );

      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const MaterialApp(home: SplitsScreen()),
        ),
      );
      await tester.pumpAndSettle();
      await tester.dragUntilVisible(
        find.text('#1'),
        find.byType(ListView),
        const Offset(0, -300),
      );

      await tester.enterText(_customSplitField(0, target: true), '5.5');
      await tester.pump();
      // Simulate focus moving away without a Done key or an outside tap —
      // e.g. the field losing focus because the app was backgrounded, or
      // (as above) the route about to be popped.
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();

      expect(
        container
            .read(splitPlanControllerProvider)
            .customSplits[0]
            .targetSpeedMps,
        closeTo(5.5 / 3.6, 0.001),
      );
    },
  );
}
