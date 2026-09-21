import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/audio/split_audio_settings_controller.dart';
import '../../core/tracking/split_plan_controller.dart';
import '../../core/units/units.dart';
import '../../domain/tracking/split_plan.dart';
import '../../domain/tracking/split_preference.dart';

/// Configuration screen for the run's split plan (issue #99): split
/// type/size, a pace-or-speed preference for targets, and either a rolling
/// (repeating) plan with an optional single target or a custom plan of
/// individually sized/targeted splits. Reached from the home screen (a
/// summary row shown while idle) and from Settings — see docs/
/// SPLIT-TARGETS-PLAN.md §5.5. Persistence is immediate on every committed
/// field, same as the old Settings section this replaces; there is no Save
/// button.
class SplitsScreen extends ConsumerWidget {
  const SplitsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final plan = ref.watch(splitPlanControllerProvider);
    final notifier = ref.read(splitPlanControllerProvider.notifier);

    return Scaffold(
      appBar: AppBar(title: const Text('Splits')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _SplitTypeSection(plan: plan, notifier: notifier),
            if (plan.base.kind == SplitKind.timeMin) ...[
              const SizedBox(height: 24),
              _DisplayUnitsSection(plan: plan, notifier: notifier),
            ],
            const SizedBox(height: 24),
            const Divider(),
            const SizedBox(height: 16),
            _TargetsAsSection(plan: plan, notifier: notifier),
            const SizedBox(height: 24),
            const Divider(),
            const SizedBox(height: 16),
            _PlanTypeSection(plan: plan, notifier: notifier),
            const SizedBox(height: 16),
            if (plan.isCustom)
              _CustomPlanSection(plan: plan, notifier: notifier)
            else
              _RollingPlanSection(plan: plan, notifier: notifier),
            const SizedBox(height: 24),
            const Divider(),
            const SizedBox(height: 16),
            const _AudioCuesSection(),
          ],
        ),
      ),
    );
  }
}

/// Audio cue toggles (issue #125): a beep on split change, a beep pattern on
/// a target-verdict change, and optional spoken announcements. Lives here
/// rather than in a separate screen since it's one more piece of "how a run
/// is captured/experienced" configuration, same reasoning as every other
/// section on this screen (see the class doc above).
///
/// No separate master on/off (removed 2026-09-21, issue #125 follow-up) —
/// each toggle below is independently visible and effective; "audio cues
/// enabled at all" is just whether any of the four is on
/// ([SplitAudioSettings.anyEnabled]), so a fifth switch that only gated the
/// other four would have been a step with no real choice behind it.
class _AudioCuesSection extends ConsumerWidget {
  const _AudioCuesSection();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(splitAudioSettingsControllerProvider);
    final notifier = ref.read(splitAudioSettingsControllerProvider.notifier);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Audio cues', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        Text(
          'Beeps and optional spoken announcements as splits change during a '
          'run. Not available for cycling, which has no split targets.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 8),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('Beep on split change'),
          value: settings.beepOnSplitChange,
          onChanged: (value) =>
              notifier.update(settings.copyWith(beepOnSplitChange: value)),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('Beep on target correction'),
          subtitle: const Text(
            'Two beeps too fast, three too slow, one long beep back on '
            'target — only fires for a split with a target set.',
          ),
          value: settings.beepOnVerdictChange,
          onChanged: (value) =>
              notifier.update(settings.copyWith(beepOnVerdictChange: value)),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('Announce current split target'),
          subtitle: const Text(
            'Speak the target pace/speed whenever a split starts, including '
            'the first on Start — "No target" with none set.',
          ),
          value: settings.announceSplitTarget,
          onChanged: (value) =>
              notifier.update(settings.copyWith(announceSplitTarget: value)),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('Announce pace correction'),
          subtitle: const Text(
            'Speak too-fast/too-slow, by how much, and the target — or '
            '"back on target" — only fires for a split with a target set.',
          ),
          value: settings.announceVerdictCorrection,
          onChanged: (value) => notifier.update(
            settings.copyWith(announceVerdictCorrection: value),
          ),
        ),
      ],
    );
  }
}

