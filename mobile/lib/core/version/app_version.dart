import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';

/// The placeholder `version:` in pubspec.yaml. Release builds replace it
/// with the tag's version (`--build-name`, mobile-release.yml), so seeing it
/// at runtime means a local/dev build — docs/VERSIONING.md §1.
const _placeholderVersion = '0.0.0';

/// This app build's release version, for display and the `X-App-Version`
/// request header. Never used for compatibility decisions — see
/// core/version/api_compat.dart for those.
class AppVersion {
  /// `1.3.0`, from the release tag — or the pubspec placeholder in a dev build.
  final String version;
  final String buildNumber;

  const AppVersion({required this.version, required this.buildNumber});

  bool get isDevBuild => version == _placeholderVersion;

  /// `1.3.0` for a release, `dev build` otherwise.
  String get display => isDevBuild ? 'dev build' : version;

  /// `1.3.0+57` — pubspec's version+build format, sent as the upload's
  /// `source.app_version` and the `X-App-Version` header.
  String get full => '$version+$buildNumber';

  static Future<AppVersion> fromPlatform() async {
    final info = await PackageInfo.fromPlatform();
    return AppVersion(version: info.version, buildNumber: info.buildNumber);
  }
}

/// Cached for the app's lifetime — the running build can't change.
final appVersionProvider = FutureProvider<AppVersion>((ref) => AppVersion.fromPlatform());
