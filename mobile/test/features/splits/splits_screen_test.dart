import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/tracking/split_plan_controller.dart';
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';
import 'package:simple_activity_tracker/features/splits/splits_screen.dart';

Future<void> _pumpScreen(WidgetTester tester) async {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform({});
  await tester.pumpWidget(
    const ProviderScope(
      child: MaterialApp(home: SplitsScreen()),
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
  return find.descendant(
    of: wrapper,
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
  return find.descendant(
    of: wrapper,
    matching: find.byType(TextFormField),
  );
}

void main() {
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
      final container = ProviderContainer();
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

      expect(
        container.read(splitPlanControllerProvider).customSplits,
        isEmpty,
      );
      expect(
        container.read(splitPlanControllerProvider).base.kind,
        SplitKind.distanceMi,
      );
    },
  );

  testWidgets('deleting a custom split removes only that row', (tester) async {
    final container = ProviderContainer();
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
    await tester.dragUntilVisible(
      find.text('#2'),
      find.byType(ListView),
      const Offset(0, -100),
    );

    expect(find.text('#1'), findsOneWidget);
    expect(find.text('#2'), findsOneWidget);

    await tester.tap(find.byIcon(Icons.delete_outline).first);
    await tester.pumpAndSettle();

    final plan = container.read(splitPlanControllerProvider);
    expect(plan.customSplits, hasLength(1));
    expect(plan.customSplits.first.size, 200);
  });

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
      final container = ProviderContainer();
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
      final container = ProviderContainer();
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
        container.read(splitPlanControllerProvider).customSplits[0].targetSpeedMps,
        closeTo(5.5 / 3.6, 0.001),
      );
    },
  );
}
