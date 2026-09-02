import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app/app.dart';
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
  runApp(const ProviderScope(child: SimpleRunnerApp()));
}
