import 'dart:math' as math;

/// Readings this close before a fix are averaged into it. Running in a
/// pocket, single readings scatter ~0.5 m from footstrike and pumping (vs
/// ~0.15 m at rest), so the sensor is sampled fast and each fix gets the
/// mean of its last second instead of one reading (issue #184).
const Duration pressureAveragingWindow = Duration(seconds: 1);

/// A platform that reports more slowly than the window (iOS's CMAltimeter
/// picks its own rate) falls back to its latest reading, if it's no older
/// than this. Older than that, the sensor has stopped reporting and the fix
/// is logged without pressure.
const Duration maxPressureReadingAge = Duration(seconds: 3);

/// The pressure logged with one fix. [sdHpa] is the spread of the readings
/// averaged into [hpa] — how disturbed the barometer is right now (pocket
/// pumping, wind), which the elevation filter can weigh it by
/// (docs/BAROMETER-PLAN.md). Null when fewer than two readings were averaged.
typedef PressureReading = ({double hpa, double? sdHpa});

/// Collects barometer readings so each GPS fix can carry the pressure
/// around it into the GPX log (issue #184).
class PressureWindow {
  final List<({double hpa, DateTime at})> _readings = [];

  void add(double hpa, DateTime receivedAt) {
    _readings.add((hpa: hpa, at: receivedAt));
    _readings.removeWhere(
      (r) => receivedAt.difference(r.at) > maxPressureReadingAge,
    );
  }

  /// The mean of the readings in the [pressureAveragingWindow] before [now],
  /// else the latest reading if it's recent enough, else null.
  PressureReading? at(DateTime now) {
    final recent = [
      for (final r in _readings)
        if (now.difference(r.at) <= pressureAveragingWindow) r.hpa,
    ];
    if (recent.isNotEmpty) {
      final mean = recent.reduce((a, b) => a + b) / recent.length;
      final sd = recent.length < 2
          ? null
          : math.sqrt(
              recent
                      .map((x) => (x - mean) * (x - mean))
                      .reduce((a, b) => a + b) /
                  recent.length,
            );
      return (hpa: mean, sdHpa: sd);
    }
    if (_readings.isEmpty) return null;
    final latest = _readings.last;
    return now.difference(latest.at) <= maxPressureReadingAge
        ? (hpa: latest.hpa, sdHpa: null)
        : null;
  }

  void reset() => _readings.clear();
}
