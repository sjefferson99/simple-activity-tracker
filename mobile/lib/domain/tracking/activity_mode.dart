/// Which activity a run's GPS plausibility checks are tuned for. Selected on
/// the home screen before a run starts (not hidden in Settings, since it
/// changes how the run is captured, not just how it's displayed) and fixed
/// for the run's duration.
///
/// For now this only changes [MetricsEngine]'s error-correction thresholds —
/// what counts as a plausible GPS segment versus a bad fix to discard. It
/// deliberately does **not** yet change displayed metrics or the km/h ⇄
/// min/km toggle; that follows once the gap-tolerance logic itself has been
/// validated against real cycling tracks.
enum ActivityMode {
  running,
  cycling;

  String get label => switch (this) {
        ActivityMode.running => 'Run',
        ActivityMode.cycling => 'Cycle',
      };
}
