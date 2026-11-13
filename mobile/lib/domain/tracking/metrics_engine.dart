import '../geo_math.dart';
import '../models/current_split_info.dart';
import '../models/live_metrics.dart';
import '../models/split.dart';
import '../models/track_point.dart';
import 'activity_mode.dart';
import 'elevation_accumulator.dart';
import 'run_clock.dart';
import 'split_plan.dart';
import 'split_preference.dart';

const double _maxAcceptableAccuracyMeters = 25;

/// The two plausibility thresholds [MetricsEngine] checks every accepted
/// segment against — see [MetricsEngine._isPlausibleSegment]. Per-[ActivityMode]
/// because a cyclist routinely exceeds a runner's plausible speed and can
/// cover far more distance in a sparse-fix gap (freewheeling downhill, a
/// tunnel) without it being a GPS glitch.
class _PlausibilityLimits {
  /// No one sustains this for the given activity; a segment implying more is
  /// a bad fix (e.g. a stale/default location before the GPS gets a real
  /// lock), not real motion.
  final double maxPlausibleSpeedMps;

  /// Backstop for the "a long enough gap makes anything look slow" hole in a
  /// speed-only test: a 65km jump implies a plausible ~18 m/s once the
  /// previous fix is an hour old. Set well above any distance a
  /// sparse-but-real stretch of fixes could cover (a tunnel or a
  /// backgrounded app can easily leave kilometres between consecutive
  /// fixes), so this only catches teleports.
  final double maxPlausibleSegmentMeters;

  const _PlausibilityLimits({
    required this.maxPlausibleSpeedMps,
    required this.maxPlausibleSegmentMeters,
  });

  factory _PlausibilityLimits.forMode(ActivityMode mode) => switch (mode) {
    // Walking is tagged separately from running (issue #129) but shares its
    // GPS plausibility thresholds — a walker is well within a runner's cap,
    // so there's no reason to tighten or loosen this for walking specifically.
    ActivityMode.running || ActivityMode.walking => const _PlausibilityLimits(
      maxPlausibleSpeedMps: 12, // ~43 km/h
      maxPlausibleSegmentMeters: 20000,
    ),
    // Downhill cycling comfortably exceeds a runner's cap, and a bike can
    // cover much more ground than a runner in the same sparse-fix gap —
    // both thresholds raised accordingly. Still well short of "obviously
    // not a bike" (a car, a plane) so genuine teleports are still caught.
    ActivityMode.cycling => const _PlausibilityLimits(
      maxPlausibleSpeedMps: 25, // 90 km/h
      maxPlausibleSegmentMeters: 40000,
    ),
  };
}

/// How long a rejected fix stays eligible to be recognised as the real
/// position (see the recovery path in [MetricsEngine.addPoint]). Beyond this
/// the run is treated as having a genuine gap rather than a recoverable
/// glitch, so a stale candidate can't be resurrected minutes later.
const Duration _pendingCandidateTtl = Duration(seconds: 30);

/// How far two rejected fixes must be apart before they count as evidence
/// that the runner really is over there, rather than a GPS repeating one
/// wrong position. Above plausible fix-to-fix noise, below a running stride's
/// worth of travel between fixes.
const double _minReanchorMotionMeters = 2;

/// Below this, a segment is treated as GPS noise rather than motion — the
/// **fallback** stationary test for when a fix carries no usable chip speed
/// (see [_StationaryDetector]). Indoors, reflected/multipath fixes routinely
/// wander between updates while the phone is completely stationary; that
/// wander implies a low but non-zero speed, comfortably inside even running
/// mode's plausibility cap, so the teleport-oriented checks never catch it.
/// Deliberately a small fixed floor rather than a multiple of reported
/// accuracy: accuracy on consumer GPS is itself an unreliable estimate
/// indoors (often overconfident), so scaling off it would let exactly the
/// wander this is meant to catch back in.
///
/// #49: originally 3m, but real on-device capture of an ordinary walk
/// (~1.7 m/s, ~1s fixes) showed almost every real step is *itself* under 3m
/// — the floor was silently swallowing genuine walking pace, not just GPS
/// noise. Lowered to 1.2m: comfortably credits that walk's real segments
/// (only a small fraction still fall under 1.2m) while a separate near-
/// stationary capture stayed at exactly zero distance down to 1.0m.
const double _noiseFloorMeters = 1.2;

