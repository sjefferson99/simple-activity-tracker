import 'dart:io';

import 'package:media_store_plus/media_store_plus.dart';
import 'package:path_provider/path_provider.dart';

/// Copies a finished run's GPX file into public storage on Android, so it
/// shows up over USB and in the on-device file browser without the user
/// needing to dig into the app's private sandbox.
///
/// iOS doesn't have an equivalent "public shared storage" — the app's own
/// Documents folder is already made visible to the Files app instead (see
/// UIFileSharingEnabled / LSSupportsOpeningDocumentsInPlace in Info.plist),
/// so this is a no-op there.
class RunExportService {
  static const _appFolder = 'SimpleActivityTracker';

  static Future<void> ensureInitialized() async {
    if (!Platform.isAndroid) return;
    await MediaStore.ensureInitialized();
    MediaStore.appFolder = _appFolder;
  }

  /// Returns the human-readable location the file was saved to (for showing
  /// in the UI), or null if export isn't applicable on this platform or the
  /// copy failed. The original file is left in place either way — this is a
  /// copy, not a move, so the app's own record of the run is never at risk.
  Future<String?> exportToPublicStorage(File gpxFile) async {
    if (!Platform.isAndroid) return null;

    // saveFile() deletes whatever it's pointed at once the copy lands in
    // MediaStore — handing it gpxFile directly would destroy the app's own
    // record of the run. Hand it a throwaway copy instead. The microsecond
    // prefix keeps two exports from ever sharing a scratch path — nothing
    // in this class enforces one-export-at-a-time, so this is cheap
    // insurance against one call's cleanup deleting another's in-flight file.
    final scratch = File(
      '${(await getTemporaryDirectory()).path}/${DateTime.now().microsecondsSinceEpoch}_${gpxFile.uri.pathSegments.last}',
    );

    try {
      await gpxFile.copy(scratch.path);
      final info = await MediaStore().saveFile(
        tempFilePath: scratch.path,
        dirType: DirType.download,
        dirName: DirName.download,
      );
      return info == null ? null : 'Downloads/$_appFolder';
    } on Object {
      // Export is a convenience on top of the run already being safely
      // recorded in app storage — never let a failure here surface as a
      // failed run. Catches Error subtypes too (e.g. a plugin-internal
      // StateError), not just Exception, so this guarantee actually holds.
      return null;
    } finally {
      if (await scratch.exists()) await scratch.delete();
    }
  }
}