/// The [SpeedUnit] targets are entered/shown in, per [SplitPlan.targetsAsPace]
/// and the plan's effective distance unit — one member reused across every
/// target field on this screen.
SpeedUnit _targetUnit(SplitPlan plan) {
  final speedFirst = SpeedUnit.initialFor(plan.base.effectiveDistanceUnit);
  return plan.targetsAsPace ? speedFirst.toggled : speedFirst;
}

class _SplitTypeSection extends StatelessWidget {
  final SplitPlan plan;
  final SplitPlanController notifier;

  const _SplitTypeSection({required this.plan, required this.notifier});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Split type', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        Text(
          'Choose how splits are measured for new activities, recorded with '
          'each activity and used as the default when viewing it on the web.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 12),
        SegmentedButton<SplitKind>(
          segments: const [
            ButtonSegment(
              value: SplitKind.distanceKm,
              label: SizedBox(
                width: 88,
                child: Center(child: Text('Km', softWrap: false)),
              ),
            ),
            ButtonSegment(
              value: SplitKind.distanceMi,
              label: SizedBox(
                width: 88,
                child: Center(child: Text('Miles', softWrap: false)),
              ),
            ),
            ButtonSegment(
              value: SplitKind.timeMin,
              label: SizedBox(
                width: 88,
                child: Center(child: Text('Minutes', softWrap: false)),
              ),
            ),
          ],
          showSelectedIcon: false,
          selected: {plan.base.kind},
          onSelectionChanged: (selection) =>
              _changeKind(context, selection.first),
        ),
        const SizedBox(height: 12),
        if (!plan.isCustom)
          Row(
            children: [
              const Text('Every'),
              const SizedBox(width: 8),
              SizedBox(
                width: 72,
                child: _CommittingTextField(
                  key: ValueKey(plan.base.value),
                  initialValue: '${plan.base.value}',
                  parse: (text) => int.tryParse(text)?.let((v) => v > 0 ? v : null),
                  format: (v) => '$v',
                  onCommit: (value) => notifier.select(
                    plan.copyWith(
                      base: SplitPreference(
                        kind: plan.base.kind,
                        value: value,
                        timeSplitDisplayUnit: plan.base.timeSplitDisplayUnit,
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Text(_unitLabel(plan.base.kind)),
            ],
          ),
      ],
    );
  }

  /// Changing the split type when a custom plan is defined makes every
  /// existing custom size meaningless (a 400m rep has no sensible reading
  /// once the plan becomes minutes-based) — confirm before clearing it.
  Future<void> _changeKind(BuildContext context, SplitKind kind) async {
    if (kind == plan.base.kind) return;

    if (plan.isCustom) {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Change split type?'),
          content: const Text(
            'Changing the split type clears the custom splits, since their '
            'sizes only make sense for the current type.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(context).pop(true),
              child: const Text('Change'),
            ),
          ],
        ),
      );
      if (confirmed != true) return;
    }

    await notifier.select(
      plan.copyWith(
        base: SplitPreference(
          kind: kind,
          value: plan.base.value,
          timeSplitDisplayUnit: plan.base.timeSplitDisplayUnit,
        ),
        customSplits: const [],
      ),
    );
  }

  String _unitLabel(SplitKind kind) => switch (kind) {
    SplitKind.distanceKm => 'km',
    SplitKind.distanceMi => 'mi',
    SplitKind.timeMin => 'min',
  };
}

class _DisplayUnitsSection extends StatelessWidget {
  final SplitPlan plan;
  final SplitPlanController notifier;

