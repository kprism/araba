import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

class ArabaApiException implements Exception {
  final String message;

  final int? statusCode;
  final String? stage;
  final String? exceptionType;
  final Map<String, dynamic> diagnostics;

  const ArabaApiException(
    this.message, {
    this.statusCode,
    this.stage,
    this.exceptionType,
    this.diagnostics = const {},
  });

  String get diagnosticText => [
    message,
    'HTTP: ${statusCode ?? "응답 없음"}',
    '단계: ${stage ?? "server_response"}',
    '예외: ${exceptionType ?? "미제공"}',
    for (final key in [
      'request_id', 'model', 'server_elapsed_ms', 'openai_elapsed_ms',
      'timeout_seconds', 'retries', 'upstream_http_status',
      'upstream_request_id',
    ])
      if (diagnostics[key] != null) '$key: ${diagnostics[key]}',
  ].join('\n');

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
    String? kakaoRestApiKey,
    String? naverClientId,
    String? naverClientSecret,
    String? twilioAccountSid,
    String? twilioAuthToken,
    String? twilioFromNumber,
    String? twilioCallerIdNumber,
  }) {
    final headers = <String, String>{
      'Content-Type': 'application/json',
    };

    final key = apiKey?.trim();

    if (key != null && key.isNotEmpty) {
      headers['X-OpenAI-API-Key'] = key;
    }

    final kakaoKey = kakaoRestApiKey?.trim();

    if (kakaoKey != null && kakaoKey.isNotEmpty) {
      headers['X-Kakao-REST-API-Key'] = kakaoKey;
    }

    final naverId = naverClientId?.trim();
    final naverSecret = naverClientSecret?.trim();

    if (naverId != null && naverId.isNotEmpty) {
      headers['X-Naver-Client-Id'] = naverId;
    }

    if (naverSecret != null && naverSecret.isNotEmpty) {
      headers['X-Naver-Client-Secret'] = naverSecret;
    }

    final sid = twilioAccountSid?.trim();
    final token = twilioAuthToken?.trim();

    if (sid != null && sid.isNotEmpty) {
      headers['X-Twilio-Account-SID'] = sid;
    }

    if (token != null && token.isNotEmpty) {
      headers['X-Twilio-Auth-Token'] = token;
    }

    final fromNumber = twilioFromNumber?.trim();

    if (fromNumber != null && fromNumber.isNotEmpty) {
      headers['X-Twilio-From-Number'] = fromNumber;
    }

    final callerIdNumber = twilioCallerIdNumber?.trim();

    if (callerIdNumber != null && callerIdNumber.isNotEmpty) {
      headers['X-Twilio-Caller-ID'] = callerIdNumber;
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
      timeout: const Duration(seconds: 15),
      retries: 0,
      retryServerErrors: false,
    );

    return _decode(response);
  }

  Future<Map<String, dynamic>> searchBusinesses(
    Map<String, dynamic> mission, {
    required String kakaoRestApiKey,
    required String openAiApiKey,
    String? naverClientId,
    String? naverClientSecret,
    bool quickCards = false,
  }) async {
    final response = await _request(
      () => http.post(
        _uri('/api/research/search/'),
        headers: _headers(
          apiKey: openAiApiKey,
          kakaoRestApiKey: kakaoRestApiKey,
          naverClientId: naverClientId,
          naverClientSecret: naverClientSecret,
        ),
        body: jsonEncode({
          'mission': mission,
          'quick_cards': quickCards,
        }),
      ),
      timeout: const Duration(seconds: 45),
      retries: 0,
      retryServerErrors: false,
    );

    return _decode(response);
  }

  Future<Map<String, dynamic>> enrichBusinesses(
    Map<String, dynamic> mission,
    List<Map<String, dynamic>> businesses, {
    required String openAiApiKey,
    String? naverClientId,
    String? naverClientSecret,
  }) async {
    final response = await _request(
      () => http.post(
        _uri('/api/research/enrich/'),
        headers: _headers(
          apiKey: openAiApiKey,
          naverClientId: naverClientId,
          naverClientSecret: naverClientSecret,
        ),
        body: jsonEncode({
          'mission': mission,
          'businesses': businesses,
        }),
      ),
      timeout: const Duration(seconds: 55),
      retries: 0,
      retryServerErrors: false,
    );
    return _decode(response);
  }

  Future<Map<String, dynamic>> simulateMockCalls(
    Map<String, dynamic> mission,
    List<Map<String, dynamic>> businesses, {
    Map<String, dynamic>? origin,
  }) async {
    final response = await _request(
      () => http.post(
        _uri('/api/research/mock-call/'),
        headers: _headers(),
        body: jsonEncode({
          'mission': mission,
          'businesses': businesses,
          'origin': ?origin,
        }),
      ),
      timeout: const Duration(seconds: 10),
    );

    return _decode(response);
  }

  Future<Map<String, dynamic>> researchHistory({
    int limit = 50,
  }) async {
    final safeLimit = limit.clamp(1, 100);
    final response = await _request(
      () => http.get(
        _uri('/api/research/history/?limit=$safeLimit'),
        headers: _headers(),
      ),
      timeout: const Duration(seconds: 10),
    );

    return _decode(response);
  }

  Future<Map<String, dynamic>> trainingStatus() async {
    final response = await _request(
      () => http.get(
        _uri('/api/training/status/'),
        headers: _headers(),
      ),
      timeout: const Duration(seconds: 15),
    );

    return _decode(response);
  }

  Future<Map<String, dynamic>> generateTrainingScenarios({
    String? category,
    int limit = 10,
  }) async {
    final response = await _request(
      () => http.post(
        _uri('/api/training/generate/'),
        headers: _headers(),
        body: jsonEncode({
          'category': category,
          'limit': limit,
        }),
      ),
      timeout: const Duration(seconds: 20),
    );

    return _decode(response);
  }

  Future<Map<String, dynamic>> runAutoTraining({
    required String apiKey,
    String? category,
    int limit = 4,
  }) async {
    final response = await _request(
      () => http.post(
        _uri('/api/training/run-auto/'),
        headers: _headers(apiKey: apiKey),
        body: jsonEncode({
          'category': category,
          'limit': limit,
        }),
      ),
      timeout: const Duration(seconds: 90),
    );

    return _decode(response);
  }

  Future<Map<String, dynamic>> saveTrainingFeedback({
    required String category,
    required String trigger,
    required String instruction,
    String example = '',
  }) async {
    final response = await _request(
      () => http.post(
        _uri('/api/training/feedback/'),
        headers: _headers(),
        body: jsonEncode({
          'category': category,
          'trigger': trigger,
          'instruction': instruction,
          'example': example,
        }),
      ),
      timeout: const Duration(seconds: 20),
    );

    return _decode(response);
  }

  Future<Map<String, dynamic>> analyzeResearchImage({
    required List<int> bytes,
    required String filename,
    required String mimeType,
    required String context,
    required String apiKey,
  }) async {
    final request = http.MultipartRequest(
      'POST',
      _uri('/api/images/analyze/'),
    );

    request.headers['X-OpenAI-API-Key'] = apiKey;
    request.fields['context'] = context;
    request.fields['mime_type'] = mimeType;
    request.files.add(
      http.MultipartFile.fromBytes(
        'image',
        bytes,
        filename: filename,
      ),
    );

    try {
      final streamed = await request
          .send()
          .timeout(
            const Duration(seconds: 50),
          );
      final response =
          await http.Response.fromStream(streamed);

      return _decode(response);
    } on TimeoutException {
      throw const ArabaApiException(
        '사진 판독이 늦어지고 있어요. 잠시 후 다시 시도해주세요.',
      );
    } on http.ClientException {
      throw const ArabaApiException(
        '사진 전송 중 네트워크 연결이 끊겼어요.',
      );
    }
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

  Future<Map<String, dynamic>> createLiveSession(
    String offerSdp, {
    required String apiKey,
    String voiceGender = 'female',
    String voiceSpeed = 'medium',
  }) async {
    final response = await _request(
      () => http.post(
        _uri('/api/live/session/'),
        headers: _headers(apiKey: apiKey),
        body: jsonEncode({
          'sdp': offerSdp,
          'voice_gender': voiceGender,
          'voice_speed': voiceSpeed,
        }),
      ),
      timeout: const Duration(seconds: 45),
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
    required String twilioAccountSid,
    required String twilioAuthToken,
    String? twilioFromNumber,
    String? twilioCallerIdNumber,
    String voiceGender = 'female',
    String voiceSpeed = 'medium',
    bool trainingMode = false,
    String trainingCategory = '',
  }) async {
    final response = await _request(
      () => http.post(
        _uri('/api/voice/test-call/'),
        headers: _headers(
          apiKey: apiKey,
          twilioAccountSid: twilioAccountSid,
          twilioAuthToken: twilioAuthToken,
          twilioFromNumber: twilioFromNumber,
          twilioCallerIdNumber: twilioCallerIdNumber,
        ),
        body: jsonEncode({
          'phone_number': phoneNumber,
          'voice_gender': voiceGender,
          'voice_speed': voiceSpeed,
          'training_mode': trainingMode,
          'training_category': trainingCategory,
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
    bool retryServerErrors = false,
  }) async {
    for (var attempt = 0; attempt <= retries; attempt++) {
      try {
        final response = await action().timeout(timeout);

        if (retryServerErrors &&
            response.statusCode >= 500 &&
            attempt < retries) {
          await Future<void>.delayed(
            Duration(milliseconds: 700 * (attempt + 1)),
          );
          continue;
        }

        return response;
      } on TimeoutException {
        if (attempt < retries) {
          await Future<void>.delayed(
            Duration(milliseconds: 700 * (attempt + 1)),
          );
          continue;
        }
        throw const ArabaApiException(
          '서버 응답이 늦어지고 있어요. 잠시 후 다시 시도해주세요.',
          stage: 'app_wait_timeout',
          exceptionType: 'TimeoutException',
        );
      } on http.ClientException {
        if (attempt < retries) {
          await Future<void>.delayed(
            Duration(milliseconds: 700 * (attempt + 1)),
          );
          continue;
        }
        throw const ArabaApiException(
          '서버 연결이 잠시 끊겼어요. 네트워크를 확인한 뒤 다시 시도해주세요.',
          stage: 'app_transport',
          exceptionType: 'ClientException',
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
        statusCode: response.statusCode,
        stage: 'decode_response',
        exceptionType: 'InvalidResponse',
      );
    }

    if (response.statusCode < 200 || response.statusCode >= 300) {
      final rawDiagnostics = data['diagnostics'];
      final diagnostics = rawDiagnostics is Map
          ? Map<String, dynamic>.from(rawDiagnostics)
          : <String, dynamic>{};
      throw ArabaApiException(
        data['message']?.toString() ??
            '요청에 실패했습니다. '
                'HTTP ${response.statusCode}',
        statusCode: response.statusCode,
        stage: diagnostics['stage']?.toString(),
        exceptionType: diagnostics['exception_type']?.toString(),
        diagnostics: diagnostics,
      );
    }

    return data;
  }
}
