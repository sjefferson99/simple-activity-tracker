/// A completed split, sized per the run's [SplitPreference].
class Split {
  final int index;
  final Duration duration;
  final double avgSpeedMps;

  /// The distance actually covered by this split — constant across every
  /// split for a distance-mode preference, but varies per split for a
  /// time-mode preference (a slower time-boxed split covers less ground).
  final double distanceMeters;

  /// The target speed this split was measured against (issue #99), or null
  /// if the run's split plan had no target for this split — either a
  /// rolling plan with no target set, or a custom plan's split beyond the
  /// last planned one (see SplitPlan's roll-on behavior).
  final double? targetSpeedMps;

  const Split({
    required this.index,
    required this.duration,
    required this.avgSpeedMps,
    required this.distanceMeters,
    this.targetSpeedMps,
  });
}
