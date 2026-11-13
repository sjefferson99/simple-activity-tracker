import 'dart:async';

import 'package:simple_activity_tracker/core/sensors/barometer_service.dart';

/// Silent until a test calls [emit] or [failNoSensor].
class FakeBarometerService implements BarometerService {
  final _controller = StreamController<double>.broadcast();

  @override
  Stream<double> get pressureHpa => _controller.stream;

  void emit(double hpa) => _controller.add(hpa);

  /// What the plugin does on a phone with no barometer.
  void failNoSensor() => _controller.addError(StateError('NO_SENSOR'));
}
