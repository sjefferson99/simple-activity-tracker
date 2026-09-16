/// Mirrors the server's SplitPlanOut schema (issue #100) — the split plan an
/// activity was uploaded with. Null on [RunDto.splitPlan] for an activity
/// with no plan at all (an old upload, or a plain rolling preference with no
/// target).
class SplitPlanDto {
  final double? rollingTargetMps;

  /// (size, target) pairs, splits 1..N of a custom plan; empty for a rolling
  /// plan. Size is metres/seconds per the activity's own split type; target
  /// is null for an untargeted custom split.
  final List<(double, double?)> customSplits;
  final String targetsAs;

  const SplitPlanDto({
    required this.rollingTargetMps,
    required this.customSplits,
    required this.targetsAs,
  });

  factory SplitPlanDto.fromJson(Map<String, dynamic> json) => SplitPlanDto(
    rollingTargetMps: (json['rolling_target_mps'] as num?)?.toDouble(),
    customSplits: (json['custom_splits'] as List<dynamic>)
        .map(
          (pair) => (
            (pair[0] as num).toDouble(),
            (pair[1] as num?)?.toDouble(),
          ),
        )
        .toList(),
    targetsAs: json['targets_as'] as String,
  );
}
