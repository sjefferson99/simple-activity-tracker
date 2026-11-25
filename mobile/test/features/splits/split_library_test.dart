import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/api_client.dart';
import 'package:simple_activity_tracker/core/api/api_exception.dart';
import 'package:simple_activity_tracker/core/api/dto/server_info_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/split_config_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/split_source_dto.dart';
import 'package:simple_activity_tracker/core/auth/auth_state.dart';
import 'package:simple_activity_tracker/core/auth/auth_state_controller.dart';
import 'package:simple_activity_tracker/core/version/api_compat.dart';
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';
import 'package:simple_activity_tracker/features/splits/saved_split_configs_section.dart';
import 'package:simple_activity_tracker/features/splits/split_library_screen.dart';
import 'package:simple_activity_tracker/features/splits/splits_screen.dart';

import '../../fakes/fake_api_client.dart';

/// Split library on the phone (issue #143): folder groups in the picker, the
/// Library screen, and a folder on Save as, all only for a level-4 server.

class _SignedInAuthController extends AuthStateController {
  @override
  Future<AuthState> build() async =>
      const AuthState(serverUrl: 'https://example.com', token: 't', email: 'runner@example.com');
}

SplitConfigDto _config(
  String name, {
  String? folder,
  bool readOnly = false,
  String? source,
}) => SplitConfigDto(
  id: name,
  name: name,
  plan: const SplitPlan(base: SplitPreference.defaultPreference, rollingTargetSpeedMps: 2.5),
  createdAt: DateTime.utc(2026),
  updatedAt: DateTime.utc(2026),
  folderName: folder,
  readOnly: readOnly,
  sourceName: source,
);

FakeApiClient _fakeAtLevel(int level) => FakeApiClient()
  ..getServerInfoHandler = ({required baseUrl, required token}) async =>
      ServerInfoDto(version: '1.4.0', apiLevel: level, minAppApiLevel: 0);

Future<void> _pump(
  WidgetTester tester,
  FakeApiClient fake, {
  Widget home = const SplitsScreen(),
  List<dynamic> overrides = const [],
}) async {
  FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform({});
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        authStateControllerProvider.overrideWith(_SignedInAuthController.new),
        apiClientProvider.overrideWithValue(fake),
        ...overrides.cast(),
      ],
      child: MaterialApp(home: home),
    ),
  );
  await tester.pumpAndSettle();
}

const _c25k = SplitSourceDto(
  id: 's1',
  name: 'SAT templates',
  url: 'https://github.com/o/r',
  ref: 'main',
  path: 'splits',
  isDefault: true,
  folders: [
    SplitSourceFolderDto(id: 'f1', name: 'Couch to 5K', templateCount: 27),
    SplitSourceFolderDto(id: 'f2', name: 'Intervals', templateCount: 3, enabled: false),
  ],
);

const _club = SplitSourceDto(
  id: 's2',
  name: 'Club plans',
  url: 'https://git.example.org/club/plans',
  ref: 'main',
  path: 'splits',
  hasToken: true,
);

