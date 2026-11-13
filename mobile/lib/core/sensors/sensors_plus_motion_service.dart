import 'dart:math' as math;

import 'package:sensors_plus/sensors_plus.dart';

import 'motion_service.dart';

class SensorsPlusMotionService implements MotionService {
  // 50 Hz: comfortably above running cadence (~3 Hz) and its harmonics.
  @override
  Stream<double> get accelerationMagnitude =>
      accelerometerEventStream(samplingPeriod: const Duration(milliseconds: 20))
          .map((e) => math.sqrt(e.x * e.x + e.y * e.y + e.z * e.z));
}
