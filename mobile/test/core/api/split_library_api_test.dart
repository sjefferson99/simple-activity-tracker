import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:simple_activity_tracker/core/api/api_exception.dart';
import 'package:simple_activity_tracker/core/api/dto/split_config_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/split_source_dto.dart';
import 'package:simple_activity_tracker/core/api/http_api_client.dart';
import 'package:simple_activity_tracker/core/version/api_compat.dart';
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';
import 'package:simple_activity_tracker/domain/tracking/split_preference.dart';

/// Split library (issue #143, API level 4): the DTOs read tolerantly and the
/// client calls the right endpoints.

const _base = 'https://example.com';

Map<String, dynamic> _configJson({Map<String, dynamic> extra = const {}}) => {
  'id': 'c1',
  'name': 'C25K week 1 run 1',
  'plan': {
    'split_type': 'time_min',
    'split_value': 1,
    'rolling_target_mps': null,
    'custom_splits': [
      [300, 1.667],
      [60, 2.222],
    ],
    'targets_as': 'pace',
  },
  'created_at': '2026-11-24T00:00:00Z',
  'updated_at': '2026-11-24T00:00:00Z',
  ...extra,
};

Map<String, dynamic> _sourceJson() => {
  'id': 's1',
  'name': 'Simple Activity Tracker templates',
  'url': 'https://github.com/o/r',
  'host_kind': 'github',
  'ref': 'main',
  'path': 'splits',
  'enabled': true,
  'is_default': true,
  'has_token': false,
  'last_synced_at': '2026-11-24T10:00:00Z',
  'last_commit': 'abc',
  'last_error': null,
  'warnings': ['bad.json: not valid JSON'],
  'folders': [
    {
      'id': 'f1',
      'folder': 'couch-to-5k',
      'name': 'Couch to 5K',
      'description': 'Nine weeks',
      'enabled': true,
      'template_count': 27,
    },
    'not a folder',
    {'name': 'no id, skipped'},
  ],
};

HttpApiClient _client(Future<http.Response> Function(http.Request) handler) =>
    HttpApiClient(client: MockClient(handler));

