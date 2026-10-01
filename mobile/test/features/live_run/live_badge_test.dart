import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/sync/live_upload_service.dart';
import 'package:simple_activity_tracker/features/live_run/live_badge.dart';

void main() {
  test('the runner always sees whether they are being watched', () {
    expect(LiveBadge.describe(LiveUploadPhase.upToDate, 2)?.text, 'Live · shared with 2');
    expect(LiveBadge.describe(LiveUploadPhase.upToDate, 0)?.text, 'Live · not shared');
    expect(LiveBadge.describe(LiveUploadPhase.waiting, 2)?.text, 'Live · waiting for signal');
    expect(LiveBadge.describe(LiveUploadPhase.off, 2)?.text, 'Live upload off');
  });

  test('hidden when live upload cannot apply to this run', () {
    for (final phase in [LiveUploadPhase.idle, LiveUploadPhase.unavailable, LiveUploadPhase.closed]) {
      expect(LiveBadge.describe(phase, 1), isNull, reason: '$phase');
    }
  });
}
