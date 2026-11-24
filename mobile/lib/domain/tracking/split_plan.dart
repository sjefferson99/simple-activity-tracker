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

  PlannedSplit copyWith({
    double? size,
    double? targetSpeedMps,
    bool clearTarget = false,
  }) => PlannedSplit(
    size: size ?? this.size,
    targetSpeedMps: clearTarget
        ? null
        : (targetSpeedMps ?? this.targetSpeedMps),
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

/// One entry of a custom plan as the editor lays it out (issue #225): a
/// single split, or a [RepeatBlock] of several splits repeated N times.
/// Entries only exist for editing: everything that runs, logs or uploads a
/// plan reads the flat, expanded [SplitPlan.customSplits].
sealed class PlanEntry {
  const PlanEntry();

  /// The flat splits this entry stands for, in run order.
  List<PlannedSplit> expand();

  Map<String, Object?> toJson();

  /// Parses one persisted entry, or throws on malformed JSON (caught by
  /// [SplitPlan.fromJson]).
  static PlanEntry fromJson(Map<String, Object?> json) {
    final repeat = json['repeat'];
    if (repeat == null) {
      return SingleSplitEntry(
        PlannedSplit.fromJson(
          Map<String, Object?>.from(json['split']! as Map<Object?, Object?>),
        ),
      );
    }
    return RepeatBlock(
      count: repeat as int,
      splits: [
        for (final entry in json['splits']! as List<Object?>)
          PlannedSplit.fromJson(
            Map<String, Object?>.from(entry! as Map<Object?, Object?>),
          ),
      ],
    );
  }
}

/// A single split in the editor's layout.
class SingleSplitEntry extends PlanEntry {
  final PlannedSplit split;

  const SingleSplitEntry(this.split);

  @override
  List<PlannedSplit> expand() => [split];

  @override
  Map<String, Object?> toJson() => {'split': split.toJson()};

  @override
  bool operator ==(Object other) =>
      other is SingleSplitEntry && other.split == split;

  @override
  int get hashCode => split.hashCode;
}

/// `count x [splits...]`, e.g. 5 x [3:00 @ 10 km/h, 2:00 @ 7 km/h]
/// (issue #225). [count] >= 1 and [splits] non-empty.
class RepeatBlock extends PlanEntry {
  final int count;
  final List<PlannedSplit> splits;

  const RepeatBlock({required this.count, required this.splits});

  RepeatBlock copyWith({int? count, List<PlannedSplit>? splits}) =>
      RepeatBlock(count: count ?? this.count, splits: splits ?? this.splits);

  @override
  List<PlannedSplit> expand() => [for (var i = 0; i < count; i++) ...splits];

  @override
  Map<String, Object?> toJson() => {
    'repeat': count,
    'splits': [for (final s in splits) s.toJson()],
  };

  @override
  bool operator ==(Object other) =>
      other is RepeatBlock &&
      other.count == count &&
      _listEquals(other.splits, splits);

  @override
  int get hashCode => Object.hash(count, Object.hashAll(splits));
}

/// The flat split list [entries] expand to, in run order.
List<PlannedSplit> expandPlanEntries(List<PlanEntry> entries) => [
  for (final entry in entries) ...entry.expand(),
];

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

  /// How the editor groups [customSplits] (issue #225): empty when the plan
  /// is just a list of single splits (always the case for a plan from a
  /// saved config or an older install), else entries whose expansion is
  /// exactly [customSplits]. Local-only: never sent to the server or written
  /// to the GPX. Read it through [customEntries].
  final List<PlanEntry> customLayout;

  /// Whether targets are entered/displayed as pace (true) or speed (false).
  /// Display-only — targets are always stored as speed in m/s.
  final bool targetsAsPace;

  const SplitPlan({
    required this.base,
    this.rollingTargetSpeedMps,
    this.customSplits = const [],
    this.customLayout = const [],
    this.targetsAsPace = true,
  });

  static const SplitPlan defaultPlan = SplitPlan(
    base: SplitPreference.defaultPreference,
  );

  bool get isCustom => customSplits.isNotEmpty;

  /// The custom plan as the editor shows it: [customLayout] when it holds a
  /// repeat block, else one [SingleSplitEntry] per custom split.
  List<PlanEntry> get customEntries => customLayout.isNotEmpty
      ? customLayout
      : [for (final s in customSplits) SingleSplitEntry(s)];

  /// Whether the custom plan contains at least one [RepeatBlock].
  bool get hasRepeatBlocks => customLayout.any((e) => e is RepeatBlock);

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
    if (customLayout.isNotEmpty)
      'customLayout': [for (final e in customLayout) e.toJson()],
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
        if (s.targetSpeedMps != null && s.targetSpeedMps! <= 0) return null;
      }
      if (customSplits.length > maxCustomSplits) return null;
      final customLayout = _layoutFromJson(json['customLayout'], customSplits);
      final rollingTargetSpeedMps = (json['rollingTargetSpeedMps'] as num?)
          ?.toDouble();
      if (rollingTargetSpeedMps != null && rollingTargetSpeedMps <= 0) {
        return null;
      }
      return SplitPlan(
        base: base,
        rollingTargetSpeedMps: rollingTargetSpeedMps,
        customSplits: customSplits,
        customLayout: customLayout,
        targetsAsPace: json['targetsAsPace'] as bool? ?? true,
      );
    } catch (_) {
      return null;
    }
  }

  /// The persisted editor layout, or empty when it's missing, malformed or
  /// doesn't expand to exactly [customSplits]. The flat list is what runs,
  /// so a bad layout only costs the grouping, never the plan itself.
  static List<PlanEntry> _layoutFromJson(
    Object? json,
    List<PlannedSplit> customSplits,
  ) {
    if (json == null) return const [];
    try {
      final layout = [
        for (final entry in json as List<Object?>)
          PlanEntry.fromJson(
            Map<String, Object?>.from(entry! as Map<Object?, Object?>),
          ),
      ];
      var expandedLength = 0;
      for (final entry in layout) {
        switch (entry) {
          case RepeatBlock(:final count, :final splits):
            if (count < 1 || splits.isEmpty) return const [];
            expandedLength += count * splits.length;
          case SingleSplitEntry():
            expandedLength += 1;
        }
      }
      // Check the size before expanding, so a corrupt huge repeat count
      // can't allocate a huge list.
      if (expandedLength != customSplits.length) return const [];
      if (!_listEquals(expandPlanEntries(layout), customSplits)) {
        return const [];
      }
      return _normalizedLayout(layout);
    } catch (_) {
      return const [];
    }
  }

  /// Drops a layout with no repeat block, so a plan of single splits is
  /// stored and compared the same way whether or not it came from entries.
  static List<PlanEntry> _normalizedLayout(List<PlanEntry> entries) =>
      entries.any((e) => e is RepeatBlock)
      ? List.unmodifiable(entries)
      : const [];

  SplitPlan copyWith({
    SplitPreference? base,
    double? rollingTargetSpeedMps,
    bool clearRollingTarget = false,
    List<PlannedSplit>? customSplits,
    List<PlanEntry>? customEntries,
    bool? targetsAsPace,
  }) {
    // [customEntries] (the editor's grouped form) sets both the flat list
    // and the layout; a bare [customSplits] replaces the plan with single
    // splits, so any old grouping no longer applies.
    assert(customSplits == null || customEntries == null);
    final List<PlannedSplit> splits;
    final List<PlanEntry> layout;
    if (customEntries != null) {
      splits = expandPlanEntries(customEntries);
      layout = _normalizedLayout(customEntries);
    } else if (customSplits != null) {
      splits = customSplits;
      layout = const [];
    } else {
      splits = this.customSplits;
      layout = customLayout;
    }
    return SplitPlan(
      base: base ?? this.base,
      rollingTargetSpeedMps: clearRollingTarget
          ? null
          : (rollingTargetSpeedMps ?? this.rollingTargetSpeedMps),
      customSplits: splits,
      customLayout: layout,
      targetsAsPace: targetsAsPace ?? this.targetsAsPace,
    );
  }

  @override
  bool operator ==(Object other) =>
      other is SplitPlan &&
      other.base == base &&
      other.rollingTargetSpeedMps == rollingTargetSpeedMps &&
      _listEquals(other.customSplits, customSplits) &&
      _listEquals(other.customLayout, customLayout) &&
      other.targetsAsPace == targetsAsPace;

  @override
  int get hashCode => Object.hash(
    base,
    rollingTargetSpeedMps,
    Object.hashAll(customSplits),
    Object.hashAll(customLayout),
    targetsAsPace,
  );
}

bool _listEquals<T>(List<T> a, List<T> b) {
  if (a.length != b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}

const double metersPerMile = 1609.344;
