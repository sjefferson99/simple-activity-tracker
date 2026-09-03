import 'dart:io';

import 'package:simple_runner/core/api/api_client.dart';
import 'package:simple_runner/core/api/dto/analysis_dto.dart';
import 'package:simple_runner/core/api/dto/device_dto.dart';
import 'package:simple_runner/core/api/dto/login_response_dto.dart';
import 'package:simple_runner/core/api/dto/run_dto.dart';
import 'package:simple_runner/core/api/dto/user_dto.dart';
import 'package:simple_runner/domain/models/run_summary.dart';

/// A scriptable [ApiClient] test double. Each method defers to a settable
/// handler field defaulting to a reasonable success response, so a test only
/// overrides the handler(s) it actually cares about. Calls are recorded for
/// assertions on retry counts / ordering.
class FakeApiClient implements ApiClient {
  final List<RunSummary> uploadCalls = [];
  int uploadCallCount = 0;
  int getAnalysisCallCount = 0;

  Future<LoginResponseDto> Function({
    required String baseUrl,
    required String email,
    required String password,
    required String deviceName,
  })? loginHandler;

  Future<RunDto> Function({
    required String baseUrl,
    required String token,
    required RunSummary summary,
    required File gpxFile,
  })? uploadRunHandler;

  Future<AnalysisDto> Function({
    required String baseUrl,
    required String token,
    required String serverRunId,
  })? getAnalysisHandler;

  @override
  Future<LoginResponseDto> login({
    required String baseUrl,
    required String email,
    required String password,
    required String deviceName,
  }) {
    final handler = loginHandler;
    if (handler != null) {
      return handler(
        baseUrl: baseUrl,
        email: email,
        password: password,
        deviceName: deviceName,
      );
    }
    return Future.value(LoginResponseDto(
      token: 'fake-token',
      device: DeviceDto(id: 'd1', name: deviceName, createdAt: DateTime.utc(2026), lastUsedAt: null),
      user: UserDto(id: 'u1', email: email, displayName: 'Runner', isAdmin: false),
    ));
  }

  @override
  Future<void> logout({required String baseUrl, required String token}) async {}

  @override
  Future<UserDto> me({required String baseUrl, required String token}) {
    return Future.value(
      const UserDto(id: 'u1', email: 'runner@example.com', displayName: 'Runner', isAdmin: false),
    );
  }

  @override
  Future<RunDto> uploadRun({
    required String baseUrl,
    required String token,
    required RunSummary summary,
    required File gpxFile,
  }) {
    uploadCallCount++;
    uploadCalls.add(summary);
    final handler = uploadRunHandler;
    if (handler != null) {
      return handler(baseUrl: baseUrl, token: token, summary: summary, gpxFile: gpxFile);
    }
    return Future.value(RunDto(
      id: 'server-${summary.clientRunId}',
      clientRunId: summary.clientRunId,
      startedAt: summary.startedAt,
      endedAt: summary.endedAt,
      title: null,
      notes: null,
      clientSummary: summary.toJson(),
      sourcePlatform: summary.sourcePlatform,
      sourceAppVersion: summary.sourceAppVersion,
      analysis: const AnalysisDto(status: 'pending', result: null),
    ));
  }

  @override
  Future<AnalysisDto> getAnalysis({
    required String baseUrl,
    required String token,
    required String serverRunId,
  }) {
    getAnalysisCallCount++;
    final handler = getAnalysisHandler;
    if (handler != null) {
      return handler(baseUrl: baseUrl, token: token, serverRunId: serverRunId);
    }
    return Future.value(const AnalysisDto(status: 'pending', result: null));
  }
}
