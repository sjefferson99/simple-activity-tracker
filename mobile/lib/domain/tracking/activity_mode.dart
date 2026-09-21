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
  cycling,
  // Issue #129: a tag distinct from running so walks can be filtered/
  // analyzed separately in future — deliberately identical to running in
  // every other respect (plausibility thresholds, splits, tiles) until a
  // walk-specific need actually shows up.
  walking;

  String get label => switch (this) {
        ActivityMode.running => 'Run',
        ActivityMode.cycling => 'Cycle',
        ActivityMode.walking => 'Walk',
      };

  /// Whether this mode's UI and recorded GPX include split-plan data.
  /// Cycling hides splits entirely (issue #99 D8) — anything gated on this
  /// must not surface a running-configured split plan while cycling.
  bool get supportsSplits =>
      this == ActivityMode.running || this == ActivityMode.walking;
}
