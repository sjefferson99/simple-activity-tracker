import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:simple_activity_tracker/core/api/dto/activity_list_item_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/login_response_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/run_dto.dart';

Map<String, dynamic> _loadFixture(String name) =>
    jsonDecode(File('test/fixtures/$name').readAsStringSync())
        as Map<String, dynamic>;

void main() {
  group('LoginResponseDto', () {
    test('parses the server fixture', () {
      final dto = LoginResponseDto.fromJson(
        _loadFixture('login_response_sample.json'),
      );

      expect(dto.token, 'srdt_examplefaketoken1234567890');
      expect(dto.device.id, '22222222-2222-2222-2222-222222222222');
      expect(dto.device.name, 'Pixel 8');
      expect(dto.device.lastUsedAt, isNull);
      expect(dto.user.email, 'runner@example.com');
      expect(dto.user.isAdmin, isFalse);
    });
  });

  group('RunDto', () {
    test('parses the server fixture, including nested analysis', () {
      final dto = RunDto.fromJson(_loadFixture('run_dto_sample.json'));

      expect(dto.id, '44444444-4444-4444-4444-444444444444');
      expect(dto.clientRunId, '11111111-1111-1111-1111-111111111111');
      expect(dto.activityType, 'running');
      expect(dto.title, isNull);
      expect(dto.notes, isNull);
      expect(dto.sourcePlatform, 'android');
      expect(dto.clientSummary['distance_meters'], 3000.0);
      expect(dto.analysis.isDone, isTrue);
      expect(dto.analysis.result?['distance_meters'], 3017.6);
      expect(dto.analysis.result?['splits'], hasLength(1));
      expect(dto.deviceName, 'Pixel 8');
      expect(dto.tags, hasLength(1));
      expect(dto.tags.single.name, 'morning');
      expect(dto.splitPlan?.rollingTargetMps, 3.33);
      expect(dto.splitPlan?.targetsAs, 'pace');
      expect(dto.splitPlan?.customSplits, isEmpty);
    });

    test('a pending analysis has a null result', () {
      final json = _loadFixture('run_dto_sample.json');
      json['analysis'] = {'status': 'pending', 'result': null};

      final dto = RunDto.fromJson(json);

      expect(dto.analysis.isPending, isTrue);
      expect(dto.analysis.result, isNull);
    });

    test(
      'tolerates a pre-#101 record with no device_name/tags/split_plan',
      () {
        final json = _loadFixture('run_dto_sample.json');
        json.remove('device_name');
        json.remove('tags');
        json.remove('split_plan');

        final dto = RunDto.fromJson(json);

        expect(dto.deviceName, isNull);
        expect(dto.tags, isEmpty);
        expect(dto.splitPlan, isNull);
      },
    );

    test('custom_splits parses (size, target) pairs, including a null target', () {
      final json = _loadFixture('run_dto_sample.json');
      json['split_plan'] = {
        'rolling_target_mps': null,
        'custom_splits': [
          [500.0, 3.33],
          [300.0, null],
        ],
        'targets_as': 'speed',
      };

      final dto = RunDto.fromJson(json);

      expect(dto.splitPlan?.rollingTargetMps, isNull);
      expect(dto.splitPlan?.customSplits, [(500.0, 3.33), (300.0, null)]);
      expect(dto.splitPlan?.targetsAs, 'speed');
    });
  });

  group('ActivityListResponseDto', () {
    test('parses a page of activities and a next_cursor', () {
      final dto = ActivityListResponseDto.fromJson({
        'activities': [
          {
            'id': 'a1',
            'activity_type': 'running',
            'started_at': '2026-01-01T07:00:00Z',
            'ended_at': '2026-01-01T07:30:00Z',
            'title': 'Morning run',
            'distance_meters': 5000.0,
            'moving_seconds': 1500.0,
            'tags': [
              {'id': 't1', 'name': 'morning'},
            ],
          },
        ],
        'next_cursor': 'abc123',
      });

      expect(dto.activities, hasLength(1));
      expect(dto.activities.single.title, 'Morning run');
      expect(dto.activities.single.tags.single.name, 'morning');
      expect(dto.nextCursor, 'abc123');
    });

    test('a null next_cursor means there is no further page', () {
      final dto = ActivityListResponseDto.fromJson({
        'activities': <Map<String, dynamic>>[],
        'next_cursor': null,
      });

      expect(dto.activities, isEmpty);
      expect(dto.nextCursor, isNull);
    });
  });
}
