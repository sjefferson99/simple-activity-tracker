/// Tolerant readers for free-form server JSON — `analysis.result` and similar
/// maps whose shape openapi.json doesn't pin down (docs/VERSIONING.md §3.3).
///
/// Each returns null (or an empty list) for a missing key *or* a value of the
/// wrong type, never throws: a server older or newer than this app may omit
/// a field or change it, and that must cost one missing line on screen, not a
/// crashed activity view. Pure Dart.
library;

double? readDouble(Map<String, dynamic>? json, String key) => switch (json?[key]) {
  final num value => value.toDouble(),
  _ => null,
};

/// Accepts a whole-number double too (`1.0` → 1): a server serialising an
/// index as a float must not blank out the row.
int? readInt(Map<String, dynamic>? json, String key) => switch (json?[key]) {
  final int value => value,
  final double value when value == value.roundToDouble() => value.toInt(),
  _ => null,
};

String? readString(Map<String, dynamic>? json, String key) => switch (json?[key]) {
  final String value => value,
  _ => null,
};

Map<String, dynamic>? readMap(Map<String, dynamic>? json, String key) => switch (json?[key]) {
  final Map<String, dynamic> value => value,
  _ => null,
};

/// The list's object entries; anything that isn't a JSON object is skipped.
List<Map<String, dynamic>> readMapList(Map<String, dynamic>? json, String key) =>
    switch (json?[key]) {
      final List<dynamic> values => values.whereType<Map<String, dynamic>>().toList(),
      _ => const [],
    };
