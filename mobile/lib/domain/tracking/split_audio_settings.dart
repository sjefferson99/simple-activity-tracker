/// The user's audio-cue preferences for a live run (issue #125): one toggle
/// per cue type, so e.g. someone who wants the beeps but finds spoken
/// announcements too chatty (or vice versa) can turn off just that piece.
/// Pure Dart, persisted by [SplitAudioSettingsController] the same way
/// [SplitPlan] is persisted by `SplitPlanController`.
///
/// There is deliberately no separate master on/off — audio cues are "on"
/// whenever any of the four toggles below is, which [anyEnabled] expresses;
/// a fifth switch that only gated the other four added a step with no real
/// choice behind it (issue #125 follow-up, 2026-09-21).
class SplitAudioSettings {
  /// Beep once when a new split starts (including the very first, on Start
  /// — see `LiveRunController`'s start-of-activity cue).
  final bool beepOnSplitChange;

  /// Beep pattern (2/3/1-long) on a target-verdict transition — too fast,
  /// too slow, or back on target. Meaningless with no target configured, but
  /// harmless to leave on; the cue simply never fires without a target since
  /// [splitVerdict] itself returns null with no target.
  final bool beepOnVerdictChange;

  /// Speak the current split's target pace/speed whenever a split starts
  /// (including the very first, on Start) — e.g. "Target 5 kilometres per
  /// hour", or "No target." with none configured. Renamed from
  /// announceSplitStats (issue #125 follow-up, 2026-09-21): the original
  /// end-of-split "average pace so far" summary was replaced with an
  /// announcement of what's coming up, not what just happened — this
  /// toggle's name follows that behaviour change.
  final bool announceSplitTarget;

  /// Speak the too-fast/too-slow verdict, by how much, and the target being
  /// judged against (e.g. "Pace is 2 minutes per kilometre too slow, target
  /// pace is 5 minutes per kilometre."), or "Back on target." with no target
  /// restated.
  final bool announceVerdictCorrection;

  const SplitAudioSettings({
    required this.beepOnSplitChange,
    required this.beepOnVerdictChange,
    required this.announceSplitTarget,
    required this.announceVerdictCorrection,
  });

  /// Off by default, so an existing install doesn't suddenly start beeping
  /// after an app update the user didn't ask for. Once any toggle is turned
  /// on, the others default the same way they always have.
  static const defaultSettings = SplitAudioSettings(
    beepOnSplitChange: false,
    beepOnVerdictChange: false,
    announceSplitTarget: false,
    announceVerdictCorrection: false,
  );

  /// Whether either beep toggle is on — drives both the split-changed beep
  /// and the start-of-activity confirmation beep (issue #125 follow-up):
  /// the start cue's beep fires whenever a beep would ever fire during the
  /// run, so it's a meaningful preview rather than a separate setting.
  bool get anyBeepEnabled => beepOnSplitChange || beepOnVerdictChange;

  /// Whether either speech toggle is on — same reasoning as [anyBeepEnabled],
  /// for the start-of-activity target announcement.
  bool get anySpeechEnabled => announceSplitTarget || announceVerdictCorrection;

  /// Whether any cue at all would ever fire this run — the single gate
  /// [LiveRunController] checks before doing any audio work, replacing the
  /// old separate master toggle.
  bool get anyEnabled => anyBeepEnabled || anySpeechEnabled;

  SplitAudioSettings copyWith({
    bool? beepOnSplitChange,
    bool? beepOnVerdictChange,
    bool? announceSplitTarget,
    bool? announceVerdictCorrection,
  }) => SplitAudioSettings(
    beepOnSplitChange: beepOnSplitChange ?? this.beepOnSplitChange,
    beepOnVerdictChange: beepOnVerdictChange ?? this.beepOnVerdictChange,
    announceSplitTarget: announceSplitTarget ?? this.announceSplitTarget,
    announceVerdictCorrection:
        announceVerdictCorrection ?? this.announceVerdictCorrection,
  );

  Map<String, Object?> toJson() => {
    'beepOnSplitChange': beepOnSplitChange,
    'beepOnVerdictChange': beepOnVerdictChange,
    'announceSplitTarget': announceSplitTarget,
    'announceVerdictCorrection': announceVerdictCorrection,
  };

  /// Parses a previously-persisted value, or null if malformed — callers
  /// fall back to [defaultSettings] on null, same convention as
  /// `SplitPlan.fromJson`. A pre-existing stored value from before this
  /// field's rename (`announceSplitStats` — issue #125 follow-up,
  /// 2026-09-21) parses as if that toggle had been off, same as any other
  /// unrecognized/missing key — everything else round-trips unaffected,
  /// since every field here is looked up by name, not position.
  static SplitAudioSettings? fromJson(Map<String, Object?> json) {
    try {
      return SplitAudioSettings(
        beepOnSplitChange: json['beepOnSplitChange']! as bool,
        beepOnVerdictChange: json['beepOnVerdictChange']! as bool,
        announceSplitTarget: json['announceSplitTarget'] as bool? ?? false,
        announceVerdictCorrection: json['announceVerdictCorrection']! as bool,
      );
    } catch (_) {
      return null;
    }
  }

  @override
  bool operator ==(Object other) =>
      other is SplitAudioSettings &&
      other.beepOnSplitChange == beepOnSplitChange &&
      other.beepOnVerdictChange == beepOnVerdictChange &&
      other.announceSplitTarget == announceSplitTarget &&
      other.announceVerdictCorrection == announceVerdictCorrection;

  @override
  int get hashCode => Object.hash(
    beepOnSplitChange,
    beepOnVerdictChange,
    announceSplitTarget,
    announceVerdictCorrection,
  );
}