  const _DisplayUnitsSection({required this.plan, required this.notifier});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        const Text('Display units'),
        const SizedBox(width: 8),
        SegmentedButton<DistanceUnit>(
          segments: const [
            ButtonSegment(
              value: DistanceUnit.km,
              label: SizedBox(
                width: 72,
                child: Center(child: Text('Km', softWrap: false)),
              ),
            ),
            ButtonSegment(
              value: DistanceUnit.mi,
              label: SizedBox(
                width: 72,
                child: Center(child: Text('Miles', softWrap: false)),
              ),
            ),
          ],
          showSelectedIcon: false,
          selected: {plan.base.timeSplitDisplayUnit},
          onSelectionChanged: (selection) => notifier.select(
            plan.copyWith(
              base: SplitPreference(
                kind: plan.base.kind,
                value: plan.base.value,
                timeSplitDisplayUnit: selection.first,
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _TargetsAsSection extends StatelessWidget {
  final SplitPlan plan;
  final SplitPlanController notifier;

  const _TargetsAsSection({required this.plan, required this.notifier});

  @override
  Widget build(BuildContext context) {
    final unit = plan.base.effectiveDistanceUnit;
    final paceLabel = unit == DistanceUnit.mi ? 'min/mi' : 'min/km';
    final speedLabel = unit == DistanceUnit.mi ? 'mph' : 'km/h';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Targets as', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        Text(
          'How split targets are entered and shown, and the live screen\'s '
          'starting speed/pace toggle.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 12),
        SegmentedButton<bool>(
          segments: [
            ButtonSegment(value: true, label: Text(paceLabel)),
            ButtonSegment(value: false, label: Text(speedLabel)),
          ],
          showSelectedIcon: false,
          selected: {plan.targetsAsPace},
          onSelectionChanged: (selection) =>
              notifier.select(plan.copyWith(targetsAsPace: selection.first)),
        ),
      ],
    );
  }
}

class _PlanTypeSection extends StatelessWidget {
  final SplitPlan plan;
  final SplitPlanController notifier;

  const _PlanTypeSection({required this.plan, required this.notifier});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Plan', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        Text(
          plan.isCustom
              ? 'A custom plan: each split below can have its own size and '
                    'target. Once the plan ends, splits continue at the base '
                    'size above with no target.'
              : 'A rolling plan: every split is the base size above, '
                    'optionally with one target that applies to all of them.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: 12),
        SegmentedButton<bool>(
          segments: const [
            ButtonSegment(value: false, label: Text('Rolling')),
            ButtonSegment(value: true, label: Text('Custom')),
          ],
          showSelectedIcon: false,
          selected: {plan.isCustom},
          onSelectionChanged: (selection) {
            final wantsCustom = selection.first;
            if (wantsCustom == plan.isCustom) return;
            notifier.select(
              wantsCustom
                  ? plan.copyWith(
                      customSplits: [
                        PlannedSplit(
                          size: _rollingSizeInPlanUnits(plan.base),
                          targetSpeedMps: plan.rollingTargetSpeedMps,
                        ),
                      ],
                    )
                  : plan.copyWith(customSplits: const []),
            );
          },
        ),
      ],
    );
  }
}

double _rollingSizeInPlanUnits(SplitPreference base) => switch (base.kind) {
  SplitKind.distanceKm => base.value * 1000.0,
  SplitKind.distanceMi => base.value * metersPerMile,
  SplitKind.timeMin => base.value * 60.0,
};

class _RollingPlanSection extends StatelessWidget {
  final SplitPlan plan;
  final SplitPlanController notifier;

  const _RollingPlanSection({required this.plan, required this.notifier});

  @override
  Widget build(BuildContext context) {
    final unit = _targetUnit(plan);
    final target = plan.rollingTargetSpeedMps;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Text('Target'),
            const SizedBox(width: 8),
            SizedBox(
              width: 88,
              child: _CommittingTextField(
                key: ValueKey(
                  'rolling_target-${plan.rollingTargetSpeedMps}-${unit.name}',
                ),
                initialValue: target != null
                    ? formatTargetForEditing(target, unit)
                    : '',
                hintText: unit.isPace ? 'm:ss' : '0.0',
                parse: (text) => unit.isPace
                    ? parsePaceToMps(text, unit)
                    : parseSpeedToMps(text, unit),
                format: (v) => formatTargetForEditing(v, unit),
                onCommit: (value) => notifier.select(
                  plan.copyWith(rollingTargetSpeedMps: value),
                ),
              ),
            ),
            const SizedBox(width: 8),
            Text(unit.suffix),
            if (target != null) ...[
              const SizedBox(width: 8),
              IconButton(
                icon: const Icon(Icons.close, size: 18),
                tooltip: 'Clear target',
                onPressed: () => notifier.select(
                  plan.copyWith(clearRollingTarget: true),
                ),
              ),
            ],
          ],
        ),
        if (target != null) ...[
          const SizedBox(height: 4),
          Text(
            '= ${_equivalentHint(plan, target, unit)}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ],
    );
  }

  String _equivalentHint(SplitPlan plan, double targetMps, SpeedUnit unit) {
    final sizeMeters = _rollingSizeInPlanUnits(plan.base);
    if (plan.base.kind == SplitKind.timeMin) {
      // Time split: the hint is the distance covered at this target speed
      // over the split's duration.
      final distance = targetMps * sizeMeters; // sizeMeters holds seconds here
      return formatSplitSizeMeters(distance, plan.base.effectiveDistanceUnit);
    }
    // Distance split: the hint is the time to cover the split at this
    // target speed.
    final seconds = sizeMeters / targetMps;
    return '${formatMinSec(Duration(milliseconds: (seconds * 1000).round()))} per split';
  }
}

