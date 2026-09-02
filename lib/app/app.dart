import 'package:flutter/material.dart';

import '../features/live_run/live_run_screen.dart';

class SimpleRunnerApp extends StatelessWidget {
  const SimpleRunnerApp({super.key});

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
