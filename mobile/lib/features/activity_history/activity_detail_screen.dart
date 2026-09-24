import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/api/dto/run_dto.dart';
import '../../core/api/tolerant_json.dart';
import '../../core/auth/auth_state_controller.dart';
import '../../core/units/units.dart';
import 'splits_targets_view.dart';

/// Fetches one activity's full server record (issue #101) — headline stats,
/// tags, split plan, and analysis. Keyed by server activity id so the same
/// provider instance is reused if a screen is revisited for the same id.
/// Deliberately a plain [FutureProvider.family], not cached across app
/// restarts — this plan's D3 explicitly rules out any local persistence of
/// server activity data for v1.
final activityDetailProvider = FutureProvider.family<RunDto, String>((ref, activityId) async {
  final auth = await ref.watch(authStateControllerProvider.future);
  final baseUrl = auth.serverUrl;
  final token = auth.token;
  if (baseUrl == null || token == null) {
    throw StateError('Not signed in');
  }
  return ref.read(apiClientProvider).getActivity(
        baseUrl: baseUrl,
        token: token,
        serverRunId: activityId,
      );
});

/// The server-backed activity detail screen — headline stats and, once
/// analysis is done, the splits/targets table (issue #101). Reached from the
/// activity list (Slice B) and from the post-Stop summary screen's "View
/// full summary" link (Slice C) once that activity has finished uploading.
class ActivityDetailScreen extends ConsumerWidget {
  final String activityId;

  const ActivityDetailScreen({required this.activityId, super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final activity = ref.watch(activityDetailProvider(activityId));

    return Scaffold(
      appBar: AppBar(title: const Text('Activity')),
      body: activity.when(
        data: (run) => _ActivityDetailBody(run: run),
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (error, _) => Center(child: Text('Could not load activity: $error')),
      ),
    );
  }
}

class _ActivityDetailBody extends StatelessWidget {
  final RunDto run;

  const _ActivityDetailBody({required this.run});

  @override
  Widget build(BuildContext context) {
    final analysis = run.analysis;
    final result = analysis.result;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            run.title ?? formatActivityDate(run.startedAt.toLocal()),
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 4),
          Text(
            // The date always shows, even with a title set — otherwise a
            // named activity would show no date at all.
            run.title != null
                ? '${run.activityType} · ${formatActivityDate(run.startedAt.toLocal())}'
                : run.activityType,
            style: Theme.of(context).textTheme.bodySmall,
          ),
          if (run.tags.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: [
                for (final tag in run.tags) Chip(label: Text(tag.name)),
              ],
            ),
          ],
          const SizedBox(height: 16),
          if (analysis.isPending)
            const Text('Analysis pending', style: TextStyle(fontStyle: FontStyle.italic))
          else if (analysis.isFailed)
            const Text('Analysis failed', style: TextStyle(fontStyle: FontStyle.italic))
          else if (result != null) ...[
            _HeadlineStats(result: result),
            const SizedBox(height: 24),
            SplitsTargetsView(analysisResult: result),
          ],
        ],
      ),
    );
  }
}

class _HeadlineStats extends StatelessWidget {
  final Map<String, dynamic> result;

  const _HeadlineStats({required this.result});

  @override
  Widget build(BuildContext context) {
    // Tolerant reads (docs/VERSIONING.md §3.3): a field an older or newer
    // server omits or reshapes costs one missing line, never the screen.
    final distanceM = readDouble(result, 'distance_meters');
    final elapsedS = readDouble(result, 'elapsed_seconds');
    final movingS = readDouble(result, 'moving_seconds');
    final avgSpeedMps = readDouble(result, 'avg_moving_speed_mps');
    final elevation = readMap(result, 'elevation');
    final gainM = readDouble(elevation, 'gain_m');
    final lossM = readDouble(elevation, 'loss_m');
    final bestEfforts = readMapList(result, 'best_efforts');
    final best1km = _bestEffortFor(bestEfforts, 1000);
    final best5km = _bestEffortFor(bestEfforts, 5000);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (distanceM != null) Text('Distance: ${formatDistanceKm(distanceM)} km'),
        if (elapsedS != null)
          Text('Time: ${formatDuration(Duration(seconds: elapsedS.round()))}'),
        if (movingS != null)
          Text('Moving time: ${formatDuration(Duration(seconds: movingS.round()))}'),
        if (avgSpeedMps != null) Text('Avg speed: ${formatKmh(avgSpeedMps)} km/h'),
        if (gainM != null) Text('Elevation gain: ${gainM.toStringAsFixed(0)} m'),
        if (lossM != null) Text('Elevation loss: ${lossM.toStringAsFixed(0)} m'),
        if (best1km != null) Text('Best 1 km: ${formatDuration(best1km)}'),
        if (best5km != null) Text('Best 5 km: ${formatDuration(best5km)}'),
      ],
    );
  }

  Duration? _bestEffortFor(
    List<Map<String, dynamic>> bestEfforts,
    double targetDistanceMeters,
  ) {
    for (final entry in bestEfforts) {
      final durationS = readDouble(entry, 'duration_seconds');
      if (readDouble(entry, 'distance_meters') == targetDistanceMeters && durationS != null) {
        return Duration(seconds: durationS.round());
      }
    }
    return null;
  }
}
