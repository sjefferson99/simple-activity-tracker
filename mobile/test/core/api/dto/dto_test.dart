import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
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
    });

    test('a pending analysis has a null result', () {
      final json = _loadFixture('run_dto_sample.json');
      json['analysis'] = {'status': 'pending', 'result': null};

      final dto = RunDto.fromJson(json);

      expect(dto.analysis.isPending, isTrue);
      expect(dto.analysis.result, isNull);
    });
  });
}
