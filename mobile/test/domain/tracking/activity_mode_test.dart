import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';

void main() {
  group('ActivityMode', () {
    test('labels', () {
      expect(ActivityMode.running.label, 'Run');
      expect(ActivityMode.cycling.label, 'Cycle');
      expect(ActivityMode.walking.label, 'Walk');
    });

    // Issue #129: walking is a distinct tag from running (for future
    // filtering/analysis) but deliberately behaves exactly like running
    // everywhere else — starting with supportsSplits, which cycling alone
    // turns off (issue #99 D8).
    test('supportsSplits is true for running and walking, false for cycling', () {
      expect(ActivityMode.running.supportsSplits, isTrue);
      expect(ActivityMode.walking.supportsSplits, isTrue);
      expect(ActivityMode.cycling.supportsSplits, isFalse);
    });
  });
}
