import '../../core/units/units.dart' show DistanceUnit;
import 'split_preference.dart';

/// Maximum number of splits a custom plan may define — generous for any
/// real workout (an interval session rarely has more than a couple dozen
/// reps) while bounding storage/GPX size and the editor's list length.
const int maxCustomSplits = 50;

/// One split of a custom [SplitPlan]: a size (in metres for a distance-kind
/// plan, seconds for a time-kind plan — always finer than
/// [SplitPreference]'s whole-unit rolling size, since a workout may want
/// e.g. a 90-second interval) and an optional target speed.
class PlannedSplit {
  /// Metres (distance-kind plan) or seconds (time-kind plan). Must be > 0.
  final double size;

  /// Target average speed for this split, in m/s, or null for no target.
  final double? targetSpeedMps;

  const PlannedSplit({required this.size, this.targetSpeedMps});

  PlannedSplit copyWith({double? size, double? targetSpeedMps, bool clearTarget = false}) =>
      PlannedSplit(
        size: size ?? this.size,
        targetSpeedMps: clearTarget ? null : (targetSpeedMps ?? this.targetSpeedMps),
      );

  Map<String, Object?> toJson() => {
    'size': size,
    if (targetSpeedMps != null) 'targetSpeedMps': targetSpeedMps,
  };

  factory PlannedSplit.fromJson(Map<String, Object?> json) => PlannedSplit(
    size: (json['size'] as num).toDouble(),
    targetSpeedMps: (json['targetSpeedMps'] as num?)?.toDouble(),
  );

  @override
  bool operator ==(Object other) =>
      other is PlannedSplit &&
      other.size == size &&
      other.targetSpeedMps == targetSpeedMps;

  @override
  int get hashCode => Object.hash(size, targetSpeedMps);
}

/// A run's full split configuration (issue #99): the split kind/size that
/// was already configurable ([base]), plus optional targets and an optional
/// custom (variable-size) plan replacing the rolling one.
///
/// [base]'s kind/value are still the wire format written to
/// `sat:split_type`/`sat:split_value` and read by the server's analyzer —
/// see [SplitPreference]'s own doc. A custom plan's [customSplits] are
/// additional, server-ignored-for-now GPX extensions (issue #99 §4.2); the
/// server keeps analyzing at [base]'s rolling size regardless.
class SplitPlan {
  final SplitPreference base;

  /// Target applied to every rolling split when [customSplits] is empty.
  /// Null = no target. Ignored (and roll-on splits after a custom plan ends
  /// get no target either — see [targetOf]) when [isCustom].
  final double? rollingTargetSpeedMps;

  /// Empty = rolling plan (every split sized/targeted per [base] and
  /// [rollingTargetSpeedMps]). Non-empty = a custom plan: splits 1..N sized
  /// and targeted individually, then rolling on at [base]'s size with no
  /// target once exhausted (see [sizeOf]/[targetOf]).
  final List<PlannedSplit> customSplits;

  /// Whether targets are entered/displayed as pace (true) or speed (false).
  /// Display-only — targets are always stored as speed in m/s.
  final bool targetsAsPace;

  const SplitPlan({
    required this.base,
    this.rollingTargetSpeedMps,
    this.customSplits = const [],
    this.targetsAsPace = true,
  });

  static const SplitPlan defaultPlan = SplitPlan(
    base: SplitPreference.defaultPreference,
  );

  bool get isCustom => customSplits.isNotEmpty;

  /// Number of splits explicitly planned for a custom plan (the "/6" in
  /// "Split 3/6"), or null for a rolling plan (which has no fixed count).
  int? get plannedCount => isCustom ? customSplits.length : null;

  /// Size (metres for a distance-kind [base], seconds for a time-kind one)
  /// of the 0-based [splitIndex]th split: the matching custom entry while
  /// inside a custom plan, else [base]'s rolling size.
  double sizeOf(int splitIndex) {
    if (isCustom && splitIndex < customSplits.length) {
      return customSplits[splitIndex].size;
    }
    return _baseSizeInPlanUnits;
  }

  /// Target speed (m/s) for the 0-based [splitIndex]th split: the matching
  /// custom entry's target while inside a custom plan (may itself be null),
  /// [rollingTargetSpeedMps] for a rolling plan, or null once a custom
  /// plan's splits are exhausted (roll-on has no target — issue #99 D5).
  double? targetOf(int splitIndex) {
    if (isCustom) {
      return splitIndex < customSplits.length
          ? customSplits[splitIndex].targetSpeedMps
          : null;
    }
    return rollingTargetSpeedMps;
  }

