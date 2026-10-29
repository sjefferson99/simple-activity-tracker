import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/display/orientation_lock_settings.dart';
import 'package:simple_activity_tracker/features/settings/display_section.dart';

/// Every SystemChrome.setPreferredOrientations call's argument, in order.
List<List<String>> _captureOrientationCalls() {
  final calls = <List<String>>[];
  TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(
    SystemChannels.platform,
    (call) async {
      if (call.method == 'SystemChrome.setPreferredOrientations') {
        calls.add((call.arguments as List).cast<String>());
      }
      return null;
    },
  );
  addTearDown(
    () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null),
  );
  return calls;
}

/// The settings section plus the same listener SimpleActivityTrackerApp
/// installs, without the rest of the app's providers. _pump applies the
/// saved value first, as main() does.
class _Host extends ConsumerStatefulWidget {
  const _Host();

  @override
  ConsumerState<_Host> createState() => _HostState();
}

class _HostState extends ConsumerState<_Host> {
  @override
  void initState() {
    super.initState();
    ref.listenManual(portraitLockProvider, (_, locked) => applyPortraitLock(locked));
  }

  @override
  Widget build(BuildContext context) => const MaterialApp(home: Scaffold(body: DisplaySection()));
}

Future<void> _pump(WidgetTester tester, {Map<String, String> storage = const {}}) async {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform({...storage});
  await applyStoredPortraitLock();
  await tester.pumpWidget(const ProviderScope(child: _Host()));
  await tester.pumpAndSettle();
}

bool _switchValue(WidgetTester tester) => tester.widget<SwitchListTile>(find.byType(SwitchListTile)).value;

void main() {
  testWidgets('off by default: follows the phone', (tester) async {
    final calls = _captureOrientationCalls();
    await _pump(tester);
    expect(_switchValue(tester), isFalse);
    expect(calls, [<String>[]]);
  });

  testWidgets('turning it on locks to portrait at once and is saved', (tester) async {
    final calls = _captureOrientationCalls();
    await _pump(tester);
    await tester.tap(find.text('Lock to portrait'));
    await tester.pumpAndSettle();
    expect(calls.last, ['DeviceOrientation.portraitUp']);
    expect(await const FlutterSecureStorage().read(key: 'portrait_lock_enabled'), 'true');
  });

  testWidgets('a saved lock is restored on launch', (tester) async {
    final calls = _captureOrientationCalls();
    await _pump(tester, storage: {'portrait_lock_enabled': 'true'});
    expect(_switchValue(tester), isTrue);
    // Never a momentary "follow the phone" while the provider loads, which
    // would let a phone held sideways at launch draw in landscape.
    expect(calls, isNotEmpty);
    expect(calls, everyElement(['DeviceOrientation.portraitUp']));
  });

  testWidgets('turning it off hands rotation back to the phone', (tester) async {
    final calls = _captureOrientationCalls();
    await _pump(tester, storage: {'portrait_lock_enabled': 'true'});
    await tester.tap(find.text('Lock to portrait'));
    await tester.pumpAndSettle();
    expect(_switchValue(tester), isFalse);
    expect(calls.last, <String>[]);
    expect(await const FlutterSecureStorage().read(key: 'portrait_lock_enabled'), 'false');
  });
}
