/// Pure conversion and formatting helpers. No Flutter imports here —
/// keep this layer testable with plain Dart.
library;

double kmhFromMps(double metersPerSecond) => metersPerSecond * 3.6;

const double _metersPerMile = 1609.344;

double mphFromMps(double metersPerSecond) =>
    metersPerSecond * 3600 / _metersPerMile;

/// Seconds needed to cover one kilometer at [metersPerSecond].
/// Returns null when not moving (division by zero / undefined pace).
double? paceSecPerKmFromMps(double metersPerSecond) {
  if (metersPerSecond <= 0) return null;
  return 1000 / metersPerSecond;
}

/// Seconds needed to cover one mile at [metersPerSecond].
/// Returns null when not moving (division by zero / undefined pace).
double? paceSecPerMileFromMps(double metersPerSecond) {
  if (metersPerSecond <= 0) return null;
  return _metersPerMile / metersPerSecond;
}

String formatKmh(double metersPerSecond) {
  return kmhFromMps(metersPerSecond).toStringAsFixed(1);
}

String formatMph(double metersPerSecond) {
  return mphFromMps(metersPerSecond).toStringAsFixed(1);
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

double milesFromMeters(double meters) => meters / _metersPerMile;

String formatDistanceMi(double meters) =>
    milesFromMeters(meters).toStringAsFixed(2);

double feetFromMeters(double meters) => meters * 3.280839895;

/// Formats a metres value (e.g. elevation gain) as a whole number, rounded.
String formatMeters(double meters) => meters.round().toString();

/// Formats a metres value (e.g. elevation gain) as feet, rounded to a whole
/// number — used instead of [formatMeters] when the run's distance unit is
/// miles (issue #94).
String formatFeet(double meters) => feetFromMeters(meters).round().toString();

/// Which distance unit a run's speed/pace/elevation readouts are displayed
/// in. Driven by the split preference's distance unit (see
/// SplitPreference.effectiveDistanceUnit in domain/tracking/split_preference.dart)
/// — km splits show km-based units, mile splits show mile-based units.
enum DistanceUnit {
  km,
  mi;

  String get label => switch (this) {
    DistanceUnit.km => 'km',
    DistanceUnit.mi => 'mi',
  };
}

/// The four interchangeable ways the live run screen's primary readout and
/// metric tiles can show speed/pace: km-based speed, km-based pace,
/// mile-based speed, mile-based pace. Tapping the unit toggle cycles speed
/// ⇄ pace within whichever [DistanceUnit] the current run's splits use — see
/// issue #94.
enum SpeedUnit {
  kmh,
  minKm,
  mph,
  minMi;

  DistanceUnit get distanceUnit => switch (this) {
    SpeedUnit.kmh || SpeedUnit.minKm => DistanceUnit.km,
    SpeedUnit.mph || SpeedUnit.minMi => DistanceUnit.mi,
  };

  bool get isPace => this == SpeedUnit.minKm || this == SpeedUnit.minMi;

  /// The speed-flavored member sharing this unit's [distanceUnit] — what
  /// tapping the toggle switches to from a pace member, and what a pace
  /// member's own suffix/label refers back to.
  SpeedUnit get toggled => switch (this) {
    SpeedUnit.kmh => SpeedUnit.minKm,
    SpeedUnit.minKm => SpeedUnit.kmh,
    SpeedUnit.mph => SpeedUnit.minMi,
    SpeedUnit.minMi => SpeedUnit.mph,
  };

  /// The starting [SpeedUnit] for a run using [unit] as its distance unit —
  /// always the speed-flavored (not pace) member, matching the app's
  /// existing default of starting in km/h.
  static SpeedUnit initialFor(DistanceUnit unit) => switch (unit) {
    DistanceUnit.km => SpeedUnit.kmh,
    DistanceUnit.mi => SpeedUnit.mph,
  };

  String get suffix => switch (this) {
    SpeedUnit.kmh => 'km/h',
    SpeedUnit.minKm => 'min/km',
    SpeedUnit.mph => 'mph',
    SpeedUnit.minMi => 'min/mi',
  };
}

/// Formats speed or pace at [mps] in [unit] — e.g. "18.0 km/h" or
/// "3:20 /km" — used by metric tiles, which spell the unit out on every
/// value unlike the primary readout's separate unit label.
String formatSpeedOrPace(double? mps, SpeedUnit unit) {
  if (mps == null) {
    return unit.isPace ? "--:-- /${_paceSuffix(unit)}" : '--.- ${unit.suffix}';
  }
  return unit.isPace
      ? '${formatPace(unit == SpeedUnit.minMi ? paceSecPerMileFromMps(mps) : paceSecPerKmFromMps(mps))} /${_paceSuffix(unit)}'
      : '${unit == SpeedUnit.mph ? formatMph(mps) : formatKmh(mps)} ${unit.suffix}';
}

String _paceSuffix(SpeedUnit unit) => unit == SpeedUnit.minMi ? 'mi' : 'km';
