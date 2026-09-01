import 'dart:math';

import 'models/track_point.dart';

const double _earthRadiusMeters = 6371000;

/// Great-circle distance between two points, in meters.
double haversineDistanceMeters(TrackPoint a, TrackPoint b) {
  final lat1 = a.latitude * pi / 180;
  final lat2 = b.latitude * pi / 180;
  final dLat = (b.latitude - a.latitude) * pi / 180;
  final dLon = (b.longitude - a.longitude) * pi / 180;

  final h = sin(dLat / 2) * sin(dLat / 2) +
      cos(lat1) * cos(lat2) * sin(dLon / 2) * sin(dLon / 2);
  final c = 2 * atan2(sqrt(h), sqrt(1 - h));
  return _earthRadiusMeters * c;
}

/// Speed in meters/second implied by two consecutive points.
/// Returns null when the points share a timestamp (avoids division by zero).
double? speedMpsBetween(TrackPoint a, TrackPoint b) {
  final dtSeconds = b.timestamp.difference(a.timestamp).inMilliseconds / 1000;
  if (dtSeconds <= 0) return null;
  return haversineDistanceMeters(a, b) / dtSeconds;
}
