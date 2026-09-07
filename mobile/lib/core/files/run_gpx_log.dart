import 'dart:io';

import 'package:gpx/gpx.dart';

import '../../domain/models/track_point.dart';

/// Namespace for this app's own per-point GPX extensions (accuracy/speed
/// diagnostics — see [RunGpxLog.addPoint]). A plain, unregistered URI is
/// fine: nothing resolves it, it just has to be unique enough not to clash
/// with a real extension schema. Unknown extensions are ignored by both the
/// `gpx` package's own reader and the server's `gpxpy`-based parser, so
/// adding these never breaks reading a file back.
const String _extensionsNamespaceUri =
    'https://simple-activity-tracker.local/gpx-extensions';
const String _extensionsPrefix = 'sat';

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

  /// Chains flushes so a periodic flush and the final one can never write
  /// the same temp file concurrently and clobber each other's rename.
  Future<void> _pendingFlush = Future.value();

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
    _currentSegment!.trkpts.add(
      Wpt(
        lat: point.latitude,
        lon: point.longitude,
        ele: point.elevationMeters,
        time: point.timestamp,
        // Diagnostic-only extensions (docs/GPS-METRICS-PLAN.md step 1): the
        // values MetricsEngine's acceptance gates actually decide on, which
        // a plain lat/lon/ele/time GPX otherwise has no way to show. Written
        // as strings — the `gpx` package's own extension map round-trips
        // element text as strings on read, not typed values.
        extensions: {
          '$_extensionsPrefix:accuracy': '${point.accuracyMeters}',
          '$_extensionsPrefix:has_accuracy': '${point.hasAccuracy}',
          if (point.speedMps != null)
            '$_extensionsPrefix:speed': '${point.speedMps}',
          '$_extensionsPrefix:has_speed': '${point.hasSpeed}',
        },
      ),
    );
  }

  /// Serializes the current track to a temp file and atomically renames it
  /// over the target file. Concurrent calls are queued rather than run in
  /// parallel, so they cannot race on the shared temp path.
  Future<void> flush() {
    final result = _pendingFlush.then((_) => _writeSnapshot());
    // The chain itself must stay un-failed, otherwise one bad write would
    // make every later flush inherit that error. Callers still see it.
    _pendingFlush = result.catchError((_) {});
    return result;
  }

  Future<void> _writeSnapshot() async {
    final gpx = Gpx()
      ..creator = 'Simple Activity Tracker'
      ..trks = [_track];
    final xml = GpxWriter().asString(
      gpx,
      pretty: true,
      compatibility: GpxCompatibilityMode.gpx11,
      namespaces: const {_extensionsPrefix: _extensionsNamespaceUri},
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
