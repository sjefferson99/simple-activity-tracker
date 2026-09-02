import 'dart:io' show Platform;

import 'package:flutter/material.dart';

/// Plain-language, platform-specific steps for finding an exported run's
/// GPX file — reached from the run summary screen once a run finishes.
class ExportHelpScreen extends StatelessWidget {
  final String? exportedTo;

  const ExportHelpScreen({super.key, required this.exportedTo});

  @override
  Widget build(BuildContext context) {
    final steps = Platform.isIOS ? _iosSteps : _androidSteps(exportedTo);

    return Scaffold(
      appBar: AppBar(title: const Text('Finding your run file')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            Text(
              Platform.isIOS
                  ? 'Every run is saved as a GPX file — a standard format most mapping and running sites can open. On iPhone, it lives in the Files app.'
                  : 'Every run is saved as a GPX file — a standard format most mapping and running sites can open. On Android, a copy is placed in your Downloads folder so you can find it easily.',
              style: Theme.of(context).textTheme.bodyLarge,
            ),
            const SizedBox(height: 28),
            for (final (index, step) in steps.indexed) ...[
              _Step(number: index + 1, text: step),
              if (index != steps.length - 1) const SizedBox(height: 18),
            ],
          ],
        ),
      ),
    );
  }

  static const _iosSteps = [
    'Open the Files app (built in to every iPhone).',
    'Tap "On My iPhone" in the sidebar, then open the "Simple Runner" folder.',
    'Open the "runs" folder — each run is a file named with the date and time it started.',
    'Tap and hold a file to share it by AirDrop, Messages, email, or save it to a cloud drive.',
  ];

  static List<String> _androidSteps(String? exportedTo) => [
        if (exportedTo != null)
          'Open your Files or "My Files" app and go to $exportedTo.'
        else
          'Open your Files or "My Files" app and go to Downloads > SimpleRunner.',
        'Each run is a file named with the date and time it started.',
        'Tap a file to share it by email, Bluetooth, or a cloud drive — or plug your phone into a computer by USB and copy it from the same folder.',
      ];
}

class _Step extends StatelessWidget {
  final int number;
  final String text;

  const _Step({required this.number, required this.text});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        CircleAvatar(
          radius: 14,
          backgroundColor: theme.colorScheme.primaryContainer,
          child: Text(
            '$number',
            style: TextStyle(
              color: theme.colorScheme.onPrimaryContainer,
              fontWeight: FontWeight.w600,
              fontSize: 13,
            ),
          ),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Text(text, style: theme.textTheme.bodyMedium),
        ),
      ],
    );
  }
}
