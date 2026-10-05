import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class NaverCredentialStore {
  static const String _clientIdKey = 'naver_client_id';
  static const String _clientSecretKey = 'naver_client_secret';

  final FlutterSecureStorage _storage;

  NaverCredentialStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  Future<({
    String clientId,
    String clientSecret,
  })?> read() async {
    final clientId = (
      await _storage.read(key: _clientIdKey)
    )?.trim();
    final clientSecret = (
      await _storage.read(key: _clientSecretKey)
    )?.trim();

    if (clientId == null ||
        clientId.isEmpty ||
        clientSecret == null ||
        clientSecret.isEmpty) {
      return null;
    }

    return (
      clientId: clientId,
      clientSecret: clientSecret,
    );
  }

  Future<void> write({
    required String clientId,
    required String clientSecret,
  }) async {
    final id = clientId.trim();
    final secret = clientSecret.trim();

    if (id.isEmpty || secret.isEmpty) {
      throw ArgumentError(
        'Naver Client ID와 Client Secret을 모두 입력해주세요.',
      );
    }

    await _storage.write(
      key: _clientIdKey,
      value: id,
    );
    await _storage.write(
      key: _clientSecretKey,
      value: secret,
    );
  }

  Future<void> delete() async {
    await _storage.delete(key: _clientIdKey);
    await _storage.delete(key: _clientSecretKey);
  }
}
