import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/app.dart';
import 'core/display/orientation_lock_settings.dart';
import 'core/files/run_export_service.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Export is a convenience layered on top of run tracking, not a
  // prerequisite for it — if the plugin's platform-channel init ever throws
  // (a bad install, an OS quirk), that must not stop the app from launching.
  try {
    await RunExportService.ensureInitialized();
  } on Object {
    // ignore: nothing to do here — exportToPublicStorage() checks its own
    // preconditions and simply returns null if initialization never ran.
  }
  // Same reasoning: a failed read just means the app follows the phone's
  // rotation until the Settings provider's own load applies the lock.
  try {
    await applyStoredPortraitLock();
  } on Object {
    // ignore: the app root re-applies the setting on every change.
  }
  runApp(const ProviderScope(child: SimpleActivityTrackerApp()));
}