/// The chip-speed stationary gate (docs/GPS-METRICS-PLAN.md step 3a).
///
/// A segment's *position-implied* speed can't tell genuine drift (indoor
/// multipath ramping the reported position while the phone doesn't move)
/// apart from a genuine turnaround — both have long stretches where every
/// individual hop is small and plausible. But GNSS Doppler speed comes from
/// carrier frequency shift, not from successive position fixes, so multipath
/// that moves the *position* does not produce a matching *speed*: real
/// on-device captures show stationary/indoor chip speed at 0.0–0.2 m/s
/// (occasionally spiking to several m/s for one noisy fix) while real
/// walking sits solidly at 0.9–1.35 m/s and jogging at 1.2–2.3 m/s, with no
/// overlap between the two once hysteresis absorbs the odd stray reading.
///
/// [_enterMovingMps] and [_exitMovingMps] are deliberately different, and
/// entering "moving" deliberately needs [_enterConfirmFixes] *consecutive*
/// fixes at/above the enter threshold, not just one: real on-device capture
/// showed the noise this gate exists for isn't always a single clean spike —
/// one stationary blip rang for two consecutive fixes (4.32, then 4.34 m/s)
/// before decaying back down through 0.71 and 0.62 m/s over the next two.
/// A 2-fix confirmation still let ~5m of that ringing through; 3 fixes
/// rejects it almost entirely (tested against real captures: ~1m credited
/// from a 69s stationary indoor capture, vs. ~230m correctly retained from a
/// real walk/jog) at the cost of a ~2-3s lag recognising a genuine walk-off,
/// an acceptable trade for a live tracker. Dropping below the lower exit bar
/// stops crediting immediately (no confirmation needed) so pace jitter right
/// at walking speed doesn't flicker distance on/off mid-stride once already
/// moving. Values chosen from real captures with clear headroom either side,
/// not intended as an exact physiological threshold — see
/// docs/GPS-METRICS-PLAN.md step 1's capture data.
class _StationaryDetector {
  static const double _enterMovingMps = 0.6;
  static const double _exitMovingMps = 0.4;
  static const int _enterConfirmFixes = 3;

  bool _isMoving = false;

  /// Consecutive fixes at/above [_enterMovingMps] seen while not yet moving.
  int _aboveEnterStreak = 0;

  /// Whether [point] (with chip speed [speedMps], trustworthy only when
  /// [hasSpeed]) should credit its segment as motion. Falls back to the
  /// position-based [_noiseFloorMeters] check against [segmentDistance] when
  /// the platform gave no usable speed for this fix — see
  /// [LocationSample.hasSpeed]'s doc for why a platform-reported `0.0` can't
  /// always be trusted as a real measurement.
  bool accepts({
    required bool hasSpeed,
    required double? speedMps,
    required double segmentDistance,
  }) {
    if (!hasSpeed || speedMps == null) {
      return segmentDistance >= _noiseFloorMeters;
    }
    // The verdict this segment is judged by is whatever was true *before*
    // this fix updates it — a fix that completes the confirmation streak
    // confirms the *next* segment as moving, not the one ending on itself.
    final wasMoving = _isMoving;
    if (wasMoving) {
      if (speedMps < _exitMovingMps) {
        _isMoving = false;
        _aboveEnterStreak = 0;
      }
    } else {
      _aboveEnterStreak = speedMps >= _enterMovingMps
          ? _aboveEnterStreak + 1
          : 0;
      if (_aboveEnterStreak >= _enterConfirmFixes) {
        _isMoving = true;
      }
    }
    return wasMoving;
  }

  /// Resets to "not moving" — call alongside [MetricsEngine.resetSegmentAnchor]
  /// so a pause/re-anchor doesn't inherit a stale moving/stationary verdict.
  void reset() {
    _isMoving = false;
    _aboveEnterStreak = 0;
  }
}

