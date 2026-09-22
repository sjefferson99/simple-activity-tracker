import '../../../domain/tracking/split_plan.dart';
import '../../../domain/tracking/split_preference.dart';

/// A saved, named split plan (issue #126) — mirrors the server's
/// SplitConfigOut schema. Unlike [SplitPlanDto] (which mirrors the
/// read-only SplitPlanOut an *activity* was uploaded with, and has no
/// split_type/split_value of its own since those live on the activity
/// directly), a SplitConfig is a standalone plan: its own `plan` object on
/// the wire carries split_type/split_value alongside the target/custom-split
/// fields, matching the server's SplitPlanIn. [toSplitPlan]/[fromSplitPlan]
/// convert to/from the app's own [SplitPlan] domain model, whose JSON shape
/// (used for local persistence) is different from this wire shape — see
/// docs/SPLIT-CONFIGS-PLAN.md §1.
class SplitConfigDto {
  final String id;
  final String name;
  final SplitPlan plan;
  final DateTime createdAt;
  final DateTime updatedAt;

  const SplitConfigDto({
    required this.id,
    required this.name,
    required this.plan,
    required this.createdAt,
    required this.updatedAt,
  });

  factory SplitConfigDto.fromJson(Map<String, dynamic> json) => SplitConfigDto(
    id: json['id'] as String,
    name: json['name'] as String,
    plan: _planFromJson(json['plan'] as Map<String, dynamic>),
    createdAt: DateTime.parse(json['created_at'] as String),
    updatedAt: DateTime.parse(json['updated_at'] as String),
  );

  static SplitPlan _planFromJson(Map<String, dynamic> json) {
    final base =
        SplitPreference.fromGpxValues(
          json['split_type'] as String?,
          '${json['split_value']}',
        ) ??
        SplitPreference.defaultPreference;
    final customSplitsJson = json['custom_splits'] as List<dynamic>? ?? const [];
    return SplitPlan(
      base: base,
      rollingTargetSpeedMps: (json['rolling_target_mps'] as num?)?.toDouble(),
      customSplits: [
        for (final entry in customSplitsJson)
          PlannedSplit(
            size: (entry[0] as num).toDouble(),
            targetSpeedMps: (entry[1] as num?)?.toDouble(),
          ),
      ],
      targetsAsPace: (json['targets_as'] as String?) != 'speed',
    );
  }
}

/// Request body for POST/PATCH /api/v1/split-configs — see
/// docs/SPLIT-CONFIGS-PLAN.md §3. [overwrite] is only meaningful on create.
class SplitConfigSaveRequestDto {
  final String name;
  final SplitPlan plan;
  final bool overwrite;

  const SplitConfigSaveRequestDto({
    required this.name,
    required this.plan,
    this.overwrite = false,
  });

  Map<String, dynamic> toJson() => {
    'name': name,
    'plan': _planToJson(plan),
    if (overwrite) 'overwrite': true,
  };

  static Map<String, dynamic> _planToJson(SplitPlan plan) => {
    'split_type': plan.base.gpxSplitType,
    'split_value': plan.base.value,
    if (!plan.isCustom && plan.rollingTargetSpeedMps != null)
      'rolling_target_mps': plan.rollingTargetSpeedMps,
    'custom_splits': [
      for (final split in plan.customSplits) [split.size, split.targetSpeedMps],
    ],
    'targets_as': plan.targetsAsPace ? 'pace' : 'speed',
  };
}
