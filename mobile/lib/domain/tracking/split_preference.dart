/// Kind of split boundary a run is measured in: distance in kilometers,
/// distance in miles, or elapsed time in minutes. Choosing miles only
/// affects the split boundary itself — the rest of the app's display stays
/// in km/h or min/km regardless (see core/units).
enum SplitKind { distanceKm, distanceMi, timeMin }

/// A user's chosen split size — e.g. "every 1 km" or "every 5 minutes".
/// Pure Dart: mirrors the server's Activity.split_type/split_value columns
/// (server/app/models/activity.py) and AnalyzerV1's split_type/split_value
/// parameters (server/app/analysis/v1.py) exactly, on the wire via
/// [gpxSplitType]/[value].
class SplitPreference {
  final SplitKind kind;

  /// Positive integer: kilometers, miles, or minutes depending on [kind].
  final int value;

  const SplitPreference({required this.kind, required this.value});

  static const SplitPreference defaultPreference = SplitPreference(
    kind: SplitKind.distanceKm,
    value: 1,
  );

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
      other is SplitPreference && other.kind == kind && other.value == value;

  @override
  int get hashCode => Object.hash(kind, value);
}
