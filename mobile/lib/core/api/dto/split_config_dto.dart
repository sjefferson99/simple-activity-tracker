import '../../../domain/tracking/split_plan.dart';
import '../../../domain/tracking/split_preference.dart';
import '../../version/api_compat.dart';

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
    final customSplitsJson =
        json['custom_splits'] as List<dynamic>? ?? const [];
    final customSplits = [
      for (final entry in customSplitsJson)
        PlannedSplit(
          size: (entry[0] as num).toDouble(),
          targetSpeedMps: (entry[1] as num?)?.toDouble(),
        ),
    ];
    return SplitPlan(
      base: base,
      rollingTargetSpeedMps: (json['rolling_target_mps'] as num?)?.toDouble(),
      customSplits: customSplits,
      customLayout: SplitPlan.validLayout(
        _layoutFromWire(json['layout']),
        customSplits,
      ),
      targetsAsPace: (json['targets_as'] as String?) != 'speed',
    );
  }

  /// The repeat-block layout (issue #233; API level 3+), read tolerantly:
  /// missing on older servers, and anything malformed costs only the
  /// grouping (empty list), never the config.
  static List<PlanEntry> _layoutFromWire(Object? json) {
    if (json is! List) return const [];
    PlannedSplit? pair(Object? value) {
      if (value is! List || value.length < 2) return null;
      final size = value[0];
      final target = value[1];
      if (size is! num || (target != null && target is! num)) return null;
      return PlannedSplit(
        size: size.toDouble(),
        targetSpeedMps: (target as num?)?.toDouble(),
      );
    }

    final entries = <PlanEntry>[];
    for (final item in json) {
      if (item is! Map) return const [];
      final repeat = item['repeat'];
      if (repeat == null) {
        final split = pair(item['split']);
        if (split == null) return const [];
        entries.add(SingleSplitEntry(split));
        continue;
      }
      final splitsJson = item['splits'];
      if (repeat is! int || splitsJson is! List) return const [];
      final splits = <PlannedSplit>[];
      for (final value in splitsJson) {
        final split = pair(value);
        if (split == null) return const [];
        splits.add(split);
      }
      entries.add(RepeatBlock(count: repeat, splits: splits));
    }
    return entries;
  }
}

/// Request body for POST/PATCH /api/v1/split-configs — see
/// docs/SPLIT-CONFIGS-PLAN.md §3. [overwrite] is only meaningful on create.
/// The repeat-block layout is only sent to a server at
/// [ApiLevels.splitConfigLayout] or later (issue #233): a level-0 server
/// rejects unknown fields, and older ones would just drop it.
class SplitConfigSaveRequestDto {
  final String name;
  final SplitPlan plan;
  final bool overwrite;
  final int serverApiLevel;

  const SplitConfigSaveRequestDto({
    required this.name,
    required this.plan,
    this.overwrite = false,
    this.serverApiLevel = kLegacyServerApiLevel,
  });

  /// Whether this save keeps [plan]'s repeat blocks on the server.
  bool get sendsLayout =>
      plan.hasRepeatBlocks && serverApiLevel >= ApiLevels.splitConfigLayout;

  Map<String, dynamic> toJson() => {
    'name': name,
    'plan': splitPlanWireJson(plan, includeLayout: sendsLayout),
    if (overwrite) 'overwrite': true,
  };
}

/// [plan] in the server's SplitPlanIn wire shape — shared by saved split
/// configs (issue #126) and a live session's metadata (issue #130). Only a
/// saved config sends the repeat-block `layout` ([includeLayout]), and only
/// to a server new enough for it.
Map<String, dynamic> splitPlanWireJson(
  SplitPlan plan, {
  bool includeLayout = false,
}) => {
  'split_type': plan.base.gpxSplitType,
  'split_value': plan.base.value,
  if (!plan.isCustom && plan.rollingTargetSpeedMps != null)
    'rolling_target_mps': plan.rollingTargetSpeedMps,
  'custom_splits': [
    for (final split in plan.customSplits) [split.size, split.targetSpeedMps],
  ],
  'targets_as': plan.targetsAsPace ? 'pace' : 'speed',
  if (includeLayout && plan.hasRepeatBlocks)
    'layout': [
      for (final entry in plan.customLayout)
        switch (entry) {
          SingleSplitEntry(:final split) => {
            'split': [split.size, split.targetSpeedMps],
          },
          RepeatBlock(:final count, :final splits) => {
            'repeat': count,
            'splits': [
              for (final s in splits) [s.size, s.targetSpeedMps],
            ],
          },
        },
    ],
};
