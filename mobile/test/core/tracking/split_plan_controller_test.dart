import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/tracking/split_plan_controller.dart';
import 'package:simple_activity_tracker/core/units/units.dart' show DistanceUnit;
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';

ProviderContainer _container(Map<String, String> backing) {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(
    backing,
  );
  final container = ProviderContainer();
  addTearDown(container.dispose);
  return container;
}

void main() {
  test(
    'defaults to the default plan before storage has loaded, and stays there with nothing stored',
    () async {
      final container = _container({});
      expect(
        container.read(splitPlanControllerProvider),
        SplitPlan.defaultPlan,
      );

      await pumpEventQueue();
      expect(
        container.read(splitPlanControllerProvider),
        SplitPlan.defaultPlan,
      );
    },
  );

  test('loads a previously persisted plan on build', () async {
    const plan = SplitPlan(
      base: SplitPreference(kind: SplitKind.timeMin, value: 5),
      rollingTargetSpeedMps: 3.0,
    );
    final container = _container({'split_plan': jsonEncode(plan.toJson())});
    container.read(splitPlanControllerProvider);
    await pumpEventQueue();

    expect(container.read(splitPlanControllerProvider), plan);
  });

  test('select updates state immediately and persists it', () async {
    final container = _container({});
    const plan = SplitPlan(
      base: SplitPreference(kind: SplitKind.distanceMi, value: 2),
      customSplits: [PlannedSplit(size: 400, targetSpeedMps: 3.5)],
    );
    await container.read(splitPlanControllerProvider.notifier).select(plan);

    expect(container.read(splitPlanControllerProvider), plan);

    final storage = const FlutterSecureStorage();
    final stored = await storage.read(key: 'split_plan');
    expect(stored, isNotNull);
    expect(SplitPlan.fromJson(jsonDecode(stored!) as Map<String, Object?>), plan);
  });

  test(
    'a slow _load() cannot clobber a select() the user already made',
    () async {
      const persisted = SplitPlan(
        base: SplitPreference(kind: SplitKind.timeMin, value: 10),
      );
      final container = _container({
        'split_plan': jsonEncode(persisted.toJson()),
      });
      // Trigger build()/the unawaited _load(), but don't let it resolve yet.
      container.read(splitPlanControllerProvider);

      const selected = SplitPlan(
        base: SplitPreference(kind: SplitKind.distanceKm, value: 3),
      );
      await container.read(splitPlanControllerProvider.notifier).select(selected);

      // Now let the in-flight _load() resolve — it must not overwrite the
      // user's selection with the stale persisted value it read earlier.
      await pumpEventQueue();

      expect(container.read(splitPlanControllerProvider), selected);
    },
  );

  group('migration from the pre-#99 legacy keys', () {
    test(
      'a fresh install with only the legacy keys loads them as a rolling plan and writes the new key',
      () async {
        final container = _container({
          'split_kind': 'time_min',
          'split_value': '5',
          'split_time_display_unit': 'mi',
        });
        container.read(splitPlanControllerProvider);
        await pumpEventQueue();

        expect(
          container.read(splitPlanControllerProvider),
          const SplitPlan(
            base: SplitPreference(
              kind: SplitKind.timeMin,
              value: 5,
              timeSplitDisplayUnit: DistanceUnit.mi,
            ),
          ),
        );

        // The migration must have written the new key so it only runs once.
        final storage = const FlutterSecureStorage();
        final stored = await storage.read(key: 'split_plan');
        expect(stored, isNotNull);
      },
    );

    test(
      'a fresh install with no keys at all falls back to the default plan',
      () async {
        final container = _container({});
        container.read(splitPlanControllerProvider);
        await pumpEventQueue();

        expect(
          container.read(splitPlanControllerProvider),
          SplitPlan.defaultPlan,
        );
      },
    );

    test(
      'a present split_plan key wins over the legacy keys (migration already happened)',
      () async {
        const plan = SplitPlan(
          base: SplitPreference(kind: SplitKind.distanceMi, value: 2),
        );
        final container = _container({
          'split_plan': jsonEncode(plan.toJson()),
          // Stale legacy keys left over from before migration — must be
          // ignored now that the new key exists.
          'split_kind': 'time_min',
          'split_value': '99',
        });
        container.read(splitPlanControllerProvider);
        await pumpEventQueue();

        expect(container.read(splitPlanControllerProvider), plan);
      },
    );
  });
}
