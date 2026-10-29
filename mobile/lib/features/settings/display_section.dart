import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/display/orientation_lock_settings.dart';

/// Settings → Display (issue #150): the "Lock to portrait" switch. Applies at
/// once, mid-run included (SimpleActivityTrackerApp listens to the provider).
class DisplaySection extends ConsumerWidget {
  const DisplaySection({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Display', style: Theme.of(context).textTheme.titleMedium),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('Lock to portrait'),
          subtitle: const Text(
            "Keep the app upright even when your phone's auto-rotate is on.",
          ),
          value: ref.watch(portraitLockProvider),
          onChanged: (value) => ref.read(portraitLockProvider.notifier).set(value),
        ),
      ],
    );
  }
}
