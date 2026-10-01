import 'dart:io';

import 'package:simple_activity_tracker/core/api/api_client.dart';
import 'package:simple_activity_tracker/core/api/api_exception.dart';
import 'package:simple_activity_tracker/core/api/dto/activity_list_item_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/analysis_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/device_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/live_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/login_response_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/run_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/server_info_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/split_config_dto.dart';
import 'package:simple_activity_tracker/core/api/dto/user_dto.dart';
import 'package:simple_activity_tracker/core/version/api_compat.dart';
import 'package:simple_activity_tracker/domain/models/run_summary.dart';

/// A scriptable [ApiClient] test double. Each method defers to a settable
/// handler field defaulting to a reasonable success response, so a test only
/// overrides the handler(s) it actually cares about. Calls are recorded for
/// assertions on retry counts / ordering.
class FakeApiClient implements ApiClient {
  final List<RunSummary> uploadCalls = [];

  /// The `serverApiLevel` each [uploadRun] call was shaped for, in order.
  final List<int> uploadApiLevels = [];
  int uploadCallCount = 0;
  int getServerInfoCallCount = 0;

  /// Defaults to a server at the app's own API level — override to simulate
  /// an older ([ServerInfoDto.legacy]) or incompatible server.
  Future<ServerInfoDto> Function({required String baseUrl, required String token})?
  getServerInfoHandler;
  int getAnalysisCallCount = 0;
  int getActivityCallCount = 0;

  Future<LoginResponseDto> Function({
    required String baseUrl,
    required String email,
    required String password,
    required String deviceName,
  })?
  loginHandler;

  Future<RunDto> Function({
    required String baseUrl,
    required String token,
    required RunSummary summary,
    required File gpxFile,
  })?
  uploadRunHandler;

  Future<AnalysisDto> Function({
    required String baseUrl,
    required String token,
    required String serverRunId,
  })?
  getAnalysisHandler;

  Future<RunDto> Function({
    required String baseUrl,
    required String token,
    required String serverRunId,
  })?
  getActivityHandler;

  Future<ActivityListResponseDto> Function({
    required String baseUrl,
    required String token,
    String? cursor,
    int limit,
  })?
  listActivitiesHandler;

  final List<SplitConfigSaveRequestDto> saveSplitConfigCalls = [];
  int deleteSplitConfigCallCount = 0;

  Future<List<SplitConfigDto>> Function({required String baseUrl, required String token})?
  listSplitConfigsHandler;

  Future<SplitConfigDto> Function({
    required String baseUrl,
    required String token,
    required SplitConfigSaveRequestDto request,
  })?
  saveSplitConfigHandler;

