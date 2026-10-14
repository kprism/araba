import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

import 'araba_api.dart';

/// Authentication is server enforced. A local role-preview toggle is never sent
/// as an authorization credential.
class MerchantAccountApi {
  MerchantAccountApi({
    http.Client? client,
    FlutterSecureStorage? secureStorage,
    String? baseUrl,
  })  : _client = client ?? http.Client(),
        _storage = secureStorage ?? const FlutterSecureStorage(),
        _baseUrl = baseUrl ?? ArabaApi().baseUrl;

  final http.Client _client;
  final FlutterSecureStorage _storage;
  final String _baseUrl;
  static const _key = 'araba_merchant_account_token_v1';

  Uri _url(String path, [Map<String, String>? query]) =>
      Uri.parse('$_baseUrl$path').replace(queryParameters: query);

  Future<String?> token() => _storage.read(key: _key);

  Future<void> _saveToken(String value) =>
      _storage.write(key: _key, value: value);

  Future<Map<String, String>> _headers({bool authenticated = false}) async {
    final token = authenticated ? await this.token() : null;
    return {
      'Content-Type': 'application/json',
      if (token != null && token.isNotEmpty) 'Authorization': 'Token $token',
    };
  }

  Map<String, dynamic> _decode(http.Response response) {
    Map<String, dynamic> data;
    try {
      final raw = jsonDecode(response.body);
      data = raw is Map ? Map<String, dynamic>.from(raw) : {};
    } catch (_) {
      throw const ArabaApiException('서버 응답을 읽지 못했습니다.');
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ArabaApiException(
        data['message']?.toString() ?? '요청에 실패했습니다.',
        statusCode: response.statusCode,
      );
    }
    return data;
  }

  Future<Map<String, dynamic>> usernameAvailable(String username) async {
    final response = await _client.get(
      _url('/api/accounts/username-available/', {'username': username}),
    ).timeout(const Duration(seconds: 15));
    return _decode(response);
  }

  Future<Map<String, dynamic>> signup({
    required String username,
    required String password,
    required String confirm,
  }) async {
    final response = await _client.post(
      _url('/api/accounts/signup/'),
      headers: await _headers(),
      body: jsonEncode({
        'username': username,
        'password': password,
        'password_confirm': confirm,
        'terms_consent': true,
        'privacy_consent': true,
      }),
    ).timeout(const Duration(seconds: 15));
    final result = _decode(response);
    final token = result['token']?.toString() ?? '';
    if (token.isEmpty) throw const ArabaApiException('로그인 토큰을 받지 못했습니다.');
    await _saveToken(token);
    return result;
  }

  Future<Map<String, dynamic>> login({
    required String username,
    required String password,
  }) async {
    final response = await _client.post(
      _url('/api/accounts/login/'),
      headers: await _headers(),
      body: jsonEncode({'username': username, 'password': password}),
    ).timeout(const Duration(seconds: 15));
    final result = _decode(response);
    final token = result['token']?.toString() ?? '';
    if (token.isEmpty) throw const ArabaApiException('로그인 토큰을 받지 못했습니다.');
    await _saveToken(token);
    return result;
  }

  Future<Map<String, dynamic>> me() async {
    final response = await _client.get(
      _url('/api/accounts/me/'), headers: await _headers(authenticated: true),
    ).timeout(const Duration(seconds: 15));
    return _decode(response);
  }

  Future<Map<String, dynamic>> searchExistingBusinesses(String query) async {
    final response = await _client.get(
      _url('/api/merchant/businesses/search/', {'q': query}),
    ).timeout(const Duration(seconds: 15));
    return _decode(response);
  }

  Future<Map<String, dynamic>> claim({
    required int businessId,
    required String ownerName,
    required String registrationNumber,
    String phone = '',
  }) async {
    final response = await _client.post(
      _url('/api/merchant/claims/'),
      headers: await _headers(authenticated: true),
      body: jsonEncode({
        'business_id': businessId,
        'owner_name': ownerName,
        'registration_number': registrationNumber,
        'contact_phone': phone,
      }),
    ).timeout(const Duration(seconds: 15));
    return _decode(response);
  }

  Future<Map<String, dynamic>> saveDraft({
    required int claimId,
    required Map<String, String> basic,
    required String extraInformation,
    required String agentInstructions,
  }) async {
    final response = await _client.patch(
      _url('/api/merchant/claims/$claimId/'),
      headers: await _headers(authenticated: true),
      body: jsonEncode({
        'proposed_info': basic,
        'extra_information': extraInformation,
        'agent_instructions': agentInstructions,
      }),
    ).timeout(const Duration(seconds: 15));
    return _decode(response);
  }

  Future<void> logout() async {
    try {
      await _client.post(
        _url('/api/accounts/logout/'),
        headers: await _headers(authenticated: true),
      ).timeout(const Duration(seconds: 8));
    } finally {
      await _storage.delete(key: _key);
    }
  }
}