void main() {
  group('groupSplitConfigs', () {
    test('own unfiled first, then own folders, then templates; natural order', () {
      final groups = groupSplitConfigs([
        _config('C25K week 10 run 1', folder: 'Couch to 5K', readOnly: true, source: 'SAT'),
        _config('Hills', folder: 'Club'),
        _config('C25K week 2 run 1', folder: 'Couch to 5K', readOnly: true, source: 'SAT'),
        _config('Easy'),
        _config('Fartlek', folder: 'Intervals', readOnly: true, source: 'SAT'),
      ]);
      expect([for (final g in groups) g.title], [null, 'Club', 'Couch to 5K', 'Intervals']);
      expect(groups[2].isTemplate, isTrue);
      expect([for (final c in groups[2].configs) c.name], [
        'C25K week 2 run 1',
        'C25K week 10 run 1',
      ]);
    });

    test('an older server gives one untitled group', () {
      final groups = groupSplitConfigs([_config('B'), _config('A')]);
      expect(groups, hasLength(1));
      expect(groups.single.title, isNull);
    });

    test('naturalCompare', () {
      expect(naturalCompare('week 2', 'Week 10'), lessThan(0));
      expect(naturalCompare('a', 'a1'), lessThan(0));
      expect(naturalCompare('B', 'a'), greaterThan(0));
    });
  });

  group('Saved configs on the Splits screen', () {
    testWidgets('a level-4 server: groups, template label and a Library button', (tester) async {
      final fake = _fakeAtLevel(ApiLevels.splitLibrary)
        ..listSplitConfigsHandler = ({required baseUrl, required token}) async => [
          _config('Easy'),
          _config('C25K week 1 run 1', folder: 'Couch to 5K', readOnly: true, source: 'SAT'),
        ];
      await _pump(tester, fake);

      expect(find.text('Library'), findsOneWidget);
      expect(find.text('My splits'), findsOneWidget);
      expect(find.text('Couch to 5K'), findsOneWidget);
      expect(find.textContaining('templates from SAT'), findsOneWidget);
      // Template groups start collapsed.
      expect(find.text('C25K week 1 run 1'), findsNothing);
      await tester.tap(find.text('Couch to 5K'));
      await tester.pumpAndSettle();
      expect(find.text('C25K week 1 run 1'), findsOneWidget);
      expect(find.textContaining('Template · '), findsOneWidget);
    });

    testWidgets('a level-3 server: flat list, no Library, no folder field', (tester) async {
      final fake = _fakeAtLevel(ApiLevels.splitConfigLayout)
        ..listSplitConfigsHandler = ({required baseUrl, required token}) async => [
          _config('Easy'),
        ];
      await _pump(tester, fake);

      expect(find.text('Library'), findsNothing);
      expect(find.text('My splits'), findsNothing);
      expect(find.text('Easy'), findsOneWidget);
      await tester.ensureVisible(find.text('Save as…'));
      await tester.tap(find.text('Save as…'));
      await tester.pumpAndSettle();
      expect(find.widgetWithText(TextField, 'Folder (optional)'), findsNothing);
      await tester.enterText(find.widgetWithText(TextField, 'Name'), 'Mine');
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();
      expect(fake.saveSplitConfigCalls.single.toJson().containsKey('folder'), isFalse);
    });

    testWidgets('Save as on a level-4 server sends the folder', (tester) async {
      final fake = _fakeAtLevel(ApiLevels.splitLibrary);
      await _pump(tester, fake);

      await tester.ensureVisible(find.text('Save as…'));
      await tester.tap(find.text('Save as…'));
      await tester.pumpAndSettle();
      await tester.enterText(find.widgetWithText(TextField, 'Name'), 'Hills');
      await tester.enterText(find.widgetWithText(TextField, 'Folder (optional)'), ' Club ');
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();
      expect(fake.saveSplitConfigCalls.single.toJson()['folder'], 'Club');
    });

    testWidgets('a server-info failure falls back to no library', (tester) async {
      final fake = FakeApiClient()
        ..getServerInfoHandler = ({required baseUrl, required token}) async =>
            throw const ApiNetworkException('offline');
      await _pump(tester, fake);
      expect(find.text('Library'), findsNothing);
    });
  });

  group('Library screen', () {
    testWidgets('lists repos and folders; a folder switch calls the server', (tester) async {
      final fake = FakeApiClient()
        ..splitSources = const SplitSourceListDto(sources: [_c25k, _club], canAdd: true);
      await _pump(tester, fake, home: const SplitLibraryScreen());

      expect(find.text('SAT templates (default)'), findsOneWidget);
      expect(find.text('Club plans'), findsOneWidget);
      expect(find.textContaining('private'), findsOneWidget);
      expect(find.text('Couch to 5K'), findsOneWidget);
      expect(find.text('27 splits'), findsOneWidget);
      // The default repo can't be edited or removed.
      expect(find.text('Remove'), findsOneWidget);

      await tester.tap(find.byKey(const ValueKey('folder-f1')));
      await tester.pumpAndSettle();
      expect(fake.splitFolderCalls, [('s1', 'f1', false)]);
      final tile = tester.widget<SwitchListTile>(find.byKey(const ValueKey('folder-f1')));
      expect(tile.value, isFalse);
    });

    testWidgets('Sync now reports the result', (tester) async {
      final fake = FakeApiClient()
        ..splitSources = const SplitSourceListDto(sources: [_c25k])
        ..syncResult = const SplitSourceSyncDto(ok: true, added: 2, updated: 1);
      await _pump(tester, fake, home: const SplitLibraryScreen());

      await tester.tap(find.text('Sync now'));
      await tester.pumpAndSettle();
      expect(fake.syncSplitSourceCalls, ['s1']);
      expect(find.text('SAT templates synced: 2 added, 1 updated.'), findsOneWidget);
    });

    testWidgets('adding a repo sends what was typed', (tester) async {
      final fake = FakeApiClient()
        ..syncResult = const SplitSourceSyncDto(
          ok: false,
          error: 'The repo host answered 404',
          source: _club,
        );
      await _pump(tester, fake, home: const SplitLibraryScreen());

      await tester.tap(find.text('Add a split repo'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextField, 'Repo URL'),
        'https://git.example.org/club/plans',
      );
      await tester.enterText(find.widgetWithText(TextField, 'Access token (private repos)'), 'tok');
      await tester.tap(find.text('Add and sync'));
      await tester.pumpAndSettle();
      expect(fake.addSplitSourceCalls.single.toJson(), {
        'url': 'https://git.example.org/club/plans',
        'ref': 'main',
        'path': 'splits',
        'token': 'tok',
      });
      expect(
        find.text('Club plans added, but the sync failed: The repo host answered 404'),
        findsOneWidget,
      );
    });

    testWidgets('removing a repo asks first', (tester) async {
      final fake = FakeApiClient()
        ..splitSources = const SplitSourceListDto(sources: [_c25k, _club], canAdd: true);
      await _pump(tester, fake, home: const SplitLibraryScreen());

      await tester.tap(find.text('Remove'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Remove'));
      await tester.pumpAndSettle();
      expect(fake.deleteSplitSourceCalls, ['s2']);
      expect(find.text('Club plans'), findsNothing);
    });

    testWidgets('import reads the picked file and reports the result', (tester) async {
      final fake = FakeApiClient()
        ..importResult = const SplitImportResultDto(created: 2, updated: 1, renamed: ['A → A (2)']);
      final file = utf8.encode('{"format": "sat-split-configs", "version": 1, "configs": []}');
      await _pump(
        tester,
        fake,
        home: const SplitLibraryScreen(),
        overrides: [
          splitFilePickerProvider.overrideWithValue(() async => Uint8List.fromList(file)),
        ],
      );

      await tester.tap(find.text('Import a file'));
      await tester.pumpAndSettle();
      expect(fake.importSplitConfigsCalls.single['format'], 'sat-split-configs');
      expect(find.text('Imported: 2 new, 1 replaced (1 renamed).'), findsOneWidget);
    });

    testWidgets('a file that is not JSON is reported without calling the server', (tester) async {
      final fake = FakeApiClient();
      await _pump(
        tester,
        fake,
        home: const SplitLibraryScreen(),
        overrides: [
          splitFilePickerProvider.overrideWithValue(
            () async => Uint8List.fromList(utf8.encode('not json')),
          ),
        ],
      );

      await tester.tap(find.text('Import a file'));
      await tester.pumpAndSettle();
      expect(fake.importSplitConfigsCalls, isEmpty);
      expect(find.textContaining("Couldn't read that file"), findsOneWidget);
    });

    testWidgets('export saves the server file where the user can find it', (tester) async {
      final saved = <(String, String)>[];
      final fake = FakeApiClient()..exportJson = '{"format": "sat-split-configs"}';
      await _pump(
        tester,
        fake,
        home: const SplitLibraryScreen(),
        overrides: [
          splitExportSaverProvider.overrideWithValue((name, contents) async {
            saved.add((name, contents));
            return 'Downloads/SimpleActivityTracker';
          }),
        ],
      );

      await tester.tap(find.text('Export my configs'));
      await tester.pumpAndSettle();
      expect(saved.single.$1, matches(RegExp(r'^split-configs-\d{4}-\d{2}-\d{2}\.json$')));
      expect(saved.single.$2, '{"format": "sat-split-configs"}');
      expect(find.text('Exported to Downloads/SimpleActivityTracker'), findsOneWidget);
    });

    testWidgets('a load failure offers a retry', (tester) async {
      final fake = FakeApiClient()..splitLibraryFailure = const ApiNetworkException('offline');
      await _pump(tester, fake, home: const SplitLibraryScreen());
      expect(find.textContaining('Could not load split repos'), findsOneWidget);
      expect(find.text('Retry'), findsOneWidget);
    });
  });
}
