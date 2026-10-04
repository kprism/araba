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

  Future<Map<String, dynamic>> health() async {
    final response = await http
        .get(_uri('/api/health/'))
        .timeout(const Duration(seconds: 15));

    return _decode(response);
  }

  Future<Map<String, dynamic>> openAiStatus() async {
    final response = await http
        .get(_uri('/api/settings/openai/'))
        .timeout(const Duration(seconds: 15));

    return _decode(response);
  }

  Future<Map<String, dynamic>> saveOpenAiKey(String apiKey) async {
    final response = await http
        .post(
          _uri('/api/settings/openai/save/'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'api_key': apiKey}),
        )
        .timeout(const Duration(seconds: 20));

    return _decode(response);
  }

  Future<Map<String, dynamic>> createMission(String request) async {
    final response = await http
        .post(
          _uri('/api/missions/create/'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode({'request': request}),
        )
        .timeout(const Duration(seconds: 60));

    return _decode(response);
  }

  Future<Map<String, dynamic>> testOpenAi() async {
    final response = await http
        .post(
          _uri('/api/settings/openai/test/'),
          headers: const {'Content-Type': 'application/json'},
        )
        .timeout(const Duration(seconds: 30));

    return _decode(response);
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
