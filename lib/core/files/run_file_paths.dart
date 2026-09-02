import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// Returns the file a new run should be logged to:
/// `<appDocuments>/runs/run_YYYY-MM-DD_HHmmss.gpx`, creating the `runs`
/// directory if needed. If that name is already taken (two runs started in
/// the same second), a `_2`, `_3`, … suffix is appended so a previous run's
/// track is never overwritten.
Future<File> newRunGpxFile(DateTime startedAt) async {
  final documentsDir = await getApplicationDocumentsDirectory();
  final runsDir = Directory('${documentsDir.path}/runs');
  await runsDir.create(recursive: true);

  final stamp = 'run_'
      '${startedAt.year.toString().padLeft(4, '0')}-'
      '${startedAt.month.toString().padLeft(2, '0')}-'
      '${startedAt.day.toString().padLeft(2, '0')}_'
      '${startedAt.hour.toString().padLeft(2, '0')}'
      '${startedAt.minute.toString().padLeft(2, '0')}'
      '${startedAt.second.toString().padLeft(2, '0')}';

  var file = File('${runsDir.path}/$stamp.gpx');
  var attempt = 1;
  while (await file.exists()) {
    attempt++;
    file = File('${runsDir.path}/${stamp}_$attempt.gpx');
  }

  return file;
}