  double get _baseSizeInPlanUnits => switch (base.kind) {
    SplitKind.distanceKm => base.value * 1000.0,
    SplitKind.distanceMi => base.value * metersPerMile,
    SplitKind.timeMin => base.value * 60.0,
  };

  /// The value written to the GPX's `sat:split_plan` extension for a custom
  /// plan — `size@target;size@target;size` (target omitted when null),
  /// sizes in metres/seconds per [base.kind], speeds in m/s — or null for a
  /// rolling plan, which writes no `sat:split_plan` element at all.
  String? get gpxPlanValue {
    if (!isCustom) return null;
    return customSplits
        .map(
          (s) => s.targetSpeedMps != null
              ? '${_num(s.size)}@${_num(s.targetSpeedMps!)}'
              : _num(s.size),
        )
        .join(';');
  }

  static String _num(double value) {
    // Avoid trailing ".0" noise for whole numbers while still writing full
    // precision fractional values (e.g. a target speed of 2.7778 m/s).
    return value == value.roundToDouble()
        ? value.toStringAsFixed(0)
        : value.toString();
  }

  Map<String, Object?> toJson() => {
    'base': {
      'kind': base.kind.name,
      'value': base.value,
      'timeSplitDisplayUnit': base.timeSplitDisplayUnit.name,
    },
    if (rollingTargetSpeedMps != null)
      'rollingTargetSpeedMps': rollingTargetSpeedMps,
    'customSplits': [for (final s in customSplits) s.toJson()],
    'targetsAsPace': targetsAsPace,
  };

  /// Parses a previously-persisted plan, or null if the JSON is malformed —
  /// callers should fall back to [defaultPlan] on null, same convention as
  /// [SplitPreference.fromGpxValues].
  static SplitPlan? fromJson(Map<String, Object?> json) {
    try {
      final baseJson = json['base'] as Map<Object?, Object?>;
      final kind = SplitKind.values.byName(baseJson['kind']! as String);
      final value = baseJson['value']! as int;
      final displayUnitName = baseJson['timeSplitDisplayUnit'] as String?;
      final base = SplitPreference(
        kind: kind,
        value: value,
        timeSplitDisplayUnit: displayUnitName == 'mi'
            ? DistanceUnit.mi
            : DistanceUnit.km,
      );
      final customSplitsJson = json['customSplits'] as List<Object?>? ?? [];
      final customSplits = [
        for (final entry in customSplitsJson)
          PlannedSplit.fromJson(
            Map<String, Object?>.from(entry! as Map<Object?, Object?>),
          ),
      ];
      if (value <= 0) return null;
      for (final s in customSplits) {
        if (s.size <= 0) return null;
      }
      if (customSplits.length > maxCustomSplits) return null;
      return SplitPlan(
        base: base,
        rollingTargetSpeedMps: (json['rollingTargetSpeedMps'] as num?)
            ?.toDouble(),
        customSplits: customSplits,
        targetsAsPace: json['targetsAsPace'] as bool? ?? true,
      );
    } catch (_) {
      return null;
    }
  }

  SplitPlan copyWith({
    SplitPreference? base,
    double? rollingTargetSpeedMps,
    bool clearRollingTarget = false,
    List<PlannedSplit>? customSplits,
    bool? targetsAsPace,
  }) => SplitPlan(
    base: base ?? this.base,
    rollingTargetSpeedMps: clearRollingTarget
        ? null
        : (rollingTargetSpeedMps ?? this.rollingTargetSpeedMps),
    customSplits: customSplits ?? this.customSplits,
    targetsAsPace: targetsAsPace ?? this.targetsAsPace,
  );

  @override
  bool operator ==(Object other) =>
      other is SplitPlan &&
      other.base == base &&
      other.rollingTargetSpeedMps == rollingTargetSpeedMps &&
      _listEquals(other.customSplits, customSplits) &&
      other.targetsAsPace == targetsAsPace;

  @override
  int get hashCode => Object.hash(
    base,
    rollingTargetSpeedMps,
    Object.hashAll(customSplits),
    targetsAsPace,
  );
}

bool _listEquals(List<PlannedSplit> a, List<PlannedSplit> b) {
  if (a.length != b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}

const double metersPerMile = 1609.344;