/// Accumulates accepted track points into live run metrics: elapsed time,
/// distance, current/average speed, and interpolated 1km splits.
///
/// Pure Dart, no Flutter dependency — fed one point at a time via [addPoint]
/// so it never has to recompute a whole run's history from scratch.
///
/// [mode] only affects which GPS segments are accepted as plausible motion
/// versus discarded as a bad fix — see [_PlausibilityLimits]. It does not
/// yet change how metrics are computed or displayed.
///
/// **Two clocks (issue #161).** Splits are measured on the run's *elapsed*
/// clock — [RunClock]: wall-clock since Start, stopped only by an explicit
/// pause — the same clock as the "Time" tile, so completed splits plus the
/// split in progress always add up to Time exactly, and a 5-minute split
/// is five minutes on any stopwatch. Nothing the GPS filters decide (a
/// stationary verdict, a dropped or implausible fix) ever takes time out of
/// a split; only distance is filtered. Moving time ([LiveMetrics.elapsed])
/// is kept separately, for average pace and the server's `moving_seconds`.
class MetricsEngine {
  final _PlausibilityLimits _limits;

  /// The split plan this run is measured against — read once at
  /// construction, same as [mode]: a mid-run preference change (disabled in
  /// the UI, but this is the actual guarantee) can't affect an in-progress
  /// run. Whether splits are sized by distance (km/mi) or duration (minutes)
  /// comes from [SplitPlan.base]'s kind, never both.
  final SplitPlan _plan;
  final bool _isTimeMode;

  /// The run's elapsed clock, shared with the caller, which pauses and
  /// resumes it. Null until the first point when none was given: a
  /// standalone engine (tests, replay tools) then starts its own clock at
  /// the first fix and, never being paused, counts every gap as elapsed.
  RunClock? _clock;

  MetricsEngine({
    ActivityMode mode = ActivityMode.running,
    SplitPlan splitPlan = SplitPlan.defaultPlan,
    SplitPreference? splitPreference,
    RunClock? clock,
  }) : _clock = clock,
       _limits = _PlausibilityLimits.forMode(mode),
       // splitPreference is kept as a convenience wrapper for callers/tests
       // that only need a rolling plan — it wins over splitPlan if both are
       // given, which should never happen outside a test double.
       _plan = splitPreference != null
           ? SplitPlan(base: splitPreference)
           : splitPlan,
       _isTimeMode = (splitPreference ?? splitPlan.base).kind == SplitKind.timeMin;

  final _StationaryDetector _stationaryDetector = _StationaryDetector();
  TrackPoint? _lastAccepted;

  /// A point rejected as an implausible jump from [_lastAccepted], kept in
  /// case it turns out [_lastAccepted] was the bad fix rather than this one —
  /// see [addPoint].
  TrackPoint? _pendingCandidate;

  Duration _movingElapsed = Duration.zero;
  double _totalDistanceMeters = 0;

  /// The latest point on the run's elapsed timeline the engine has seen,
  /// from a fix's timestamp or [advanceTo] — what [LiveMetrics.
  /// elapsedWallClock] reports and the split in progress is timed against.
  Duration _latestRunTime = Duration.zero;

  /// No fix is placed earlier than this on the run timeline: the run time
  /// at the last [resetSegmentAnchor], so a stale fix delivered just after
  /// a resume can't land before the pause it followed.
  Duration _runTimeFloor = Duration.zero;

  double _splitStartDistanceMeters = 0;

  /// Where the split in progress started, on the run's elapsed timeline.
  Duration _splitStartRunTime = Duration.zero;
  final List<Split> _completedSplits = [];

  /// Where each completed split ended on the elapsed timeline, parallel to
  /// [_completedSplits] — what [_creditTimeMode] needs to share a late fix's
  /// distance back into a split the clock already closed.
  final List<Duration> _splitEndRunTimes = [];

  double? _maxSpeedMps;
  final ElevationAccumulator _elevation = ElevationAccumulator();

  /// Metrics as of the latest fix or [advanceTo], whichever was later.
  LiveMetrics get metrics =>
      _clock == null ? LiveMetrics.zero : _buildMetrics();

  /// Moves the run's elapsed clock on to [now] without a fix, so a time-kind
  /// split closes on the clock (and its countdown keeps moving) even when no
  /// fix arrives — call on every UI tick. A no-op for a standalone engine
  /// that hasn't seen a fix yet, as its clock starts at the first one.
  void advanceTo(DateTime now) {
    if (_clock == null) return;
    _advanceRunTime(_runTimeOf(now));
  }

