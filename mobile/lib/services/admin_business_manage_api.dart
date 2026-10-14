import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

import 'araba_api.dart';

/// Admin-only moderation. The backend independently checks is_staff.
/// The administrator role-preview tab is not an authorization credential.
class AdminBusinessManageApi {
  AdminBusinessManageApi({
    http.Client? client,
    FlutterSecureStorage? secureStorage,
    String? baseUrl,
  })  : _client = client ?? http.Client(),
        _storage = secureStorage ?? const FlutterSecureStorage(),
        _baseUrl = baseUrl ?? ArabaApi().baseUrl;

  final http.Client _client;
  final FlutterSecureStorage _storage;
  final String _baseUrl;
  static const _key = 'araba_admin_business_token_v1';

  Uri _uri(String path) => Uri.parse('$_baseUrl$path');

  Map<String, dynamic> _decode(http.Response response) {
    Map<String, dynamic> result;
    try {
      final parsed = jsonDecode(response.body);
      result = parsed is Map ? Map<String, dynamic>.from(parsed) : {};
    } catch (_) {
      throw const ArabaApiException('서버 응답을 해석할 수 없습니다.');
    }
    if (response.statusCode >= 400) {
      throw ArabaApiException(
        result['message']?.toString() ?? (
          response.statusCode == 403
              ? '관리자 인증이 필요합니다.'
              : '업체 변경 요청에 실패했습니다.'),
        statusCode: response.statusCode,
      );
    }
    return result;
  }

  Future<String?> _token() => _storage.read(key: _key);

  Future<bool> isStaffAuthenticated() async {
    final key = await _token();
    if (key == null || key.isEmpty) return false;
    try {
      final response = await _client.get(
        _uri('/api/accounts/me/'),
        headers: {'Authorization': 'Token $key'},
      ).timeout(const Duration(seconds: 12));
      final result = _decode(response);
      final raw = result['user'];
      return raw is Map && raw['is_staff'] == true;
    } catch (_) {
      // Don't silently authorize a user when the server is unreachable.
      return false;
    }
  }

  Future<void> adminLogin(String username, String password) async {
    final response = await _client.post(
      _uri('/api/accounts/login/'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'username': username, 'password': password}),
    ).timeout(const Duration(seconds: 15));
    final login = _decode(response);
    final token = login['token']?.toString() ?? '';
    final user = login['user'];
    if (token.isEmpty || user is! Map || user['is_staff'] != true) {
      throw const ArabaApiException('관리자 권한이 없는 계정입니다.');
    }
    final meResponse = await _client.get(
      _uri('/api/accounts/me/'),
      headers: {'Authorization': 'Token $token'},
    ).timeout(const Duration(seconds: 15));
    final me = _decode(meResponse);
    final meUser = me['user'];
    if (meUser is! Map || meUser['is_staff'] != true) {
      throw const ArabaApiException('서버에서 관리자 권한을 확인하지 못했습니다.');
    }
    await _storage.write(key: _key, value: token);
  }

  Future<Map<String, dynamic>> updateSelected({
    required List<int> businessIds,
    required bool active,
  }) async {
    if (businessIds.isEmpty || businessIds.length > 100 ||
        businessIds.toSet().length != businessIds.length) {
      throw const ArabaApiException('1~100곳을 선택해주세요.');
    }
    final token = await _token();
    if (token == null || token.isEmpty) {
      throw const ArabaApiException('관리자 로그인 후 이용해주세요.');
    }
    final response = await _client.post(
      _uri('/api/admin/businesses/visibility/'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Token $token',
      },
      body: jsonEncode({
        'ids': businessIds,
        'active': active,
        'confirmation': 'SELECTED_ONLY',
      }),
    ).timeout(const Duration(seconds: 20));
    return _decode(response);
  }
}
