import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

class ArabaApiException implements Exception {
  final String message;

  const ArabaApiException(this.message);

  @override
  String toString() => message;
}

class ArabaApi {
  static const String _configuredBaseUrl = String.fromEnvironment(
    'ARABA_API_BASE_URL',
    defaultValue: 'https://araba-api-dev-908580697493.asia-northeast3.run.app',
  );

  String get baseUrl => _configuredBaseUrl.replaceAll(RegExp(r'/$'), '');

  Uri _uri(String path) {
    return Uri.parse('$baseUrl$path');
  }

  Map<String, String> _headers({
    String? apiKey,
  }) {
    final headers = <String, String>{
      'Content-Type': 'application/json',
    };

    final key = apiKey?.trim();

    if (key != null && key.isNotEmpty) {
      headers['X-OpenAI-API-Key'] = key;
    }

    return headers;
  }

  Future<Map<String, dynamic>> health() async {
    final response = await _request(
      () => http.get(_uri('/api/health/')),
      timeout: const Duration(seconds: 15),
    );

    return _decode(response);
  }

  Future<Map<String, dynamic>> openAiStatus(
    String apiKey,
  ) async {
    final response = await _request(
      () => http.get(
        _uri('/api/settings/openai/'),
        headers: _headers(apiKey: apiKey),
      ),
      timeout: const Duration(seconds: 20),
    );

    return _decode(response);
  }

  Future<Map<String, dynamic>> createMission(
    String request, {
    required String apiKey,
  }) async {
    final response = await _request(
      () => http.post(
        _uri('/api/missions/create/'),
        headers: _headers(apiKey: apiKey),
        body: jsonEncode({'request': request}),
      ),
      timeout: const Duration(seconds: 90),
      retries: 1,
    );

    return _decode(response);
  }

  Future<Map<String, dynamic>> registerNotificationToken(
    String token,
  ) async {
    final response = await _request(
      () => http.post(
        _uri('/api/notifications/register/'),
        headers: _headers(),
        body: jsonEncode({'token': token}),
      ),
      timeout: const Duration(seconds: 20),
      retries: 2,
    );

    return _decode(response);
  }

  Future<Map<String, dynamic>> voiceStatus() async {
    final response = await _request(
      () => http.get(
        _uri('/api/voice/status/'),
        headers: _headers(),
      ),
      timeout: const Duration(seconds: 20),
    );

    return _decode(response);
  }

  Future<Map<String, dynamic>> startVoiceTestCall(
    String phoneNumber, {
    required String apiKey,
  }) async {
    final response = await _request(
      () => http.post(
        _uri('/api/voice/test-call/'),
        headers: _headers(apiKey: apiKey),
        body: jsonEncode({
          'phone_number': phoneNumber,
        }),
      ),
      timeout: const Duration(seconds: 30),
    );

    return _decode(response);
  }

  Future<Map<String, dynamic>> testOpenAi(
    String apiKey,
  ) async {
    final response = await _request(
      () => http.post(
        _uri('/api/settings/openai/test/'),
        headers: _headers(apiKey: apiKey),
      ),
      timeout: const Duration(seconds: 45),
      retries: 1,
    );

    return _decode(response);
  }

  Future<http.Response> _request(
    Future<http.Response> Function() action, {
    required Duration timeout,
    int retries = 0,
  }) async {
    for (var attempt = 0; attempt <= retries; attempt++) {
      try {
        return await action().timeout(timeout);
      } on TimeoutException {
        if (attempt < retries) {
          await Future<void>.delayed(const Duration(milliseconds: 700));
          continue;
        }
        throw const ArabaApiException(
          '서버 응답이 늦어지고 있어요. 잠시 후 다시 시도해주세요.',
        );
      } on http.ClientException {
        if (attempt < retries) {
          await Future<void>.delayed(const Duration(milliseconds: 700));
          continue;
        }
        throw const ArabaApiException(
          '서버 연결이 잠시 끊겼어요. 네트워크를 확인한 뒤 다시 시도해주세요.',
        );
      }
    }

    throw const ArabaApiException('서버 요청에 실패했습니다.');
  }

  Map<String, dynamic> _decode(http.Response response) {
    Map<String, dynamic> data;

    try {
      data = jsonDecode(response.body) as Map<String, dynamic>;
    } catch (_) {
      throw ArabaApiException(
        '서버 응답을 읽을 수 없습니다. '
        'HTTP ${response.statusCode}',
      );
    }

    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ArabaApiException(
        data['message']?.toString() ??
            '요청에 실패했습니다. '
                'HTTP ${response.statusCode}',
      );
    }

    return data;
  }
}
