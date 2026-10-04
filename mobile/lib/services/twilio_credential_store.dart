import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class TwilioCredentialStore {
  static const String _sidKey = 'twilio_account_sid';
  static const String _tokenKey = 'twilio_auth_token';

  final FlutterSecureStorage _storage;

  TwilioCredentialStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  Future<({String accountSid, String authToken})?> read() async {
    final sid = (await _storage.read(key: _sidKey))?.trim();
    final token = (await _storage.read(key: _tokenKey))?.trim();

    if (sid == null || sid.isEmpty || token == null || token.isEmpty) {
      return null;
    }

    return (accountSid: sid, authToken: token);
  }

  Future<void> write({
    required String accountSid,
    required String authToken,
  }) async {
    final sid = accountSid.trim();
    final token = authToken.trim();

    if (sid.isEmpty || token.isEmpty) {
      throw ArgumentError('Twilio Account SID와 Auth Token을 모두 입력해주세요.');
    }

    await _storage.write(key: _sidKey, value: sid);
    await _storage.write(key: _tokenKey, value: token);
  }

  Future<void> delete() async {
    await _storage.delete(key: _sidKey);
    await _storage.delete(key: _tokenKey);
  }
}
