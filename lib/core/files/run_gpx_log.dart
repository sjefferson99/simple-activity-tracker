import 'dart:io';

import 'package:gpx/gpx.dart';

import '../../domain/models/track_point.dart';

/// Builds a GPX 1.1 track for one run and flushes it to disk incrementally.
///
/// Crash safety: every [flush] serializes the *entire* accumulated track
/// (cheap at run-length point counts) to a temp file, then renames it over
/// the target file. A rename is atomic on the filesystems Android and iOS
/// use, so a crash mid-write never leaves a corrupt or half-written GPX
/// file — the previous flush's file stays valid until the new one lands.
class RunGpxLog {
  final File _targetFile;
  final Trk _track = Trk();
  Trkseg? _currentSegment;

  RunGpxLog(this._targetFile) {
    _startNewSegment();
  }

  /// Starts a fresh track segment — call on resume after a pause, so the
  /// paused gap isn't rendered as a single continuous segment.
  void startNewSegment() => _startNewSegment();

  void _startNewSegment() {
    final segment = Trkseg();
    _currentSegment = segment;
    _track.trksegs.add(segment);
  }

  void addPoint(TrackPoint point) {
    _currentSegment!.trkpts.add(Wpt(
      lat: point.latitude,
      lon: point.longitude,
      ele: point.elevationMeters,
      time: point.timestamp,
    ));
  }

  /// Serializes the current track to a temp file and atomically renames it
  /// over the target file.
  Future<void> flush() async {
    final gpx = Gpx()
      ..creator = 'Simple Runner'
      ..trks = [_track];
    final xml = GpxWriter().asString(
      gpx,
      pretty: true,
      compatibility: GpxCompatibilityMode.gpx11,
    );

    final tempFile = File('${_targetFile.path}.tmp');
    await tempFile.writeAsString(xml, flush: true);
    await tempFile.rename(_targetFile.path);
  }

  /// Drops any track segments that never received a point (e.g. a
  /// pause/resume with no motion in between) before the final flush.
  Future<void> finalizeAndFlush() async {
    _track.trksegs.removeWhere((segment) => segment.trkpts.isEmpty);
    await flush();
  }
}