  /// [now] placed on the run's elapsed timeline (pauses excluded), starting
  /// a standalone engine's own clock on first use.
  Duration _runTimeOf(DateTime now) {
    final clock = _clock ??= RunClock(startedAt: now);
    final value = clock.elapsed(now);
    return value < _runTimeFloor ? _runTimeFloor : value;
  }

  void _advanceRunTime(Duration runTime) {
    if (runTime <= _latestRunTime) return;
    _latestRunTime = runTime;
    if (_isTimeMode) _closeTimeSplitsUpTo(runTime);
  }

  /// Feeds one more accepted GPS fix into the engine. A point is dropped
  /// entirely if [TrackPoint.hasAccuracy] is false — an unmeasured accuracy
  /// value is not the same as a perfect one, and would otherwise sail
  /// straight through the accuracy-radius check below — or if its accuracy
  /// is worse than [_maxAcceptableAccuracyMeters]. Call site should not call
  /// this for paused/rejected points.
  void addPoint(TrackPoint point) {
    // Time moves on with every fix, however it's judged below: the filters
    // decide only what distance counts, never how long a split lasts.
    _advanceRunTime(_runTimeOf(point.timestamp));

    if (!point.hasAccuracy) return;
    if (point.accuracyMeters > _maxAcceptableAccuracyMeters) return;

    // Every accuracy-accepted fix, moving or not — the same fixes the GPX
    // log holds and the server's analysis replays, so the two agree
    // (ElevationAccumulator's doc). Stationary jitter is what the
    // accumulator's dead-band is for.
    _elevation.add(point.timestamp, point.elevationMeters);

    final previous = _lastAccepted;

    if (previous == null) {
      _lastAccepted = point;
      return;
    }

    final segmentDistance = haversineDistanceMeters(previous, point);
    final segmentDuration = point.timestamp.difference(previous.timestamp);
    if (segmentDuration <= Duration.zero) {
      return;
    }

    // A jump implying an impossible running speed is a bad fix (GPS glitch,
    // stale location before a real lock), not real motion — drop it like a
    // low-accuracy point rather than let it poison cumulative distance/speed
    // forever.
    if (!_isPlausibleSegment(segmentDistance, segmentDuration)) {
      // But keeping the anchor pinned on `previous` forever is just as wrong
      // if `previous` was actually the bad fix (e.g. one stale point far from
      // where the run really is) — every subsequent good point would then
      // look like an impossible jump and be rejected too, quarantining the
      // rest of the run. Two consecutive rejects that agree with *each other*
      // say the anchor was the outlier, so re-anchor onto them.
      final pending = _pendingCandidate;
      final sincePending = pending == null
          ? null
          : point.timestamp.difference(pending.timestamp);
      final pendingDistance = pending == null
          ? null
          : haversineDistanceMeters(pending, point);
      // Agreement has to be *evidence*, not merely an absence of
      // contradiction. A GPS stuck on one wrong position repeats it exactly:
      // those duplicates imply 0 m/s, trivially "agree", and would hand the
      // anchor to the bad location. Requiring the pair to show real movement
      // means only a fix that is genuinely tracking the runner can re-anchor.
      final agreesWithPending =
          pending != null &&
          sincePending! <= _pendingCandidateTtl &&
          pendingDistance! >= _minReanchorMotionMeters &&
          _isPlausibleSegment(pendingDistance, sincePending);

      if (agreesWithPending) {
        // How the runner got from `previous` to here is unknown — the jump
        // between them is exactly the thing being rejected — so this is a
        // discontinuity, not a segment. Re-anchor without crediting any
        // distance or time, the same way a pause/resume does. Crediting the
        // pending->point leg instead would bank a bad-fix cluster's own
        // drift as real running.
        _resetAnchorTo(point);
      } else {
        _pendingCandidate = point;
      }
      return;
    }

    _pendingCandidate = null;

    // A plausible-speed segment can still be pure GPS noise: indoors,
    // reflected/multipath fixes wander a few meters between updates while
    // the phone doesn't move at all, which implies only 1-3 m/s — well
    // inside even running mode's cap, so it passes the teleport-oriented
    // check above untouched. The chip-speed gate (step 3a) tells this apart
    // from real motion using the fix's own reported speed, not the segment's
    // geometry — see [_StationaryDetector]. Below the gate, advance the
    // anchor (so the wander doesn't accumulate as drift against a stale
    // reference point) but credit no distance or elapsed time, the same as a
    // pause/resume gap.
    final isMoving = _stationaryDetector.accepts(
      hasSpeed: point.hasSpeed,
      speedMps: point.speedMps,
      segmentDistance: segmentDistance,
    );
    if (!isMoving) {
      _lastAccepted = point;
      return;
    }

    _acceptSegment(segmentDistance, segmentDuration, previous, point);
  }

