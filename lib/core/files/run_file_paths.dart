import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// Returns the file a new run should be logged to:
/// `<appDocuments>/runs/run_YYYY-MM-DD_HHmm.gpx`, creating the `runs`
/// directory if needed.
Future<File> newRunGpxFile(DateTime startedAt) async {
  final documentsDir = await getApplicationDocumentsDirectory();
  final runsDir = Directory('${documentsDir.path}/runs');
  await runsDir.create(recursive: true);

  final name = 'run_'
      '${startedAt.year.toString().padLeft(4, '0')}-'
      '${startedAt.month.toString().padLeft(2, '0')}-'
      '${startedAt.day.toString().padLeft(2, '0')}_'
      '${startedAt.hour.toString().padLeft(2, '0')}'
      '${startedAt.minute.toString().padLeft(2, '0')}'
      '.gpx';

  return File('${runsDir.path}/$name');
}
