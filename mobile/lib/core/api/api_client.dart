import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../domain/models/run_summary.dart';
import 'cert_trust_store.dart';
import 'dto/activity_list_item_dto.dart';
import 'dto/analysis_dto.dart';
import 'dto/login_response_dto.dart';
import 'dto/run_dto.dart';
import 'dto/split_config_dto.dart';
import 'dto/user_dto.dart';
import 'http_api_client.dart';

/// Shared with [apiClientProvider] so a certificate the user trusts from
/// the Settings screen's trust-on-first-use dialog is picked up by the same
/// [HttpApiClient] used for every other request, not a second store that
/// never sees the write.
final certTrustStoreProvider = Provider<CertTrustStore>((ref) => CertTrustStore());

final apiClientProvider = Provider<ApiClient>(
  (ref) => HttpApiClient(certTrustStore: ref.read(certTrustStoreProvider)),
);

/// The server's `/api/v1` surface this app needs (docs/WEB-PLAN.md §5.2).
/// `baseUrl` and `token` are passed per call rather than fixed at
/// construction, so a server URL or credential change (Settings) takes
/// effect on the very next call without rebuilding the client, and so
/// SyncService/AuthService stay the only things that need to know current
/// values. Every method throws an [ApiException] subtype on failure —
/// callers never need to inspect a raw status code.
abstract class ApiClient {
  Future<LoginResponseDto> login({
    required String baseUrl,
    required String email,
    required String password,
    required String deviceName,
  });

  Future<void> logout({required String baseUrl, required String token});

  Future<UserDto> me({required String baseUrl, required String token});

  /// Idempotent on the summary's `clientRunId` — a retried upload after a
  /// timeout returns the same run rather than creating a duplicate.
  Future<RunDto> uploadRun({
    required String baseUrl,
    required String token,
    required RunSummary summary,
    required File gpxFile,
  });

  Future<AnalysisDto> getAnalysis({
    required String baseUrl,
    required String token,
    required String serverRunId,
  });

  /// The full activity record — headline stats, tags, split plan, and
  /// analysis — for the activity detail screen (issue #101).
  Future<RunDto> getActivity({
    required String baseUrl,
    required String token,
    required String serverRunId,
  });

  /// One page of the signed-in user's activities, newest first (issue #101).
  /// [cursor] is the previous page's `nextCursor`; omit for the first page.
  Future<ActivityListResponseDto> listActivities({
    required String baseUrl,
    required String token,
    String? cursor,
    int limit = 50,
  });

  /// The signed-in user's saved split configs (issue #126), sorted by name —
  /// fetched fresh on every call, never cached locally (docs/
  /// SPLIT-CONFIGS-PLAN.md O3).
  Future<List<SplitConfigDto>> listSplitConfigs({
    required String baseUrl,
    required String token,
  });

  /// Creates a new saved split config, or — with `overwrite: true` on
  /// [request] — replaces an existing same-named one in place. Throws
  /// [ApiRejectedException] with `statusCode == 409` on a name collision
  /// when not overwriting, so the caller can offer to retry with overwrite.
  Future<SplitConfigDto> saveSplitConfig({
    required String baseUrl,
    required String token,
    required SplitConfigSaveRequestDto request,
  });

  Future<void> deleteSplitConfig({
    required String baseUrl,
    required String token,
    required String configId,
  });
}
