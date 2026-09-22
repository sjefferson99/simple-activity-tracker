import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/dto/split_config_dto.dart';
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';

void main() {
  group('SplitConfigDto.fromJson', () {
    test('parses a rolling plan with a target', () {
      final dto = SplitConfigDto.fromJson({
        'id': 'c1',
        'name': '5k tempo',
        'plan': {
          'split_type': 'distance_km',
          'split_value': 1,
          'rolling_target_mps': 2.5,
          'custom_splits': <dynamic>[],
          'targets_as': 'pace',
        },
        'created_at': '2026-01-01T00:00:00Z',
        'updated_at': '2026-01-02T00:00:00Z',
      });

      expect(dto.id, 'c1');
      expect(dto.name, '5k tempo');
      expect(dto.plan.base.kind, SplitKind.distanceKm);
      expect(dto.plan.base.value, 1);
      expect(dto.plan.rollingTargetSpeedMps, 2.5);
      expect(dto.plan.isCustom, isFalse);
      expect(dto.plan.targetsAsPace, isTrue);
      expect(dto.createdAt, DateTime.utc(2026));
      expect(dto.updatedAt, DateTime.utc(2026, 1, 2));
    });

    test('parses a rolling plan with no target', () {
      final dto = SplitConfigDto.fromJson({
        'id': 'c1',
        'name': 'Easy',
        'plan': {
          'split_type': 'distance_mi',
          'split_value': 2,
          'rolling_target_mps': null,
          'custom_splits': <dynamic>[],
          'targets_as': 'speed',
        },
        'created_at': '2026-01-01T00:00:00Z',
        'updated_at': '2026-01-01T00:00:00Z',
      });

      expect(dto.plan.base.kind, SplitKind.distanceMi);
      expect(dto.plan.base.value, 2);
      expect(dto.plan.rollingTargetSpeedMps, isNull);
      expect(dto.plan.targetsAsPace, isFalse);
    });

    test('parses a custom plan, including an untargeted split', () {
      final dto = SplitConfigDto.fromJson({
        'id': 'c1',
        'name': 'Intervals',
        'plan': {
          'split_type': 'time_min',
          'split_value': 1,
          'rolling_target_mps': null,
          'custom_splits': [
            [90.0, 4.0],
            [60.0, 6.0],
            [90.0, null],
          ],
          'targets_as': 'speed',
        },
        'created_at': '2026-01-01T00:00:00Z',
        'updated_at': '2026-01-01T00:00:00Z',
      });

      expect(dto.plan.isCustom, isTrue);
      expect(dto.plan.customSplits, hasLength(3));
      expect(dto.plan.customSplits[0].size, 90.0);
      expect(dto.plan.customSplits[0].targetSpeedMps, 4.0);
      expect(dto.plan.customSplits[2].targetSpeedMps, isNull);
    });

    test('falls back to the default preference for an unrecognized split_type', () {
      final dto = SplitConfigDto.fromJson({
        'id': 'c1',
        'name': 'Weird',
        'plan': {
          'split_type': 'furlongs',
          'split_value': 1,
          'rolling_target_mps': null,
          'custom_splits': <dynamic>[],
          'targets_as': 'pace',
        },
        'created_at': '2026-01-01T00:00:00Z',
        'updated_at': '2026-01-01T00:00:00Z',
      });

      expect(dto.plan.base, SplitPreference.defaultPreference);
    });
  });

  group('SplitConfigSaveRequestDto.toJson', () {
    test('a rolling plan with a target', () {
      final request = SplitConfigSaveRequestDto(
        name: '5k tempo',
        plan: SplitPlan(
          base: const SplitPreference(kind: SplitKind.distanceKm, value: 1),
          rollingTargetSpeedMps: 2.5,
        ),
      );

      expect(request.toJson(), {
        'name': '5k tempo',
        'plan': {
          'split_type': 'distance_km',
          'split_value': 1,
          'rolling_target_mps': 2.5,
          'custom_splits': <dynamic>[],
          'targets_as': 'pace',
        },
      });
    });

    test('omits rolling_target_mps entirely when null', () {
      final request = SplitConfigSaveRequestDto(
        name: 'Easy',
        plan: const SplitPlan(base: SplitPreference(kind: SplitKind.distanceKm, value: 1)),
      );

      expect(request.toJson()['plan'], isNot(contains('rolling_target_mps')));
    });

    test('a custom plan encodes size/target pairs and omits rolling_target_mps', () {
      final request = SplitConfigSaveRequestDto(
        name: 'Intervals',
        plan: SplitPlan(
          base: const SplitPreference(kind: SplitKind.timeMin, value: 1),
          customSplits: const [
            PlannedSplit(size: 90.0, targetSpeedMps: 4.0),
            PlannedSplit(size: 60.0),
          ],
          targetsAsPace: false,
        ),
      );

      final json = request.toJson();
      expect(json['plan'], isNot(contains('rolling_target_mps')));
      expect(json['plan']['custom_splits'], [
        [90.0, 4.0],
        [60.0, null],
      ]);
      expect(json['plan']['targets_as'], 'speed');
    });

    test('includes overwrite:true only when requested', () {
      final plan = const SplitPlan(base: SplitPreference(kind: SplitKind.distanceKm, value: 1));
      final withoutOverwrite = SplitConfigSaveRequestDto(name: 'x', plan: plan);
      final withOverwrite = SplitConfigSaveRequestDto(name: 'x', plan: plan, overwrite: true);

      expect(withoutOverwrite.toJson().containsKey('overwrite'), isFalse);
      expect(withOverwrite.toJson()['overwrite'], isTrue);
    });
  });
}
