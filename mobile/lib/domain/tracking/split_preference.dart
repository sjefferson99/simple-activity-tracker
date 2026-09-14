import '../../core/units/units.dart' show DistanceUnit;

/// Kind of split boundary a run is measured in: distance in kilometers,
/// distance in miles, or elapsed time in minutes. Distance splits also
/// decide the run's display units (km/h ⇄ min/km vs mph ⇄ min/mi, and
/// elevation in meters vs feet) — see [SplitPreference.effectiveDistanceUnit]
/// and issue #94. A time split has no distance to infer that from, so its
/// display unit is a separate, explicit choice ([SplitPreference.timeSplitDisplayUnit]).
enum SplitKind { distanceKm, distanceMi, timeMin }

/// A user's chosen split size — e.g. "every 1 km" or "every 5 minutes" — plus,
/// for a time split only, which distance unit to display speed/pace/elevation
/// in. Pure Dart: [kind]/[value] mirror the server's
/// Activity.split_type/split_value columns (server/app/models/activity.py)
/// and AnalyzerV1's split_type/split_value parameters
/// (server/app/analysis/v1.py) exactly, on the wire via
/// [gpxSplitType]/[value]. [timeSplitDisplayUnit] is a local display-only
/// choice with no server/wire counterpart — it never affects how a split
/// boundary itself is computed.
class SplitPreference {
  final SplitKind kind;

  /// Positive integer: kilometers, miles, or minutes depending on [kind].
  final int value;

  /// Display unit to use when [kind] is [SplitKind.timeMin] — a time split
  /// has no inherent distance unit, so this is asked for separately (see the
  /// Settings screen). Ignored for a distance split, whose unit is implied by
  /// [kind] itself (see [effectiveDistanceUnit]).
  final DistanceUnit timeSplitDisplayUnit;

  const SplitPreference({
    required this.kind,
    required this.value,
    this.timeSplitDisplayUnit = DistanceUnit.km,
  });

  static const SplitPreference defaultPreference = SplitPreference(
    kind: SplitKind.distanceKm,
    value: 1,
  );

  /// The distance unit every speed/pace/elevation readout on the live run
  /// screen should use for a run with this split preference (issue #94): a
  /// distance split's own unit, or [timeSplitDisplayUnit] for a time split.
  DistanceUnit get effectiveDistanceUnit => switch (kind) {
    SplitKind.distanceKm => DistanceUnit.km,
    SplitKind.distanceMi => DistanceUnit.mi,
    SplitKind.timeMin => timeSplitDisplayUnit,
  };

  /// The wire value written to the GPX's `sat:split_type` extension and
  /// matching the server's split_type string enum exactly.
  String get gpxSplitType => switch (kind) {
    SplitKind.distanceKm => 'distance_km',
    SplitKind.distanceMi => 'distance_mi',
    SplitKind.timeMin => 'time_min',
  };

  /// Parses a [gpxSplitType] string back into a [SplitKind], or null if
  /// unrecognized — mirrors the server's best-effort,
  /// never-throw convention for reading GPX extensions (see
  /// parse_split_preference in server/app/analysis/gpx_parser.py).
  static SplitPreference? fromGpxValues(String? splitType, String? splitValue) {
    if (splitType == null || splitValue == null) return null;
    final kind = switch (splitType) {
      'distance_km' => SplitKind.distanceKm,
      'distance_mi' => SplitKind.distanceMi,
      'time_min' => SplitKind.timeMin,
      _ => null,
    };
    if (kind == null) return null;
    final value = int.tryParse(splitValue);
    if (value == null || value <= 0) return null;
    return SplitPreference(kind: kind, value: value);
  }

  @override
  bool operator ==(Object other) =>
      other is SplitPreference &&
      other.kind == kind &&
      other.value == value &&
      other.timeSplitDisplayUnit == timeSplitDisplayUnit;

  @override
  int get hashCode => Object.hash(kind, value, timeSplitDisplayUnit);
}
