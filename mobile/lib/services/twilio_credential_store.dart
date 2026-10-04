import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class TwilioCredentialStore {
  static const String _sidKey = 'twilio_account_sid';
  static const String _tokenKey = 'twilio_auth_token';
  static const String _fromNumberKey = 'twilio_from_number';

  final FlutterSecureStorage _storage;

  TwilioCredentialStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  Future<({
    String accountSid,
    String authToken,
    String? fromNumber,
  })?> read() async {
    final sid = (await _storage.read(key: _sidKey))?.trim();
    final token = (await _storage.read(key: _tokenKey))?.trim();
    final fromNumber = (
      await _storage.read(key: _fromNumberKey)
    )?.trim();

    if (sid == null || sid.isEmpty || token == null || token.isEmpty) {
      return null;
    }

    return (
      accountSid: sid,
      authToken: token,
      fromNumber: fromNumber == null || fromNumber.isEmpty
          ? null
          : fromNumber,
    );
  }

  Future<void> write({
    required String accountSid,
    required String authToken,
    String? fromNumber,
  }) async {
    final sid = accountSid.trim();
    final token = authToken.trim();
    final from = fromNumber?.trim();

    if (sid.isEmpty || token.isEmpty) {
      throw ArgumentError('Twilio Account SID와 Auth Token을 모두 입력해주세요.');
    }

    await _storage.write(key: _sidKey, value: sid);
    await _storage.write(key: _tokenKey, value: token);

    if (from == null || from.isEmpty) {
      await _storage.delete(key: _fromNumberKey);
    } else {
      await _storage.write(
        key: _fromNumberKey,
        value: from,
      );
    }
  }

  Future<void> delete() async {
    await _storage.delete(key: _sidKey);
    await _storage.delete(key: _tokenKey);
    await _storage.delete(key: _fromNumberKey);
  }
}
