import '../../domain/models/run_summary.dart';
import '../version/api_compat.dart';

/// The `summary` JSON sent with `POST /api/v1/activities`, shaped for a
/// server at [serverApiLevel] — docs/VERSIONING.md §3.1.
///
/// [RunSummary.toJson] is the full local-sidecar format and must never be
/// sent to the server directly: servers up to v1.2.4 (API level 0) reject
/// any field they don't know with a 400, failing the whole upload. Every
/// field added after v1.0.0 is gated here on the level that introduced it;
/// the local record keeps all of them regardless (§3.5).
///
/// Golden copies of the output live in `contract/upload-summary/` and are
/// checked by both the mobile and the server test suites (§6).
Map<String, dynamic> buildUploadSummaryJson(
  RunSummary summary, {
  required int serverApiLevel,
}) {
  final json = summary.toJson();
  if (serverApiLevel < ApiLevels.uploadExtendedStats) {
    json.remove('max_speed_mps');
    json.remove('elevation_gain_meters');
    json['splits'] = [
      for (final split in json['splits'] as List<dynamic>)
        Map<String, dynamic>.of(split as Map<String, dynamic>)..remove('target_speed_mps'),
    ];
  }
  return json;
}