  Future<void> Function({required String baseUrl, required String token, required String configId})?
  deleteSplitConfigHandler;

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
    return Future.value(
      LoginResponseDto(
        token: 'fake-token',
        device: DeviceDto(
          id: 'd1',
          name: deviceName,
          createdAt: DateTime.utc(2026),
          lastUsedAt: null,
        ),
        user: UserDto(
          id: 'u1',
          email: email,
          displayName: 'Runner',
          isAdmin: false,
        ),
      ),
    );
  }

  @override
  Future<void> logout({required String baseUrl, required String token}) async {}

  @override
  Future<UserDto> me({required String baseUrl, required String token}) {
    return Future.value(
      const UserDto(
        id: 'u1',
        email: 'runner@example.com',
        displayName: 'Runner',
        isAdmin: false,
      ),
    );
  }

  @override
  Future<ServerInfoDto> getServerInfo({required String baseUrl, required String token}) {
    getServerInfoCallCount++;
    final handler = getServerInfoHandler;
    if (handler != null) return handler(baseUrl: baseUrl, token: token);
    return Future.value(
      const ServerInfoDto(version: '1.3.0', apiLevel: kAppApiLevel, minAppApiLevel: 0),
    );
  }

  @override
  Future<RunDto> uploadRun({
    required String baseUrl,
    required String token,
    required RunSummary summary,
    required File gpxFile,
    required int serverApiLevel,
  }) {
    uploadCallCount++;
    uploadCalls.add(summary);
    uploadApiLevels.add(serverApiLevel);
    final handler = uploadRunHandler;
    if (handler != null) {
      return handler(
        baseUrl: baseUrl,
        token: token,
        summary: summary,
        gpxFile: gpxFile,
      );
    }
    return Future.value(
      RunDto(
        id: 'server-${summary.clientRunId}',
        clientRunId: summary.clientRunId,
        startedAt: summary.startedAt,
        endedAt: summary.endedAt,
        activityType: summary.activityMode.name,
        title: null,
        notes: null,
        deviceName: null,
        clientSummary: summary.toJson(),
        sourcePlatform: summary.sourcePlatform,
        sourceAppVersion: summary.sourceAppVersion,
        analysis: const AnalysisDto(status: 'pending', result: null),
        tags: const [],
        splitPlan: null,
      ),
    );
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

  @override
  Future<RunDto> getActivity({
    required String baseUrl,
    required String token,
    required String serverRunId,
  }) {
    getActivityCallCount++;
    final handler = getActivityHandler;
    if (handler != null) {
      return handler(baseUrl: baseUrl, token: token, serverRunId: serverRunId);
    }
    return Future.value(
      RunDto(
        id: serverRunId,
        clientRunId: 'client-$serverRunId',
        startedAt: DateTime.utc(2026),
        endedAt: DateTime.utc(2026, 1, 1, 0, 30),
        activityType: 'running',
        title: null,
        notes: null,
        deviceName: null,
        clientSummary: const {},
        sourcePlatform: 'android',
        sourceAppVersion: '1.0.0+1',
        analysis: const AnalysisDto(status: 'pending', result: null),
        tags: const [],
        splitPlan: null,
      ),
    );
  }

  @override
  Future<ActivityListResponseDto> listActivities({
    required String baseUrl,
    required String token,
    String? cursor,
    int limit = 50,
  }) {
    final handler = listActivitiesHandler;
    if (handler != null) {
      return handler(baseUrl: baseUrl, token: token, cursor: cursor, limit: limit);
    }
    return Future.value(const ActivityListResponseDto(activities: [], nextCursor: null));
  }

  @override
  Future<List<SplitConfigDto>> listSplitConfigs({
    required String baseUrl,
    required String token,
  }) {
    final handler = listSplitConfigsHandler;
    if (handler != null) return handler(baseUrl: baseUrl, token: token);
    return Future.value(const []);
  }

  @override
  Future<SplitConfigDto> saveSplitConfig({
    required String baseUrl,
    required String token,
    required SplitConfigSaveRequestDto request,
  }) {
    saveSplitConfigCalls.add(request);
    final handler = saveSplitConfigHandler;
    if (handler != null) {
      return handler(baseUrl: baseUrl, token: token, request: request);
    }
    final now = DateTime.utc(2026);
    return Future.value(
      SplitConfigDto(id: 'sc1', name: request.name, plan: request.plan, createdAt: now, updatedAt: now),
    );
  }

  @override
  Future<void> deleteSplitConfig({
    required String baseUrl,
    required String token,
    required String configId,
  }) {
    deleteSplitConfigCallCount++;
    final handler = deleteSplitConfigHandler;
    if (handler != null) {
      return handler(baseUrl: baseUrl, token: token, configId: configId);
    }
    return Future.value();
  }

  // --- live tracking (issue #130) ------------------------------------------
  // A tiny in-memory server: it stores points per client activity id and
  // answers with next_index exactly like the real one (a retry is a no-op, a
  // gap reports where to resend from), so LiveUploadService tests exercise
  // the real protocol. Set [liveFailure] to make every live call throw.

  final Map<String, int> liveStoredPoints = {};
  final Map<String, String> liveStates = {};
  final List<LivePointsRequestDto> livePointCalls = [];
  final List<LiveSessionRequestDto> livePutCalls = [];
  final List<String> liveDeleteCalls = [];
  final List<LiveSharingRequestDto> liveSharingCalls = [];
  final Set<String> closedLiveSessions = {};

  /// Every call made to a live/sharing endpoint, by name, in order — for
  /// asserting that a queued sharing change goes before any points.
  final List<String> liveCallLog = [];

  ApiException? liveFailure;

  List<UserDirectoryEntryDto> users = const [
    UserDirectoryEntryDto(id: 'u-ann', displayName: 'Ann'),
    UserDirectoryEntryDto(id: 'u-bob', displayName: 'Bob'),
  ];
  MySharesDto myShares = const MySharesDto(liveSharingPaused: false, shares: []);

  void _liveCall(String name) {
    liveCallLog.add(name);
    final failure = liveFailure;
    if (failure != null) throw failure;
  }

  @override
  Future<LiveSessionStateDto> putLiveSession({
    required String baseUrl,
    required String token,
    required String clientActivityId,
    required LiveSessionRequestDto request,
  }) async {
    _liveCall('putLiveSession');
    if (closedLiveSessions.contains(clientActivityId)) {
      throw const ApiRejectedException('closed', statusCode: 410);
    }
    livePutCalls.add(request);
    final stored = liveStoredPoints.putIfAbsent(clientActivityId, () => 0);
    return LiveSessionStateDto(nextIndex: stored, state: liveStates[clientActivityId] ?? 'active');
  }

  @override
  Future<LiveSessionStateDto> postLivePoints({
    required String baseUrl,
    required String token,
    required String clientActivityId,
    required LivePointsRequestDto request,
  }) async {
    _liveCall('postLivePoints');
    if (closedLiveSessions.contains(clientActivityId)) {
      throw const ApiRejectedException('closed', statusCode: 410);
    }
    final stored = liveStoredPoints[clientActivityId];
    if (stored == null) throw const ApiRejectedException('no session', statusCode: 404);
    livePointCalls.add(request);
    if (request.fromIndex > stored) {
      return LiveSessionStateDto(nextIndex: stored, state: 'active');
    }
    final end = request.fromIndex + request.points.length;
    liveStoredPoints[clientActivityId] = end > stored ? end : stored;
    liveStates[clientActivityId] = request.state;
    return LiveSessionStateDto(
      nextIndex: liveStoredPoints[clientActivityId]!,
      state: request.state,
    );
  }

  @override
  Future<void> deleteLiveSession({
    required String baseUrl,
    required String token,
    required String clientActivityId,
  }) async {
    _liveCall('deleteLiveSession');
    liveDeleteCalls.add(clientActivityId);
    liveStoredPoints.remove(clientActivityId);
  }

  @override
  Future<List<UserDirectoryEntryDto>> listUsers({
    required String baseUrl,
    required String token,
  }) async {
    _liveCall('listUsers');
    return users;
  }

  @override
  Future<MySharesDto> getMyShares({required String baseUrl, required String token}) async {
    _liveCall('getMyShares');
    return myShares;
  }

  @override
  Future<MySharesDto> putLiveSharing({
    required String baseUrl,
    required String token,
    required LiveSharingRequestDto request,
  }) async {
    _liveCall('putLiveSharing');
    liveSharingCalls.add(request);
    final byId = {for (final user in users) user.id: user.displayName};
    myShares = MySharesDto(
      liveSharingPaused: request.liveSharingPaused,
      shares: [
        for (final id in request.liveViewerIds)
          ShareDto(
            viewerId: id,
            displayName: byId[id] ?? id,
            canViewLive: true,
            canViewHistory: false,
          ),
      ],
    );
    return myShares;
  }
}
