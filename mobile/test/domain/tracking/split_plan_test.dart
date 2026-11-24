import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/units/units.dart'
    show DistanceUnit;
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';

void main() {
  group('rolling plan', () {
    const plan = SplitPlan(
      base: SplitPreference(kind: SplitKind.distanceKm, value: 1),
      rollingTargetSpeedMps: 3.0,
    );

    test('is not custom and has no planned count', () {
      expect(plan.isCustom, isFalse);
      expect(plan.plannedCount, isNull);
    });

    test('sizeOf returns the base size for any index', () {
      expect(plan.sizeOf(0), 1000.0);
      expect(plan.sizeOf(5), 1000.0);
      expect(plan.sizeOf(500), 1000.0);
    });

    test('targetOf returns the rolling target for any index', () {
      expect(plan.targetOf(0), 3.0);
      expect(plan.targetOf(5), 3.0);
    });

    test('gpxPlanValue is null (nothing custom to write)', () {
      expect(plan.gpxPlanValue, isNull);
    });
  });

  group('rolling plan with no target', () {
    test('targetOf is null everywhere', () {
      const plan = SplitPlan(
        base: SplitPreference(kind: SplitKind.distanceKm, value: 1),
      );
      expect(plan.targetOf(0), isNull);
      expect(plan.targetOf(9), isNull);
    });
  });

  group('custom plan', () {
    const plan = SplitPlan(
      base: SplitPreference(kind: SplitKind.timeMin, value: 1),
      customSplits: [
        PlannedSplit(size: 90, targetSpeedMps: 2.222),
        PlannedSplit(size: 60, targetSpeedMps: 1.667),
        PlannedSplit(size: 120), // no target
      ],
    );

    test('is custom with a planned count matching the list', () {
      expect(plan.isCustom, isTrue);
      expect(plan.plannedCount, 3);
    });

    test('sizeOf returns each planned split size in order', () {
      expect(plan.sizeOf(0), 90.0);
      expect(plan.sizeOf(1), 60.0);
      expect(plan.sizeOf(2), 120.0);
    });

    test('sizeOf rolls on to the base size past the plan', () {
      // base.kind is timeMin, value 1 => 60 seconds.
      expect(plan.sizeOf(3), 60.0);
      expect(plan.sizeOf(100), 60.0);
    });

    test('targetOf returns each planned target, and null when unset', () {
      expect(plan.targetOf(0), 2.222);
      expect(plan.targetOf(1), 1.667);
      expect(plan.targetOf(2), isNull);
    });

    test(
      'targetOf is null once the plan is exhausted (roll-on, no target)',
      () {
        expect(plan.targetOf(3), isNull);
        expect(plan.targetOf(100), isNull);
      },
    );

    test('gpxPlanValue encodes size@target, omitting target when absent', () {
      expect(plan.gpxPlanValue, '90@2.222;60@1.667;120');
    });
  });

  group('gpxPlanValue formatting', () {
    test('whole-number sizes/targets have no trailing .0', () {
      const plan = SplitPlan(
        base: SplitPreference(kind: SplitKind.distanceKm, value: 1),
        customSplits: [
          PlannedSplit(size: 400, targetSpeedMps: 3),
          PlannedSplit(size: 1000),
        ],
      );
      expect(plan.gpxPlanValue, '400@3;1000');
    });
  });

  group('JSON round trip', () {
    test('rolling plan with a target round-trips', () {
      const plan = SplitPlan(
        base: SplitPreference(
          kind: SplitKind.timeMin,
          value: 5,
          timeSplitDisplayUnit: DistanceUnit.mi,
        ),
        rollingTargetSpeedMps: 2.5,
        targetsAsPace: false,
      );
      final restored = SplitPlan.fromJson(plan.toJson());
      expect(restored, plan);
    });

    test('custom plan round-trips', () {
      const plan = SplitPlan(
        base: SplitPreference(kind: SplitKind.distanceKm, value: 1),
        customSplits: [
          PlannedSplit(size: 400, targetSpeedMps: 3.5),
          PlannedSplit(size: 200),
        ],
      );
      final restored = SplitPlan.fromJson(plan.toJson());
      expect(restored, plan);
    });

    test('fromJson returns null for malformed input', () {
      expect(SplitPlan.fromJson({'base': 'garbage'}), isNull);
      expect(SplitPlan.fromJson({}), isNull);
    });

    test('fromJson returns null for a non-positive base value', () {
      expect(
        SplitPlan.fromJson({
          'base': {'kind': 'distanceKm', 'value': 0},
          'customSplits': <Object?>[],
        }),
        isNull,
      );
    });

    test('fromJson returns null for a non-positive custom split size', () {
      expect(
        SplitPlan.fromJson({
          'base': {'kind': 'distanceKm', 'value': 1},
          'customSplits': [
            {'size': 0},
          ],
        }),
        isNull,
      );
    });

    test('fromJson returns null when customSplits exceeds the cap', () {
      expect(
        SplitPlan.fromJson({
          'base': {'kind': 'distanceKm', 'value': 1},
          'customSplits': [
            for (var i = 0; i < maxCustomSplits + 1; i++) {'size': 100},
          ],
        }),
        isNull,
      );
    });
  });

  group('copyWith', () {
    test('clearRollingTarget removes the target', () {
      const plan = SplitPlan(
        base: SplitPreference.defaultPreference,
        rollingTargetSpeedMps: 3.0,
      );
      final cleared = plan.copyWith(clearRollingTarget: true);
      expect(cleared.rollingTargetSpeedMps, isNull);
    });
  });

  group('repeat blocks (issue #225)', () {
    const warm = PlannedSplit(size: 300, targetSpeedMps: 6 / 3.6);
    const work = PlannedSplit(size: 180, targetSpeedMps: 10 / 3.6);
    const rest = PlannedSplit(size: 120, targetSpeedMps: 7 / 3.6);
    const time = SplitPreference(kind: SplitKind.timeMin, value: 1);
    final entries = <PlanEntry>[
      const SingleSplitEntry(warm),
      const RepeatBlock(count: 5, splits: [work, rest]),
      const SingleSplitEntry(warm),
    ];

    test('customEntries expand into the flat customSplits', () {
      final plan = const SplitPlan(base: time).copyWith(customEntries: entries);
      expect(plan.customSplits, [
        warm,
        for (var i = 0; i < 5; i++) ...[work, rest],
        warm,
      ]);
      expect(plan.plannedCount, 12);
      expect(plan.hasRepeatBlocks, isTrue);
      expect(plan.customEntries, entries);
      expect(plan.targetOf(2), rest.targetSpeedMps);
      expect(plan.sizeOf(11), 300);
    });

    test('GPX plan value is the expanded list, unchanged in format', () {
      final plan = const SplitPlan(base: time).copyWith(
        customEntries: const [
          RepeatBlock(count: 2, splits: [PlannedSplit(size: 60), work]),
        ],
      );
      expect(
        plan.gpxPlanValue,
        '60;180@2.7777777777777777;60;180@2.7777777777777777',
      );
    });

    test('a layout of only single splits is not kept', () {
      final plan = const SplitPlan(base: time).copyWith(
        customEntries: const [SingleSplitEntry(warm), SingleSplitEntry(work)],
      );
      expect(plan.customLayout, isEmpty);
      expect(plan.toJson().containsKey('customLayout'), isFalse);
      expect(plan, const SplitPlan(base: time, customSplits: [warm, work]));
    });

    test('replacing customSplits drops the grouping', () {
      final plan = const SplitPlan(base: time).copyWith(customEntries: entries);
      final flat = plan.copyWith(customSplits: const [warm]);
      expect(flat.hasRepeatBlocks, isFalse);
      expect(flat.customEntries, const [SingleSplitEntry(warm)]);
      // Other edits keep it.
      expect(plan.copyWith(targetsAsPace: false).customLayout, entries);
    });

    test('round-trips through JSON', () {
      final plan = const SplitPlan(base: time).copyWith(customEntries: entries);
      expect(SplitPlan.fromJson(plan.toJson()), plan);
    });

    test('a layout that does not match customSplits is ignored, plan kept', () {
      final json = const SplitPlan(base: time)
          .copyWith(customEntries: entries)
          .toJson();
      json['customSplits'] = [warm.toJson()];
      final parsed = SplitPlan.fromJson(json)!;
      expect(parsed.customSplits, [warm]);
      expect(parsed.customLayout, isEmpty);
    });

    test('a malformed layout is ignored, plan kept', () {
      for (final bad in <Object?>[
        'nonsense',
        [
          {'repeat': 0, 'splits': <Object?>[]},
        ],
        [
          {'repeat': 'x'},
        ],
        [
          {
            'repeat': 1000000000,
            'splits': [warm.toJson()],
          },
        ],
      ]) {
        final json = const SplitPlan(base: time, customSplits: [warm]).toJson()
          ..['customLayout'] = bad;
        final parsed = SplitPlan.fromJson(json)!;
        expect(parsed.customSplits, [warm], reason: '$bad');
        expect(parsed.customLayout, isEmpty, reason: '$bad');
      }
    });

    test('the 50-split cap applies to the expanded list', () {
      final json = const SplitPlan(base: time)
          .copyWith(
            customEntries: const [
              RepeatBlock(count: 26, splits: [work, rest]),
            ],
          )
          .toJson();
      expect(SplitPlan.fromJson(json), isNull);
    });
  });

  group('PlannedSplit.copyWith', () {
    test('clearTarget removes the target', () {
      const split = PlannedSplit(size: 400, targetSpeedMps: 3.0);
      final cleared = split.copyWith(clearTarget: true);
      expect(cleared.targetSpeedMps, isNull);
      expect(cleared.size, 400);
    });
  });
}
