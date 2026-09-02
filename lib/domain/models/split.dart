/// A completed one-kilometer split.
class Split {
  final int index;
  final Duration duration;
  final double avgSpeedMps;

  const Split({
    required this.index,
    required this.duration,
    required this.avgSpeedMps,
  });
}
