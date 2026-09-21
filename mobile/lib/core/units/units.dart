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

/// Formats how far off target [avgMps] is from [targetMps], as the
/// correction the runner should make (issue #99 D7) — the arrow always
/// points the direction to move the *value being displayed*, not "up" for
/// faster: too fast means slow down (▼ for speed, but for pace a slower
/// pace is a *higher* number, so the pace arrow is ▲ in that case — see
/// below), too slow means speed up. Returns "on target" within
/// [splitTargetTolerance] of the target.
///
/// This is the delta as shown next to a split's actual pace/speed, not the
/// on/off-target boolean itself — see `splitVerdict` in
/// `domain/tracking/split_target.dart`, which this deliberately does not
/// depend on (units.dart has no dependents in `domain/`, only the reverse).
String formatSpeedDelta(double avgMps, double targetMps, SpeedUnit unit) {
  const tolerance = 0.05; // mirrors splitTargetTolerance; duplicated to keep
  // units.dart dependency-free of domain/tracking — see doc above.
  final ratio = avgMps / targetMps;
  if (ratio >= 1 - tolerance && ratio <= 1 + tolerance) return 'on target';

  final tooFast = ratio > 1;
  if (unit.isPace) {
    // A faster pace is a *smaller* number (e.g. 4:30 is faster than 5:00),
    // so "too fast" means the displayed pace value needs to go UP to slow
    // down — arrow up. "Too slow" means the value needs to go DOWN to speed
    // up — arrow down. This is the inverse of the speed-unit case below.
    final avgPaceSec = unit == SpeedUnit.minMi
        ? paceSecPerMileFromMps(avgMps)
        : paceSecPerKmFromMps(avgMps);
    final targetPaceSec = unit == SpeedUnit.minMi
        ? paceSecPerMileFromMps(targetMps)
        : paceSecPerKmFromMps(targetMps);
    // avgMps <= 0 means pace is undefined (stopped), not "on target" — the
    // ratio check above already puts this case outside tolerance since
    // ratio == 0, so this must report "too slow", not fall back silently.
    if (avgPaceSec == null) return '▼ stopped';
    if (targetPaceSec == null) return 'on target';
    final deltaSeconds = (avgPaceSec - targetPaceSec).abs().round();
    final arrow = tooFast ? '▲' : '▼';
    final direction = tooFast ? 'fast' : 'slow';
    return '$arrow $deltaSeconds s/${_paceSuffix(unit)} $direction';
  } else {
    // A faster speed is a *larger* number, so "too fast" means the
    // displayed value needs to go DOWN — arrow down. "Too slow" needs it to
    // go UP — arrow up.
    final avgDisplay = unit == SpeedUnit.mph ? mphFromMps(avgMps) : kmhFromMps(avgMps);
    final targetDisplay = unit == SpeedUnit.mph
        ? mphFromMps(targetMps)
        : kmhFromMps(targetMps);
    final delta = (avgDisplay - targetDisplay).abs();
    final arrow = tooFast ? '▼' : '▲';
    final direction = tooFast ? 'fast' : 'slow';
    return '$arrow ${delta.toStringAsFixed(1)} ${unit.suffix} $direction';
  }
}

/// Formats a split size for display — [sizeMeters] for a distance-kind
/// split (whole metres under 1km/1mi, otherwise decimal km/mi matching
/// [distanceUnit]) or [sizeSeconds] for a time-kind split (as `m:ss`).
String formatSplitSizeMeters(double sizeMeters, DistanceUnit distanceUnit) {
  if (distanceUnit == DistanceUnit.mi) {
    final miles = milesFromMeters(sizeMeters);
    if (miles < 0.1) return '${feetFromMeters(sizeMeters).round()} ft';
    return '${_trimDecimal(miles)} mi';
  }
  if (sizeMeters < 1000) return '${sizeMeters.round()} m';
  return '${_trimDecimal(sizeMeters / 1000)} km';
}

String formatSplitSizeSeconds(double sizeSeconds) =>
    formatMinSec(Duration(milliseconds: (sizeSeconds * 1000).round()));

/// Formats a decimal value trimmed of trailing zeros beyond 2 decimal
/// places (e.g. "1", "1.5", "0.25"), used for split-size distances where a
/// whole "1 km" reads better than "1.00 km".
String _trimDecimal(double value) {
  final fixed = value.toStringAsFixed(2);
  return fixed.replaceFirst(RegExp(r'\.?0+$'), '');
}

/// Formats a duration as "m:ss" — used for split sizes/targets entered as a
/// time (e.g. "1:30"), distinct from [formatDuration]'s "h:mm:ss" which
/// omits the hour digit instead of always showing minutes.
String formatMinSec(Duration duration) {
  final totalSeconds = duration.inSeconds;
  final minutes = totalSeconds ~/ 60;
  final seconds = totalSeconds % 60;
  return '$minutes:${seconds.toString().padLeft(2, '0')}';
}