class _CustomPlanSection extends StatelessWidget {
  final SplitPlan plan;
  final SplitPlanController notifier;

  const _CustomPlanSection({required this.plan, required this.notifier});

  @override
  Widget build(BuildContext context) {
    final unit = _targetUnit(plan);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Text('Number of splits'),
            const SizedBox(width: 8),
            SizedBox(
              width: 64,
              child: _CommittingTextField(
                key: ValueKey(plan.customSplits.length),
                initialValue: '${plan.customSplits.length}',
                parse: (text) =>
                    int.tryParse(text)?.let((v) => (v > 0 && v <= maxCustomSplits) ? v : null),
                format: (v) => '$v',
                onCommit: (count) => _changeCount(context, count),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        for (var i = 0; i < plan.customSplits.length; i++)
          _CustomSplitRow(
            key: ValueKey(i),
            index: i,
            split: plan.customSplits[i],
            plan: plan,
            unit: unit,
            onChanged: (updated) {
              final splits = [...plan.customSplits];
              splits[i] = updated;
              notifier.select(plan.copyWith(customSplits: splits));
            },
            onDelete: plan.customSplits.length > 1
                ? () {
                    final splits = [...plan.customSplits]..removeAt(i);
                    notifier.select(plan.copyWith(customSplits: splits));
                  }
                : null,
            onApplyTargetToAll: i == 0 && plan.customSplits[i].targetSpeedMps != null
                ? () {
                    final target = plan.customSplits[i].targetSpeedMps;
                    final splits = [
                      for (final s in plan.customSplits)
                        s.copyWith(targetSpeedMps: target),
                    ];
                    notifier.select(plan.copyWith(customSplits: splits));
                  }
                : null,
          ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: plan.customSplits.length >= maxCustomSplits
              ? null
              : () {
                  final last = plan.customSplits.isEmpty
                      ? PlannedSplit(size: _rollingSizeInPlanUnits(plan.base))
                      : plan.customSplits.last;
                  notifier.select(
                    plan.copyWith(
                      customSplits: [...plan.customSplits, last],
                    ),
                  );
                },
          icon: const Icon(Icons.add),
          label: const Text('Add split'),
        ),
      ],
    );
  }

  Future<void> _changeCount(BuildContext context, int count) async {
    final splits = plan.customSplits;
    if (count < splits.length) {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Remove splits?'),
          content: Text(
            'Reducing the split count to $count discards the last '
            '${splits.length - count} configured split'
            '${splits.length - count == 1 ? '' : 's'}, including any targets '
            'set on them.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(context).pop(true),
              child: const Text('Remove'),
            ),
          ],
        ),
      );
      if (confirmed != true) return;
    }
    await notifier.select(plan.copyWith(customSplits: _resized(splits, count)));
  }

  List<PlannedSplit> _resized(List<PlannedSplit> splits, int count) {
    if (count == splits.length) return splits;
    if (count < splits.length) return splits.sublist(0, count);
    final fill = splits.isEmpty
        ? PlannedSplit(size: _rollingSizeInPlanUnits(plan.base))
        : splits.last;
    return [...splits, for (var i = splits.length; i < count; i++) fill];
  }
}

