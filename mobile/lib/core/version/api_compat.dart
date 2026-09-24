/// App <-> server compatibility levels — see docs/VERSIONING.md §2.
///
/// Pure Dart: decisions about what the app may send or call are made from
/// these integers and the server's reported level, never from release
/// version strings.
library;

/// The server API level this app was built against. Always equal to the
/// server's `API_LEVEL` in the same commit (`server/app/api_compat.py`) —
/// test/core/version/api_compat_test.dart fails if they drift.
const kAppApiLevel = 1;

/// The oldest server API level this app still supports. Raise it only when
/// deliberately dropping support for older servers — every server release so
/// far (level 0 included) must keep working until then.
const kMinServerApiLevel = 0;

/// The level assumed for a server that predates `GET /api/v1/server-info`
/// (every release up to v1.2.4). Also the safe fallback whenever the level
/// can't be determined: level 0 is what every server accepts.
const kLegacyServerApiLevel = 0;

/// First API level at which each capability exists. The app gates on these
/// (`serverApiLevel >= ...`) rather than on literal numbers scattered around.
abstract final class ApiLevels {
  /// Upload summary accepts `max_speed_mps`, `elevation_gain_meters` and
  /// split `target_speed_mps`; `/server-info` exists; unknown request
  /// fields are ignored rather than rejected.
  static const uploadExtendedStats = 1;
}

enum ServerCompatibility {
  /// Within each other's supported range.
  compatible,

  /// The server no longer supports an app this old — update the app.
  appTooOld,

  /// This app no longer supports a server this old — update the server.
  serverTooOld,
}

ServerCompatibility assessCompatibility({
  required int serverApiLevel,
  required int serverMinAppApiLevel,
  int appApiLevel = kAppApiLevel,
  int minServerApiLevel = kMinServerApiLevel,
}) {
  if (appApiLevel < serverMinAppApiLevel) return ServerCompatibility.appTooOld;
  if (serverApiLevel < minServerApiLevel) return ServerCompatibility.serverTooOld;
  return ServerCompatibility.compatible;
}
