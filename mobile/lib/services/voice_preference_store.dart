import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class VoicePreferences {
  final String gender;
  final String speed;

  const VoicePreferences({
    required this.gender,
    required this.speed,
  });
}

class VoicePreferenceStore {
  static const _genderKey =
      'araba.voice.gender';
  static const _speedKey =
      'araba.voice.speed';

  final FlutterSecureStorage _storage =
      const FlutterSecureStorage();

  Future<VoicePreferences> read() async {
    final gender =
        await _storage.read(
          key: _genderKey,
        ) ??
        'female';
    final speed =
        await _storage.read(
          key: _speedKey,
        ) ??
        'medium';

    return VoicePreferences(
      gender: gender,
      speed: speed,
    );
  }

  Future<void> write({
    required String gender,
    required String speed,
  }) async {
    await _storage.write(
      key: _genderKey,
      value: gender,
    );
    await _storage.write(
      key: _speedKey,
      value: speed,
    );
  }
}
