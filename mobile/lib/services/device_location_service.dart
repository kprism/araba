import 'package:geolocator/geolocator.dart';

class DeviceLocationService {
  const DeviceLocationService();

  static Position? _recentPosition;

  static bool _freshEnough(Position? position) {
    if (position == null || position.accuracy > 100) return false;
    final age = DateTime.now().difference(position.timestamp);
    return !age.isNegative && age < const Duration(seconds: 60);
  }

  static Map<String, dynamic> _asContext(Position position) {
    return {
      'latitude': position.latitude,
      'longitude': position.longitude,
      'accuracy_m': position.accuracy,
      'captured_at': position.timestamp.toUtc().toIso8601String(),
      'source': 'device',
    };
  }

  Future<Map<String, dynamic>?> currentContext() async {
    final enabled = await Geolocator.isLocationServiceEnabled();
    if (!enabled) return null;

    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.denied ||
        permission == LocationPermission.deniedForever) {
      return null;
    }

    if (_freshEnough(_recentPosition)) {
      return _asContext(_recentPosition!);
    }
    try {
      final lastKnown = await Geolocator.getLastKnownPosition();
      if (_freshEnough(lastKnown)) {
        _recentPosition = lastKnown;
        return _asContext(lastKnown!);
      }
    } catch (_) {
      // Last-known position is optional, not permission to invent a location.
    }

    try {
      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          timeLimit: Duration(seconds: 5),
        ),
      );
      _recentPosition = position;
      return _asContext(position);
    } catch (_) {
      // Fail explicitly instead of navigating from a potentially stale GPS fix.
      return null;
    }
  }
}
