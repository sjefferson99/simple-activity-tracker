import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/sync/sync_service.dart';
import '../features/live_run/live_run_screen.dart';

class SimpleActivityTrackerApp extends ConsumerStatefulWidget {
  const SimpleActivityTrackerApp({super.key});

  @override
  ConsumerState<SimpleActivityTrackerApp> createState() =>
      _SimpleActivityTrackerAppState();
}

class _SimpleActivityTrackerAppState
    extends ConsumerState<SimpleActivityTrackerApp>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // A queued run may have finished uploading only partway (or not at all)
    // while the app was backgrounded — resume is one of SyncService's retry
    // triggers alongside connectivity regained and "Retry now" (§6.3).
    if (state == AppLifecycleState.resumed) {
      ref.read(syncServiceProvider).onAppResumed();
    }
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Simple Activity Tracker',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.teal),
      ),
      home: const LiveRunScreen(),
    );
  }
}
