import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class KakaoCredentialStore {
  static const String _restApiKey = 'kakao_rest_api_key';

  final FlutterSecureStorage _storage;

  KakaoCredentialStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  Future<String?> read() async {
    final value = await _storage.read(key: _restApiKey);
    final trimmed = value?.trim();

    if (trimmed == null || trimmed.isEmpty) {
      return null;
    }

    return trimmed;
  }

  Future<void> write(String apiKey) async {
    final key = apiKey.trim();

    if (key.isEmpty) {
      throw ArgumentError('Kakao REST API Key를 입력해주세요.');
    }

    await _storage.write(
      key: _restApiKey,
      value: key,
    );
  }

  Future<void> delete() async {
    await _storage.delete(key: _restApiKey);
  }
}