  /// Whether a segment could have been covered under [mode] rather than
  /// being a GPS glitch. Distance and speed are both bounded: speed alone
  /// lets an arbitrarily large jump through once the gap is long enough, and
  /// distance alone would reject a legitimately sparse stretch of fixes.
  bool _isPlausibleSegment(double distanceMeters, Duration duration) {
    if (distanceMeters > _limits.maxPlausibleSegmentMeters) return false;
    if (duration <= Duration.zero) return distanceMeters == 0;
    return distanceMeters / (duration.inMilliseconds / 1000) <=
        _limits.maxPlausibleSpeedMps;
  }

  /// Restarts measurement from [point] without crediting distance or elapsed
  /// time, for when the run continues but the path in between is unknowable.
  void _resetAnchorTo(TrackPoint point) {
    _lastAccepted = point;
    _pendingCandidate = null;
    _stationaryDetector.reset();
  }

  void _acceptSegment(
    double segmentDistance,
    Duration segmentDuration,
    TrackPoint previous,
    TrackPoint point,
  ) {
    _lastAccepted = point;

    final segmentSpeedMps =
        segmentDistance / (segmentDuration.inMilliseconds / 1000);
    if (_maxSpeedMps == null || segmentSpeedMps > _maxSpeedMps!) {
      _maxSpeedMps = segmentSpeedMps;
    }

    _movingElapsed += segmentDuration;
    final from = _runTimeOf(previous.timestamp);
    final to = _runTimeOf(point.timestamp);
    if (_isTimeMode) {
      _creditTimeMode(segmentDistance, from, to);
    } else {
      _creditDistanceMode(segmentDistance, from, to);
    }
  }

  /// Call when tracking pauses/resumes so elapsed/distance calculations
  /// don't bridge the gap as if it were continuous movement. The elapsed
  /// clock itself is paused by whoever owns the [RunClock].
  void resetSegmentAnchor() {
    _lastAccepted = null;
    _pendingCandidate = null;
    _stationaryDetector.reset();
    _elevation.resetAnchor();
    _runTimeFloor = _latestRunTime;
  }

  /// Distance-kind splits: a split ends where the run crosses its distance
  /// boundary, at the elapsed-clock time interpolated along the segment that
  /// crossed it. Its duration is elapsed time since the previous boundary,
  /// so time the GPS filters didn't credit as moving still counts.
  ///
  /// Splits may vary in size (issue #99's custom plans), so each loop
  /// iteration looks up the size of the split it is about to complete
  /// rather than reusing one constant: a single GPS gap can straddle several
  /// short splits of *different* sizes, and each one must be closed at its
  /// own boundary, not the previous split's.
  void _creditDistanceMode(double distance, Duration from, Duration to) {
    final span = to - from;
    var credited = 0.0;
    var size = _plan.sizeOf(_completedSplits.length);

    while (distance - credited > 0 &&
        _totalDistanceMeters + (distance - credited) >=
            _splitStartDistanceMeters + size) {
      final intoSplit =
          (_splitStartDistanceMeters + size) - _totalDistanceMeters;
      credited += intoSplit;
      // Fraction of the whole segment, not of what's left of it, so several
      // crossings in one segment don't compound rounding.
      var crossing = from + span * (credited / distance);
      if (crossing < _splitStartRunTime) crossing = _splitStartRunTime;

      _totalDistanceMeters += intoSplit;
      _closeSplit(end: crossing, distanceMeters: size);
      size = _plan.sizeOf(_completedSplits.length);
    }

    _totalDistanceMeters += distance - credited;
  }