void main() {
  group('SplitConfigDto (level 4 fields)', () {
    test('reads folder, read-only and source', () {
      final dto = SplitConfigDto.fromJson(
        _configJson(
          extra: {
            'uid': 'u1',
            'folder': 'couch-to-5k',
            'folder_name': 'Couch to 5K',
            'read_only': true,
            'source': {'id': 's1', 'name': 'SAT templates'},
          },
        ),
      );
      expect(dto.folderName, 'Couch to 5K');
      expect(dto.readOnly, isTrue);
      expect(dto.sourceName, 'SAT templates');
    });

    test('an older server leaves them at their defaults', () {
      final dto = SplitConfigDto.fromJson(_configJson());
      expect(dto.folderName, isNull);
      expect(dto.readOnly, isFalse);
      expect(dto.sourceName, isNull);
    });

    test('wrong types and blank folders never throw', () {
      final dto = SplitConfigDto.fromJson(
        _configJson(extra: {'folder': '  ', 'read_only': 'yes', 'source': 'nope'}),
      );
      expect(dto.folderName, isNull);
      expect(dto.readOnly, isFalse);
      expect(dto.sourceName, isNull);
    });

    test("an own config's folder is used when there's no folder_name", () {
      expect(SplitConfigDto.fromJson(_configJson(extra: {'folder': 'Club'})).folderName, 'Club');
    });
  });

  group('SplitConfigSaveRequestDto folder', () {
    const plan = SplitPlan(base: SplitPreference.defaultPreference);

    test('is sent to a level-4 server, trimmed', () {
      final json = const SplitConfigSaveRequestDto(
        name: 'Hills',
        plan: plan,
        serverApiLevel: ApiLevels.splitLibrary,
        folder: ' Club ',
      ).toJson();
      expect(json['folder'], 'Club');
    });

    test('is never sent to an older server', () {
      final json = const SplitConfigSaveRequestDto(
        name: 'Hills',
        plan: plan,
        serverApiLevel: ApiLevels.splitConfigLayout,
        folder: 'Club',
      ).toJson();
      expect(json.containsKey('folder'), isFalse);
    });

    test('is left out when not given', () {
      final json = const SplitConfigSaveRequestDto(
        name: 'Hills',
        plan: plan,
        serverApiLevel: ApiLevels.splitLibrary,
      ).toJson();
      expect(json.containsKey('folder'), isFalse);
    });
  });

  group('SplitSourceDto', () {
    test('parses a source, skipping malformed folders', () {
      final source = SplitSourceDto.fromJson(_sourceJson())!;
      expect(source.name, 'Simple Activity Tracker templates');
      expect(source.isDefault, isTrue);
      expect(source.lastSyncedAt, DateTime.utc(2026, 11, 24, 10));
      expect(source.warnings, ['bad.json: not valid JSON']);
      expect(source.folders, hasLength(1));
      expect(source.folders.single.name, 'Couch to 5K');
      expect(source.folders.single.templateCount, 27);
    });

    test('a source without an id is dropped; missing fields default', () {
      expect(SplitSourceDto.fromJson({'name': 'x'}), isNull);
      final minimal = SplitSourceDto.fromJson({'id': 's'})!;
      expect(minimal.enabled, isTrue);
      expect(minimal.folders, isEmpty);
      expect(minimal.lastSyncedAt, isNull);
    });

    test('sync summary', () {
      expect(const SplitSourceSyncDto(ok: true).summary, 'no changes');
      expect(
        const SplitSourceSyncDto(ok: true, added: 2, removed: 1).summary,
        '2 added, 1 removed',
      );
    });

    test('update and create bodies leave out what is not set', () {
      expect(const SplitSourceUpdateDto(enabled: false).toJson(), {'enabled': false});
      expect(const SplitSourceUpdateDto(clearToken: true).toJson(), {'clear_token': true});
      expect(const SplitSourceCreateDto(url: ' https://github.com/o/r ', ref: ' ').toJson(), {
        'url': 'https://github.com/o/r',
        'ref': 'main',
        'path': 'splits',
      });
    });
  });

  group('HttpApiClient split library calls', () {
    test('lists sources', () async {
      final client = _client((request) async {
        expect(request.method, 'GET');
        expect(request.url, Uri.parse('$_base/api/v1/split-sources'));
        expect(request.headers['Authorization'], 'Bearer t');
        return http.Response(
          jsonEncode({
            'sources': [_sourceJson()],
            'can_add': true,
          }),
          200,
        );
      });
      final list = await client.listSplitSources(baseUrl: _base, token: 't');
      expect(list.canAdd, isTrue);
      expect(list.sources.single.id, 's1');
    });

    test('adds a source and reads the sync result', () async {
      final client = _client((request) async {
        expect(request.method, 'POST');
        expect(request.url.path, '/api/v1/split-sources');
        expect(jsonDecode(request.body), {
          'url': 'https://git.example.org/me/plans',
          'host_kind': 'gitea',
          'ref': 'main',
          'path': 'splits',
          'token': 'secret',
        });
        return http.Response(
          jsonEncode({
            'ok': false,
            'added': 0,
            'updated': 0,
            'removed': 0,
            'error': 'The repo host answered 404',
            'source': _sourceJson(),
          }),
          201,
        );
      });
      final result = await client.addSplitSource(
        baseUrl: _base,
        token: 't',
        request: const SplitSourceCreateDto(
          url: 'https://git.example.org/me/plans',
          hostKind: 'gitea',
          token: 'secret',
        ),
      );
      expect(result.ok, isFalse);
      expect(result.error, 'The repo host answered 404');
      expect(result.source?.id, 's1');
    });

    test('toggles a folder', () async {
      final client = _client((request) async {
        expect(request.method, 'PATCH');
        expect(request.url.path, '/api/v1/split-sources/s1/folders/f1');
        expect(jsonDecode(request.body), {'enabled': false});
        return http.Response(jsonEncode(_sourceJson()), 200);
      });
      final source = await client.setSplitFolderEnabled(
        baseUrl: _base,
        token: 't',
        sourceId: 's1',
        folderId: 'f1',
        enabled: false,
      );
      expect(source?.id, 's1');
    });

    test('syncs, updates and deletes a source', () async {
      final calls = <String>[];
      final client = _client((request) async {
        calls.add('${request.method} ${request.url.path}');
        if (request.method == 'DELETE') return http.Response('', 204);
        if (request.url.path.endsWith('/sync')) {
          return http.Response(jsonEncode({'ok': true, 'added': 3}), 200);
        }
        expect(jsonDecode(request.body), {'ref': 'v2'});
        return http.Response(jsonEncode(_sourceJson()), 200);
      });
      final sync = await client.syncSplitSource(baseUrl: _base, token: 't', sourceId: 's1');
      expect(sync.added, 3);
      await client.updateSplitSource(
        baseUrl: _base,
        token: 't',
        sourceId: 's1',
        update: const SplitSourceUpdateDto(ref: 'v2'),
      );
      await client.deleteSplitSource(baseUrl: _base, token: 't', sourceId: 's1');
      expect(calls, [
        'POST /api/v1/split-sources/s1/sync',
        'PATCH /api/v1/split-sources/s1',
        'DELETE /api/v1/split-sources/s1',
      ]);
    });

    test('exports as text and imports a document', () async {
      final client = _client((request) async {
        if (request.method == 'GET') {
          expect(request.url.path, '/api/v1/split-configs/export');
          return http.Response.bytes(
            utf8.encode('{"format": "sat-split-configs", "configs": [{"name": "Hügel"}]}'),
            200,
          );
        }
        expect(request.url.path, '/api/v1/split-configs/import');
        expect(jsonDecode(request.body)['format'], 'sat-split-configs');
        return http.Response.bytes(
          utf8.encode(
            jsonEncode({
              'created': 1,
              'updated': 2,
              'renamed': ['A → A (2)'],
              'errors': [],
            }),
          ),
          200,
          headers: {'content-type': 'application/json'},
        );
      });
      final text = await client.exportSplitConfigs(baseUrl: _base, token: 't');
      expect(text, contains('Hügel'));
      final result = await client.importSplitConfigs(
        baseUrl: _base,
        token: 't',
        document: jsonDecode(text) as Map<String, dynamic>,
      );
      expect((result.created, result.updated), (1, 2));
      expect(result.renamed, ['A → A (2)']);
    });

    test('a rejected import surfaces the server message', () async {
      final client = _client(
        (request) async => http.Response(
          jsonEncode({
            'error': {'code': 'invalid_file', 'message': "Couldn't import: not a split config file"},
          }),
          422,
        ),
      );
      expect(
        () => client.importSplitConfigs(baseUrl: _base, token: 't', document: const {}),
        throwsA(
          isA<ApiRejectedException>().having(
            (e) => e.message,
            'message',
            contains('not a split config file'),
          ),
        ),
      );
    });
  });
}