class _CustomSplitRow extends StatelessWidget {
  final int index;
  final PlannedSplit split;
  final SplitPlan plan;
  final SpeedUnit unit;
  final ValueChanged<PlannedSplit> onChanged;
  final VoidCallback? onDelete;
  final VoidCallback? onApplyTargetToAll;

  const _CustomSplitRow({
    super.key,
    required this.index,
    required this.split,
    required this.plan,
    required this.unit,
    required this.onChanged,
    required this.onDelete,
    required this.onApplyTargetToAll,
  });

  @override
  Widget build(BuildContext context) {
    final isTimeKind = plan.base.kind == SplitKind.timeMin;
    final sizeHint = isTimeKind
        ? formatSplitSizeSeconds(split.size)
        : formatSplitSizeMeters(split.size, plan.base.effectiveDistanceUnit);

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              SizedBox(
                width: 28,
                child: Text('#${index + 1}', style: Theme.of(context).textTheme.bodySmall),
              ),
              SizedBox(
                width: 72,
                child: _CommittingTextField(
                  // Keyed on the row's own committed value (same pattern as
                  // the rolling target field) — without this, editing one
                  // row while another row's field keeps the same widget
                  // identity across a rebuild can leave a field showing
                  // stale text whose underlying model value never actually
                  // matched what was typed (a real bug found on-device: a
                  // custom split's size field silently reverted to an
                  // earlier value instead of the one just committed).
                  key: ValueKey('custom_size-$index-${split.size}'),
                  initialValue: isTimeKind
                      ? formatMinSec(Duration(milliseconds: (split.size * 1000).round()))
                      : _sizeToDecimalText(split.size, plan.base.effectiveDistanceUnit),
                  hintText: isTimeKind ? 'm:ss' : sizeHint,
                  parse: (text) => isTimeKind
                      ? parseMinSec(text, bareNumberAsSeconds: true)
                          ?.inMilliseconds
                          .let((ms) => ms / 1000)
                      : _parseDecimalSize(text, plan.base.effectiveDistanceUnit),
                  format: (v) => isTimeKind
                      ? formatMinSec(Duration(milliseconds: (v * 1000).round()))
                      : _sizeToDecimalText(v, plan.base.effectiveDistanceUnit),
                  onCommit: (size) => onChanged(split.copyWith(size: size)),
                ),
              ),
              Text(isTimeKind ? '' : plan.base.effectiveDistanceUnit.label),
              const SizedBox(width: 12),
              const Text('@'),
              const SizedBox(width: 8),
              SizedBox(
                width: 80,
                child: _CommittingTextField(
                  key: ValueKey(
                    'custom_target-$index-${split.targetSpeedMps}-${unit.name}',
                  ),
                  initialValue: split.targetSpeedMps != null
                      ? formatTargetForEditing(split.targetSpeedMps!, unit)
                      : '',
                  hintText: unit.isPace ? 'm:ss' : '0.0',
                  parse: (text) => unit.isPace
                      ? parsePaceToMps(text, unit)
                      : parseSpeedToMps(text, unit),
                  format: (v) => formatTargetForEditing(v, unit),
                  onCommit: (target) =>
                      onChanged(split.copyWith(targetSpeedMps: target)),
                  allowEmpty: true,
                  onCleared: () => onChanged(split.copyWith(clearTarget: true)),
                ),
              ),
              const SizedBox(width: 4),
              Text(unit.suffix, style: Theme.of(context).textTheme.bodySmall),
              const Spacer(),
              if (onDelete != null)
                IconButton(
                  icon: const Icon(Icons.delete_outline, size: 20),
                  onPressed: onDelete,
                ),
            ],
          ),
          if (onApplyTargetToAll != null)
            Padding(
              padding: const EdgeInsets.only(left: 28),
              child: TextButton(
                onPressed: onApplyTargetToAll,
                style: TextButton.styleFrom(
                  padding: EdgeInsets.zero,
                  minimumSize: const Size(0, 32),
                  tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
                child: const Text('Apply target to all'),
              ),
            ),
        ],
      ),
    );
  }

  String _sizeToDecimalText(double meters, DistanceUnit unit) {
    final value = unit == DistanceUnit.mi ? meters / metersPerMile : meters / 1000;
    final fixed = value.toStringAsFixed(3);
    return fixed.replaceFirst(RegExp(r'0+$'), '').replaceFirst(RegExp(r'\.$'), '');
  }

  double? _parseDecimalSize(String text, DistanceUnit unit) {
    final value = double.tryParse(text.trim());
    if (value == null || value <= 0) return null;
    return unit == DistanceUnit.mi ? value * metersPerMile : value * 1000;
  }
}

