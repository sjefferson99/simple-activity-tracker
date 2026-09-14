import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../core/units/units.dart' show DistanceUnit;
import '../../domain/tracking/split_plan.dart';
import '../../domain/tracking/split_preference.dart';

const _splitPlanKey = 'split_plan';

// Legacy keys from before issue #99 — read once as a migration path so an
// existing install's split preference isn't lost the first time it opens a
// build that understands SplitPlan instead of bare SplitPreference. Never
// written again after the migration.
const _legacySplitKindKey = 'split_kind';
const _legacySplitValueKey = 'split_value';
const _legacyTimeSplitDisplayUnitKey = 'split_time_display_unit';

final splitPlanControllerProvider =
    NotifierProvider<SplitPlanController, SplitPlan>(SplitPlanController.new);

/// The split configuration set on the Splits screen (issue #99): split
/// kind/size, optional targets, and an optional custom plan. Persisted (not
/// secure — same rationale as ActivityModeController: not sensitive, but
/// flutter_secure_storage is already a dependency) so the app reopens with
/// whichever plan was last chosen.
///
/// Starts at [SplitPlan.defaultPlan] and stays there until the async
/// [_load] resolves — same pattern as ActivityModeController reading real
/// state asynchronously after a synchronous default.
class SplitPlanController extends Notifier<SplitPlan> {
  FlutterSecureStorage get _storage => const FlutterSecureStorage();

  // Guards against _load() (fired from build(), can still be in flight)
  // overwriting a select() the user made in the meantime — same rationale as
  // ActivityModeController's guard.
  bool _userHasSelected = false;

  @override
  SplitPlan build() {
    unawaited(_load());
    return SplitPlan.defaultPlan;
  }

  Future<void> _load() async {
    final storedPlanJson = await _storage.read(key: _splitPlanKey);
    if (storedPlanJson != null) {
      if (_userHasSelected) return;
      final plan = SplitPlan.fromJson(
        Map<String, Object?>.from(
          jsonDecode(storedPlanJson) as Map<Object?, Object?>,
        ),
      );
      if (plan != null && plan != state) state = plan;
      return;
    }

    // No SplitPlan has ever been saved on this install — fall back to the
    // pre-#99 legacy keys (if any) so an existing user's split preference
    // survives the upgrade, then persist it under the new key so this
    // migration only ever runs once.
    final legacyPreference = await _readLegacyPreference();
    if (_userHasSelected) return;
    final plan = SplitPlan(base: legacyPreference);
    if (plan != state) state = plan;
    await _writePlan(plan);
  }

  Future<SplitPreference> _readLegacyPreference() async {
    final storedKind = await _storage.read(key: _legacySplitKindKey);
    final storedValue = await _storage.read(key: _legacySplitValueKey);
    final storedUnit = await _storage.read(key: _legacyTimeSplitDisplayUnitKey);
    final base =
        SplitPreference.fromGpxValues(storedKind, storedValue) ??
        SplitPreference.defaultPreference;
    return SplitPreference(
      kind: base.kind,
      value: base.value,
      timeSplitDisplayUnit: storedUnit == DistanceUnit.mi.name
          ? DistanceUnit.mi
          : DistanceUnit.km,
    );
  }

  Future<void> select(SplitPlan plan) async {
    _userHasSelected = true;
    state = plan;
    await _writePlan(plan);
  }

  Future<void> _writePlan(SplitPlan plan) async {
    await _storage.write(key: _splitPlanKey, value: jsonEncode(plan.toJson()));
  }
}
