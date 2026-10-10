import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class GooglePlacesCredentialStore {
  static const String _apiKey = 'google_places_api_key';

  final FlutterSecureStorage _storage;

  GooglePlacesCredentialStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  Future<String?> read() async {
    final value = await _storage.read(key: _apiKey);
    final trimmed = value?.trim();
    if (trimmed == null || trimmed.isEmpty) {
      return null;
    }
    return trimmed;
  }

  Future<void> write(String apiKey) async {
    final key = apiKey.trim();
    if (key.isEmpty) {
      throw ArgumentError('Google Places API Key를 입력해주세요.');
    }
    await _storage.write(
      key: _apiKey,
      value: key,
    );
  }

  Future<void> delete() async {
    await _storage.delete(key: _apiKey);
  }
}