  /// Time-kind splits close on the elapsed clock ([_closeTimeSplitsUpTo]),
  /// not when a fix happens to arrive, so a fix's distance can belong partly
  /// to a split that has already closed: it covers `from`..`to` on the
  /// timeline, and each split gets the share of [distance] for the share of
  /// that span it overlaps. Whatever lies after the last boundary stays with
  /// the split in progress.
  void _creditTimeMode(double distance, Duration from, Duration to) {
    _totalDistanceMeters += distance;
    final span = to - from;
    if (span <= Duration.zero) return;

    var movedBack = 0.0;
    for (var i = _completedSplits.length - 1; i >= 0; i--) {
      final end = _splitEndRunTimes[i];
      if (end <= from) break;
      final start = i == 0 ? Duration.zero : _splitEndRunTimes[i - 1];
      final overlap = (end < to ? end : to) - (start > from ? start : from);
      if (overlap <= Duration.zero) continue;
      final share = distance * overlap.inMicroseconds / span.inMicroseconds;
      final split = _completedSplits[i];
      _completedSplits[i] = _split(
        index: split.index,
        duration: split.duration,
        distanceMeters: split.distanceMeters + share,
      );
      movedBack += share;
    }
    _splitStartDistanceMeters += movedBack;
  }

  /// Closes every time-kind split whose boundary [runTime] has reached, with
  /// the distance credited to it so far — a later fix may still add to it
  /// (see [_creditTimeMode]).
  void _closeTimeSplitsUpTo(Duration runTime) {
    var size = _durationOf(_completedSplits.length);
    while (size > Duration.zero && runTime >= _splitStartRunTime + size) {
      _closeSplit(
        end: _splitStartRunTime + size,
        distanceMeters: _totalDistanceMeters - _splitStartDistanceMeters,
      );
      size = _durationOf(_completedSplits.length);
    }
  }

  /// Records the split in progress as complete at [end] on the elapsed
  /// timeline and starts the next one there.
  void _closeSplit({required Duration end, required double distanceMeters}) {
    _completedSplits.add(
      _split(
        index: _completedSplits.length + 1,
        duration: end - _splitStartRunTime,
        distanceMeters: distanceMeters,
      ),
    );
    _splitEndRunTimes.add(end);
    _splitStartRunTime = end;
    _splitStartDistanceMeters = _totalDistanceMeters;
  }

  Split _split({
    required int index,
    required Duration duration,
    required double distanceMeters,
  }) => Split(
    index: index,
    duration: duration,
    // A split covering measurable distance in no measurable time would
    // divide by zero; report 0 rather than an infinite pace.
    avgSpeedMps: duration.inMicroseconds > 0
        ? distanceMeters / duration.inMicroseconds * 1e6
        : 0,
    distanceMeters: distanceMeters,
    targetSpeedMps: _plan.targetOf(index - 1),
  );

  /// [_plan.sizeOf] returns seconds for a time-kind plan — converted here
  /// rather than in [SplitPlan] itself, which stays Duration-agnostic so it
  /// can express distance-kind sizes in the same `double` shape.
  Duration _durationOf(int splitIndex) => Duration(
    microseconds: (_plan.sizeOf(splitIndex) * Duration.microsecondsPerSecond)
        .round(),
  );

  double? _avgSpeedMps() {
    if (_movingElapsed <= Duration.zero) return null;
    return _totalDistanceMeters / _movingElapsed.inMilliseconds * 1000;
  }

  LiveMetrics _buildMetrics() {
    final splitIndex = _completedSplits.length;
    final currentSplitElapsed = _latestRunTime - _splitStartRunTime;
    return LiveMetrics(
      elapsed: _movingElapsed,
      elapsedWallClock: _latestRunTime,
      distanceMeters: _totalDistanceMeters,
      avgSpeedMps: _avgSpeedMps(),
      completedSplits: List.unmodifiable(_completedSplits),
      currentSplitElapsed: currentSplitElapsed.isNegative
          ? Duration.zero
          : currentSplitElapsed,
      currentSplitDistanceMeters:
          _totalDistanceMeters - _splitStartDistanceMeters,
      currentSplit: CurrentSplitInfo(
        index: splitIndex + 1,
        plannedCount: _plan.plannedCount,
        sizeKind: _isTimeMode
            ? SplitSizeKind.durationSeconds
            : SplitSizeKind.distanceMeters,
        size: _plan.sizeOf(splitIndex),
        targetSpeedMps: _plan.targetOf(splitIndex),
      ),
      maxSpeedMps: _maxSpeedMps,
      elevationGainMeters: _elevation.gainMeters,
    );
  }
}
