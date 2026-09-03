/// Pure conversion and formatting helpers. No Flutter imports here —
/// keep this layer testable with plain Dart.
library;

double kmhFromMps(double metersPerSecond) => metersPerSecond * 3.6;

/// Seconds needed to cover one kilometer at [metersPerSecond].
/// Returns null when not moving (division by zero / undefined pace).
double? paceSecPerKmFromMps(double metersPerSecond) {
  if (metersPerSecond <= 0) return null;
  return 1000 / metersPerSecond;
}

String formatKmh(double metersPerSecond) {
  return kmhFromMps(metersPerSecond).toStringAsFixed(1);
}

/// Formats pace as "m:ss". Returns "--:--" when pace is undefined (stopped).
String formatPace(double? secPerKm) {
  if (secPerKm == null || !secPerKm.isFinite) return '--:--';
  final totalSeconds = secPerKm.round();
  final minutes = totalSeconds ~/ 60;
  final seconds = totalSeconds % 60;
  return '$minutes:${seconds.toString().padLeft(2, '0')}';
}

/// Formats a duration as "h:mm:ss" (omitting the hour part under 1 hour).
String formatDuration(Duration duration) {
  final hours = duration.inHours;
  final minutes = duration.inMinutes.remainder(60);
  final seconds = duration.inSeconds.remainder(60);
  final mm = minutes.toString().padLeft(hours > 0 ? 2 : 1, '0');
  final ss = seconds.toString().padLeft(2, '0');
  return hours > 0 ? '$hours:$mm:$ss' : '$mm:$ss';
}

String formatDistanceKm(double meters) => (meters / 1000).toStringAsFixed(2);

/// Formats a metres value (e.g. elevation gain) as a whole number, rounded.
String formatMeters(double meters) => meters.round().toString();