/// Parses "m:ss" or "mm:ss" into a duration, or null if malformed (more
/// than one colon, non-numeric parts, or seconds outside 0-59). A plain
/// whole number with no colon at all (e.g. "5") is accepted as whole
/// minutes by default ("5:00") — typing the colon is easy to forget on a
/// phone keyboard, and "5" meaning "5 minutes" is the expected reading for
/// a pace/duration field. Pass [bareNumberAsSeconds] for a field whose
/// value is naturally seconds-sized (e.g. a short custom split length),
/// where a colon-less "90" should mean 90 seconds ("1:30"), not 90 minutes.
Duration? parseMinSec(String text, {bool bareNumberAsSeconds = false}) {
  final trimmed = text.trim();
  final parts = trimmed.split(':');
  if (parts.length == 1) {
    final value = int.tryParse(parts[0]);
    if (value == null || value < 0) return null;
    return bareNumberAsSeconds
        ? Duration(seconds: value)
        : Duration(minutes: value);
  }
  if (parts.length != 2) return null;
  final minutes = int.tryParse(parts[0]);
  final seconds = int.tryParse(parts[1]);
  if (minutes == null || seconds == null) return null;
  if (minutes < 0 || seconds < 0 || seconds > 59) return null;
  return Duration(minutes: minutes, seconds: seconds);
}

/// Parses a pace string ("m:ss", meaning minutes:seconds per km or mile —
/// caller decides which via [unit]) into a speed in m/s, or null if
/// malformed or zero. [unit] must be a pace-flavored member.
double? parsePaceToMps(String text, SpeedUnit unit) {
  assert(unit.isPace, 'parsePaceToMps expects a pace-flavored SpeedUnit');
  final duration = parseMinSec(text);
  if (duration == null || duration.inSeconds <= 0) return null;
  final secondsPerUnit = duration.inSeconds.toDouble();
  final metersPerUnit = unit == SpeedUnit.minMi ? _metersPerMile : 1000.0;
  return metersPerUnit / secondsPerUnit;
}

/// Parses a plain decimal speed string (km/h or mph per [unit]) into m/s,
/// or null if malformed or non-positive. [unit] must be a speed-flavored
/// member.
double? parseSpeedToMps(String text, SpeedUnit unit) {
  assert(!unit.isPace, 'parseSpeedToMps expects a speed-flavored SpeedUnit');
  final value = double.tryParse(text.trim());
  if (value == null || value <= 0) return null;
  return unit == SpeedUnit.mph ? value * _metersPerMile / 3600 : value / 3.6;
}

const _monthNames = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
];

/// Formats a local [dateTime] as "12 Sep 2026, 14:07" — used wherever an
/// activity's date/time is shown (activity list, activity detail), so it
/// always appears even when a title is set (issue #101 follow-up: an
/// activity list row previously showed nothing but the title once one was
/// set, hiding the date entirely).
String formatActivityDate(DateTime dateTime) {
  final hour = dateTime.hour.toString().padLeft(2, '0');
  final minute = dateTime.minute.toString().padLeft(2, '0');
  return '${dateTime.day} ${_monthNames[dateTime.month - 1]} ${dateTime.year}, $hour:$minute';
}

/// Speaks a duration as "m:ss" would be spelled out — "4 minutes 12
/// seconds" (or just "12 seconds" under a minute) — for text-to-speech
/// (issue #125), which reads a colon-formatted string as nonsense.
String speakDuration(Duration duration) {
  final minutes = duration.inMinutes;
  final seconds = duration.inSeconds.remainder(60);
  if (minutes <= 0) return '$seconds seconds';
  final minutePart = minutes == 1 ? '1 minute' : '$minutes minutes';
  if (seconds == 0) return minutePart;
  return '$minutePart $seconds seconds';
}

/// Speaks a pace/speed value for text-to-speech (issue #125) — e.g. "5
/// minutes 30 per kilometre" or "18 point 0 kilometres per hour". Returns
/// null when [mps] is null (nothing to say — the caller skips the phrase
/// entirely rather than speaking "unknown").
String? speakSpeedOrPace(double? mps, SpeedUnit unit) {
  if (mps == null) return null;
  if (unit.isPace) {
    final paceSec = unit == SpeedUnit.minMi
        ? paceSecPerMileFromMps(mps)
        : paceSecPerKmFromMps(mps);
    if (paceSec == null || !paceSec.isFinite) return null;
    final totalSeconds = paceSec.round();
    final minutes = totalSeconds ~/ 60;
    final seconds = totalSeconds % 60;
    final unitName = unit == SpeedUnit.minMi ? 'mile' : 'kilometre';
    final minutePart = minutes == 1 ? '1 minute' : '$minutes minutes';
    return seconds == 0
        ? '$minutePart per $unitName'
        : '$minutePart $seconds per $unitName';
  }
  final display = unit == SpeedUnit.mph ? mphFromMps(mps) : kmhFromMps(mps);
  final unitName = unit == SpeedUnit.mph
      ? 'miles per hour'
      : 'kilometres per hour';
  return '${display.toStringAsFixed(1).replaceFirst('.', ' point ')} $unitName';
}

