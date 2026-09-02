import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/sync/sync_service.dart';
import '../features/live_run/live_run_screen.dart';

class SimpleRunnerApp extends ConsumerStatefulWidget {
  const SimpleRunnerApp({super.key});

  @override
  ConsumerState<SimpleRunnerApp> createState() => _SimpleRunnerAppState();
}

class _SimpleRunnerAppState extends ConsumerState<SimpleRunnerApp> with WidgetsBindingObserver {
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
      title: 'Simple Runner',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.deepOrange,
          brightness: Brightness.dark,
        ),
      ),
      home: const LiveRunScreen(),
    );
  }
}
