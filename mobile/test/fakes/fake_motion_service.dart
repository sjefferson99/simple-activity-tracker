import 'dart:async';

import 'package:simple_activity_tracker/core/sensors/motion_service.dart';

/// Silent until a test calls [emit].
class FakeMotionService implements MotionService {
  final _controller = StreamController<double>.broadcast();

  @override
  Stream<double> get accelerationMagnitude => _controller.stream;

  void emit(double magnitude) => _controller.add(magnitude);
}
