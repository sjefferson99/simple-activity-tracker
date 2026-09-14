import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../core/units/units.dart' show DistanceUnit;
import '../../domain/tracking/split_preference.dart';

const _splitKindKey = 'split_kind';
const _splitValueKey = 'split_value';
const _timeSplitDisplayUnitKey = 'split_time_display_unit';

final splitPreferenceControllerProvider =
    NotifierProvider<SplitPreferenceController, SplitPreference>(
      SplitPreferenceController.new,
    );

/// The split-size setting on the Settings screen. Persisted (not secure —
/// same rationale as ActivityModeController: not sensitive, but
/// flutter_secure_storage is already a dependency) so the app reopens with
/// whichever split preference was last chosen.
///
/// Starts at [SplitPreference.defaultPreference] and stays there until the
/// async [_load] resolves — same pattern as ActivityModeController reading
/// real state asynchronously after a synchronous default.
class SplitPreferenceController extends Notifier<SplitPreference> {
  FlutterSecureStorage get _storage => const FlutterSecureStorage();

  // Guards against _load() (fired from build(), can still be in flight)
  // overwriting a select() the user made in the meantime — same rationale as
  // ActivityModeController's guard.
  bool _userHasSelected = false;

  @override
  SplitPreference build() {
    unawaited(_load());
    return SplitPreference.defaultPreference;
  }

  Future<void> _load() async {
    final storedKind = await _storage.read(key: _splitKindKey);
    final storedValue = await _storage.read(key: _splitValueKey);
    final storedUnit = await _storage.read(key: _timeSplitDisplayUnitKey);
    if (_userHasSelected) return;
    final base =
        SplitPreference.fromGpxValues(storedKind, storedValue) ??
        SplitPreference.defaultPreference;
    final preference = SplitPreference(
      kind: base.kind,
      value: base.value,
      timeSplitDisplayUnit: storedUnit == DistanceUnit.mi.name
          ? DistanceUnit.mi
          : DistanceUnit.km,
    );
    if (preference != state) state = preference;
  }

  Future<void> select(SplitPreference preference) async {
    _userHasSelected = true;
    state = preference;
    await _storage.write(key: _splitKindKey, value: preference.gpxSplitType);
    await _storage.write(key: _splitValueKey, value: '${preference.value}');
    await _storage.write(
      key: _timeSplitDisplayUnitKey,
      value: preference.timeSplitDisplayUnit.name,
    );
  }
}
