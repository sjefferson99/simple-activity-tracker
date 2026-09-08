/// A completed split, sized per the run's [SplitPreference].
class Split {
  final int index;
  final Duration duration;
  final double avgSpeedMps;

  /// The distance actually covered by this split — constant across every
  /// split for a distance-mode preference, but varies per split for a
  /// time-mode preference (a slower time-boxed split covers less ground).
  final double distanceMeters;

  const Split({
    required this.index,
    required this.duration,
    required this.avgSpeedMps,
    required this.distanceMeters,
  });
}
