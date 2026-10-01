import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:simple_activity_tracker/core/api/api_exception.dart';
import 'package:simple_activity_tracker/core/api/dto/live_dto.dart';
import 'package:simple_activity_tracker/core/api/http_api_client.dart';
import 'package:simple_activity_tracker/domain/models/track_point.dart';
import 'package:simple_activity_tracker/domain/tracking/activity_mode.dart';
import 'package:simple_activity_tracker/domain/tracking/split_plan.dart';

const _base = 'https://runner.example.com';
const _id = '13013013-0130-0130-0130-130130130130';

http.Response _json(Object body, int status) => http.Response(
  jsonEncode(body),
  status,
  headers: {'content-type': 'application/json'},
);

LivePointsRequestDto _batch(int from) => LivePointsRequestDto(
  fromIndex: from,
  state: 'active',
  points: [
    LivePointDto(
      TrackPoint(
        latitude: 51.5,
        longitude: -0.12,
        timestamp: DateTime.utc(2026, 1, 1, 7),
        accuracyMeters: 4,
      ),
      0,
    ),
  ],
);

void main() {
  test('putLiveSession PUTs the metadata and reads next_index', () async {
    late http.Request sent;
    final client = HttpApiClient(
      client: MockClient((request) async {
        sent = request;
        return _json({'next_index': 7, 'state': 'active'}, 200);
      }),
    );
    final result = await client.putLiveSession(
      baseUrl: _base,
      token: 't',
      clientActivityId: _id,
      request: LiveSessionRequestDto(
        activityMode: ActivityMode.running,
        startedAt: DateTime.utc(2026, 1, 1, 7),
        splitPlan: SplitPlan.defaultPlan,
      ),
    );
    expect(sent.method, 'PUT');
    expect(sent.url.path, '/api/v1/live/$_id');
    expect(sent.headers['Authorization'], 'Bearer t');
    final body = jsonDecode(sent.body) as Map<String, dynamic>;
    expect(body['activity_type'], 'running');
    expect(body['started_at'], '2026-01-01T07:00:00.000Z');
    expect(body['split_plan'], isA<Map<String, dynamic>>());
    expect(result.nextIndex, 7);
  });

  test('postLivePoints: a 409 gap is an answer carrying where to resend from', () async {
    final client = HttpApiClient(
      client: MockClient(
        (request) async => _json({
          'error': {'code': 'index_gap', 'message': 'Expected 3', 'next_index': 3},
        }, 409),
      ),
    );
    final result = await client.postLivePoints(
      baseUrl: _base,
      token: 't',
      clientActivityId: _id,
      request: _batch(9),
    );
    expect(result.nextIndex, 3);
  });

  test('postLivePoints: 410 (already saved) and 404 (no session) are rejections', () async {
    for (final status in [410, 404]) {
      final client = HttpApiClient(
        client: MockClient(
          (request) async => _json({
            'error': {'code': 'x', 'message': 'no'},
          }, status),
        ),
      );
      expect(
        () => client.postLivePoints(baseUrl: _base, token: 't', clientActivityId: _id, request: _batch(0)),
        throwsA(isA<ApiRejectedException>().having((e) => e.statusCode, 'statusCode', status)),
      );
    }
  });

  test('a 409 without next_index is still an error, not a silent rewind to 0', () async {
    final client = HttpApiClient(
      client: MockClient((request) async => _json({'error': {'code': 'x', 'message': 'no'}}, 409)),
    );
    expect(
      () => client.postLivePoints(baseUrl: _base, token: 't', clientActivityId: _id, request: _batch(0)),
      throwsA(isA<ApiRejectedException>()),
    );
  });

  test('deleteLiveSession tolerates a 404', () async {
    final client = HttpApiClient(
      client: MockClient((request) async {
        expect(request.method, 'DELETE');
        return _json({'error': {'code': 'not_found', 'message': 'gone'}}, 404);
      }),
    );
    await client.deleteLiveSession(baseUrl: _base, token: 't', clientActivityId: _id);
  });

  test('sharing endpoints read tolerantly and send the whole setting', () async {
    final client = HttpApiClient(
      client: MockClient((request) async {
        switch (request.url.path) {
          case '/api/v1/users':
            return _json({
              'users': [
                {'id': 'u1', 'display_name': 'Ann'},
                {'display_name': 'no id, skipped'},
                'not an object',
              ],
            }, 200);
          case '/api/v1/me/live-sharing':
            expect(request.method, 'PUT');
            expect(jsonDecode(request.body), {
              'live_sharing_paused': true,
              'live_viewer_ids': ['u1', 'u2'],
            });
            return _json({
              'live_sharing_paused': true,
              'shares': [
                {'viewer_id': 'u1', 'display_name': 'Ann', 'can_view_live': true},
                {'viewer_id': 'u2', 'can_view_live': true, 'can_view_history': true, 'new_field': 1},
              ],
            }, 200);
        }
        fail('unexpected ${request.url}');
      }),
    );
    final users = await client.listUsers(baseUrl: _base, token: 't');
    expect([for (final u in users) u.displayName], ['Ann']);

    final shares = await client.putLiveSharing(
      baseUrl: _base,
      token: 't',
      request: const LiveSharingRequestDto(liveSharingPaused: true, liveViewerIds: {'u2', 'u1'}),
    );
    expect(shares.liveSharingPaused, isTrue);
    expect(shares.liveViewerIds, {'u1', 'u2'});
    expect(shares.shares.last.displayName, 'u2');
    expect(shares.shares.first.canViewHistory, isFalse);
  });
}