/// Speaks how far off target [avgMps] is from [targetMps] (issue #125) —
/// e.g. "2 minutes 10 seconds per kilometre too slow" or "1 point 5 miles
/// per hour too fast", or "back on target" within tolerance. Mirrors
/// [formatSpeedDelta]'s direction/tolerance logic exactly, phrased for
/// speech instead of a compact tile string.
String speakSpeedDelta(double avgMps, double targetMps, SpeedUnit unit) {
  const tolerance = 0.05; // mirrors splitTargetTolerance — see formatSpeedDelta.
  final ratio = avgMps / targetMps;
  if (ratio >= 1 - tolerance && ratio <= 1 + tolerance) return 'back on target';

  final tooFast = ratio > 1;
  final direction = tooFast ? 'too fast' : 'too slow';
  if (unit.isPace) {
    final avgPaceSec = unit == SpeedUnit.minMi
        ? paceSecPerMileFromMps(avgMps)
        : paceSecPerKmFromMps(avgMps);
    final targetPaceSec = unit == SpeedUnit.minMi
        ? paceSecPerMileFromMps(targetMps)
        : paceSecPerKmFromMps(targetMps);
    if (avgPaceSec == null || targetPaceSec == null) return direction;
    final deltaSeconds = (avgPaceSec - targetPaceSec).abs().round();
    final unitName = unit == SpeedUnit.minMi ? 'mile' : 'kilometre';
    return '${speakDuration(Duration(seconds: deltaSeconds))} per $unitName $direction';
  } else {
    final avgDisplay = unit == SpeedUnit.mph ? mphFromMps(avgMps) : kmhFromMps(avgMps);
    final targetDisplay = unit == SpeedUnit.mph
        ? mphFromMps(targetMps)
        : kmhFromMps(targetMps);
    final delta = (avgDisplay - targetDisplay).abs();
    final unitName = unit == SpeedUnit.mph
        ? 'miles per hour'
        : 'kilometres per hour';
    return '${delta.toStringAsFixed(1).replaceFirst('.', ' point ')} $unitName $direction';
  }
}

/// Speaks a split's size for text-to-speech (issue #125 follow-up) — e.g.
/// "1 kilometre", "500 metres", "0.5 miles", "1 minute 30 seconds". Mirrors
/// [formatSplitSizeMeters]/[formatSplitSizeSeconds]'s own unit/threshold
/// choices, phrased for speech (a spelled-out unit name, no abbreviation,
/// and [speakDuration] instead of "m:ss" for a time-kind split).
String speakSplitSize(double sizeMeters, DistanceUnit distanceUnit) {
  if (distanceUnit == DistanceUnit.mi) {
    final miles = milesFromMeters(sizeMeters);
    if (miles < 0.1) {
      final feet = feetFromMeters(sizeMeters).round();
      return feet == 1 ? '1 foot' : '$feet feet';
    }
    return '${_trimDecimal(miles)} miles';
  }
  if (sizeMeters < 1000) {
    final metres = sizeMeters.round();
    return metres == 1 ? '1 metre' : '$metres metres';
  }
  final km = _trimDecimal(sizeMeters / 1000);
  return km == '1' ? '1 kilometre' : '$km kilometres';
}

String speakSplitSizeSeconds(double sizeSeconds) =>
    speakDuration(Duration(milliseconds: (sizeSeconds * 1000).round()));

/// Formats a target speed ([targetMps]) for display in an editor field —
/// pace as "m:ss", speed as a plain one-decimal number (no unit suffix,
/// since the field's own label/segmented control already shows the unit).
String formatTargetForEditing(double targetMps, SpeedUnit unit) {
  if (unit.isPace) {
    final paceSec = unit == SpeedUnit.minMi
        ? paceSecPerMileFromMps(targetMps)
        : paceSecPerKmFromMps(targetMps);
    return formatPace(paceSec);
  }
  final display = unit == SpeedUnit.mph ? mphFromMps(targetMps) : kmhFromMps(targetMps);
  return display.toStringAsFixed(1);
}
