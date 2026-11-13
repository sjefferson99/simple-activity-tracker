import 'package:sensors_plus/sensors_plus.dart';

import 'barometer_service.dart';

class SensorsPlusBarometerService implements BarometerService {
  // ~25 Hz, averaged per fix by PressureWindow. Android delivers at this
  // rate or the sensor's maximum; iOS ignores it (CMAltimeter picks its own).
  @override
  Stream<double> get pressureHpa =>
      barometerEventStream(samplingPeriod: const Duration(milliseconds: 40))
          .map((event) => event.pressure);
}