/// A text field that commits on submit *and* on losing focus (tapping away
/// to another field or control) — a plain TextFormField only fires
/// onFieldSubmitted on the keyboard's submit key, so a typed edit dismissed
/// any other way would otherwise be silently discarded. Generalizes the old
/// Settings screen's `_SplitValueField` to any parse/format pair (plain
/// integers, decimal distances, "m:ss" pace/duration strings) rather than
/// just integers.
class _CommittingTextField<T> extends StatefulWidget {
  final String initialValue;
  final String? hintText;
  final T? Function(String text) parse;
  final String Function(T value) format;
  final ValueChanged<T> onCommit;

  /// When true, an emptied field calls [onCleared] instead of reverting —
  /// used for an optional target field's own "clear" affordance via
  /// deleting the text, in addition to the explicit clear button.
  final bool allowEmpty;
  final VoidCallback? onCleared;

  const _CommittingTextField({
    super.key,
    required this.initialValue,
    this.hintText,
    required this.parse,
    required this.format,
    required this.onCommit,
    this.allowEmpty = false,
    this.onCleared,
  });

  @override
  State<_CommittingTextField<T>> createState() => _CommittingTextFieldState<T>();
}

class _CommittingTextFieldState<T> extends State<_CommittingTextField<T>> {
  late final _controller = TextEditingController(text: widget.initialValue);
  late final _focusNode = FocusNode()..addListener(_onFocusChange);

  // Guards against double-committing the same text: onFieldSubmitted (the
  // keyboard's Done key) and the focus-loss listener below can both fire for
  // a single edit — e.g. Done triggers a commit whose onCommit callback
  // opens a dialog, which itself steals focus and re-triggers the listener
  // before the text has changed again. Without this, a commit that shows a
  // confirmation dialog would show it twice (found via a widget test).
  // Cleared on the next focus gain so a deliberate retry of the same text
  // (e.g. after cancelling that confirmation dialog) is never suppressed.
  String? _suppressedCommitText;

  // A real on-device bug: this screen has many stacked fields and no
  // navigation guard, so onTapOutside/onFieldSubmitted alone were not
  // enough — tapping a *different* field (rather than empty space) doesn't
  // reliably fire onTapOutside for the field being left, and popping the
  // route (back button/gesture) fires neither at all, silently discarding
  // whatever was typed but never explicitly submitted. Listening for focus
  // loss itself is the one signal that fires in every one of those cases,
  // since the framework always unfocuses a field before it's disposed.
  void _onFocusChange() {
    if (_focusNode.hasFocus) {
      _suppressedCommitText = null;
    } else {
      _commit();
    }
  }

  void _commit() {
    final text = _controller.text.trim();
    if (text == _suppressedCommitText) return;
    _suppressedCommitText = text;
    if (widget.allowEmpty && text.isEmpty) {
      widget.onCleared?.call();
      return;
    }
    final value = widget.parse(text);
    if (value != null) {
      widget.onCommit(value);
    } else {
      // Reject invalid/garbage input by reverting to the last known-good
      // value, rather than leaving the field showing something that was
      // never actually persisted.
      _controller.text = widget.initialValue;
    }
  }

  @override
  void dispose() {
    _focusNode.removeListener(_onFocusChange);
    _focusNode.dispose();
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: _controller,
      focusNode: _focusNode,
      textAlign: TextAlign.center,
      decoration: InputDecoration(hintText: widget.hintText, isDense: true),
      onFieldSubmitted: (_) => _commit(),
      onTapOutside: (_) => FocusManager.instance.primaryFocus?.unfocus(),
    );
  }
}

extension _Let<T> on T {
  R let<R>(R Function(T) block) => block(this);
}
