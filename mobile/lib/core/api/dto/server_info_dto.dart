import '../../version/api_compat.dart';

/// Mirrors the server's ServerInfoOut schema (`GET /api/v1/server-info`,
/// docs/VERSIONING.md §1). A server that predates the endpoint is represented
/// by [ServerInfoDto.legacy] — its version is unknown and its level is 0.
class ServerInfoDto {
  /// The server's release version, e.g. `1.3.0` or `1.3.0+4.gabc1234`.
  /// Null for a legacy server, which never reports one.
  final String? version;
  final int apiLevel;
  final int minAppApiLevel;

  const ServerInfoDto({
    required this.version,
    required this.apiLevel,
    required this.minAppApiLevel,
  });

  static const legacy = ServerInfoDto(
    version: null,
    apiLevel: kLegacyServerApiLevel,
    minAppApiLevel: 0,
  );

  bool get isLegacy => version == null;

  ServerCompatibility get compatibility => assessCompatibility(
    serverApiLevel: apiLevel,
    serverMinAppApiLevel: minAppApiLevel,
  );

  /// Tolerant by design (docs/VERSIONING.md §3.3): a missing or mistyped
  /// field falls back to the legacy value rather than throwing.
  factory ServerInfoDto.fromJson(Map<String, dynamic> json) => ServerInfoDto(
    version: switch (json['version']) {
      final String version => version,
      _ => 'unknown',
    },
    apiLevel: switch (json['api_level']) {
      final num level => level.toInt(),
      _ => kLegacyServerApiLevel,
    },
    minAppApiLevel: switch (json['min_app_api_level']) {
      final num level => level.toInt(),
      _ => 0,
    },
  );
}
