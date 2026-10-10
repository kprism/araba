import 'dart:async';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../services/api_key_store.dart';
import '../../services/araba_api.dart';
import '../../services/conversation_context.dart';
import '../../services/device_location_service.dart';
import '../../services/google_places_credential_store.dart';
import '../../services/kakao_credential_store.dart';
import '../../services/live_voice_service.dart';
import '../../services/naver_credential_store.dart';
import '../../services/voice_preference_store.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen>
    with WidgetsBindingObserver {
  final _controller = TextEditingController();
  final _scroll = ScrollController();
  final _focus = FocusNode();
  final _api = ArabaApi();
  final _imagePicker = ImagePicker();
  final _keyStore = ApiKeyStore();
  final _kakaoStore = KakaoCredentialStore();
  final _googlePlacesStore = GooglePlacesCredentialStore();
  final _deviceLocation = const DeviceLocationService();
  final _naverStore = NaverCredentialStore();
  final _voicePreferenceStore = VoicePreferenceStore();
  final _conversationContext = ConversationContext();

  LiveVoiceService? _liveVoice;
  bool _keepLiveVoice = false;
  bool _liveNeedsReconnect = false;
  bool _appInForeground = true;
  bool _autoReconnectingLive = false;
  List<Map<String, dynamic>> _lastBusinesses = const [];
  final List<Map<String, dynamic>> _recentBusinessGroups = [];

  final List<_Message> _messages = [
    _Message(
      isUser: false,
      text: '무엇을 알아볼까요? 말하듯이 편하게 적어주세요.',
    ),
  ];

  bool _liveConnecting = false;
  bool _liveActive = false;
  bool _micEnabled = false;
  bool _sending = false;
  bool _researching = false;
  bool _trainerMode = false;
  bool _trainerSubmitting = false;
  _Message? _trainerFeedbackTarget;
  int _researchRevision = 0;
  bool _userBrowsingHistory = false;
  String _liveStatus = '';
  String _researchStage = '';
  String? _liveTranscriptSpeaker;
  int? _liveTranscriptMessageIndex;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeAppLifecycleState(
    AppLifecycleState state,
  ) {
    _appInForeground =
        state == AppLifecycleState.resumed;

    if (!_appInForeground ||
        !_keepLiveVoice) {
      return;
    }

    final live = _liveVoice;

    if (live != null &&
        live.isStarted &&
        !_liveNeedsReconnect) {
      if (_micEnabled) {
        unawaited(live.resumeAudio());
      } else {
        unawaited(live.pauseAudio());
      }
      return;
    }

    unawaited(_reconnectLiveVoice());
  }

  Future<void> _reconnectLiveVoice() async {
    if (_autoReconnectingLive ||
        !_appInForeground ||
        !_keepLiveVoice) {
      return;
    }

    _autoReconnectingLive = true;
    _liveNeedsReconnect = false;

    final existing = _liveVoice;
    _liveVoice = null;

    try {
      await existing?.stop(force: true);
    } catch (_) {}

    if (!mounted || !_keepLiveVoice) {
      _autoReconnectingLive = false;
      return;
    }

    try {
      await _startLiveVoice(
        automatic: true,
      );
    } finally {
      _autoReconnectingLive = false;
    }
  }

  Future<void> _toggleLiveVoice() async {
    final current = _liveVoice;

    if (current != null && current.isStarted) {
      if (_micEnabled) {
        await current.pauseAudio();
        if (!mounted) return;
        setState(() {
          _micEnabled = false;
          _liveStatus =
              '마이크 꺼짐 · ARABA 연결 유지';
        });
      } else {
        await current.resumeAudio();
        if (!mounted) return;
        setState(() {
          _micEnabled = true;
          _liveStatus = '듣고 있어요';
        });
      }
      return;
    }

    if (_liveConnecting) return;

    if (current != null) {
      try {
        await current.stop(force: true);
      } catch (_) {}
      _liveVoice = null;
    }

    _keepLiveVoice = true;
    _micEnabled = true;
    await _startLiveVoice();
  }

  Future<void> _startLiveVoice({
    bool automatic = false,
  }) async {
    if (_liveConnecting) return;

    try {
      final apiKey = await _keyStore.read();

      if (apiKey == null) {
        throw const ArabaApiException(
          'MY에서 OpenAI API Key를 먼저 저장해주세요.',
        );
      }

      final voicePreferences =
          await _voicePreferenceStore.read();

      if (!mounted) return;

      setState(() {
        _liveConnecting = true;
        _liveActive = false;
        _liveStatus = automatic
            ? '음성 자동 재연결 중'
            : 'GPT-Live 연결 중';
      });

      late final LiveVoiceService liveVoice;
      liveVoice = LiveVoiceService(
        api: _api,
        apiKey: apiKey,
        conversationContext: _conversationContext,
        voiceGender: voicePreferences.gender,
        voiceSpeed: voicePreferences.speed,
        onStatus: (status) {
          if (!mounted || _liveVoice != liveVoice) return;

          setState(() {
            _liveActive = liveVoice.isStarted;
            _liveStatus = (
              _liveActive && !_micEnabled
            )
                ? '마이크 꺼짐 · ARABA 연결 유지'
                : status;
            if (_liveActive) {
              _liveConnecting = false;
            }
          });
        },
        onTranscript: ({
          required isUser,
          required delta,
        }) {
          if (!mounted || _liveVoice != liveVoice) return;

          setState(() {
            _appendLiveTranscript(
              isUser: isUser,
              delta: delta,
            );
          });
          _toBottom();
        },
        onUserUtterance: (text) async {
          if (!mounted || _liveVoice != liveVoice) return false;

          final target = _trainerFeedbackTarget;
          if (!_trainerMode || target == null) {
            if (!_trainerMode &&
                _looksLikeUserCorrection(text)) {
              final previous = _latestTrainableAssistant();
              if (previous != null) {
                _recordUserFeedbackCandidate(
                  previous,
                  text,
                  inputSource: 'voice',
                );
              }
            }
            return false;
          }

          _liveTranscriptSpeaker = null;
          _liveTranscriptMessageIndex = null;
          setState(() {
            _trainerFeedbackTarget = null;
          });

          await _submitTrainerFeedback(
            target,
            correct: false,
            trainerNote: text,
            inputSource: 'voice',
          );
          return true;
        },
        resolveDeviceContext: (text) async {
          if (!_needsDeviceLocation(text)) return null;
          try {
            return await _deviceLocation.currentContext();
          } catch (_) {
            return null;
          }
        },
        onMission: (mission, requestContext) async {
          if (!mounted || _liveVoice != liveVoice) return;
          final currentText = requestContext.contains('[현재 요청]')
              ? requestContext.split('[현재 요청]').last.trim()
              : requestContext;
          if (_isPhotoEvidenceQuestion(currentText) &&
              _lastBusinesses.isNotEmpty) {
            final answer = _photoEvidenceAnswer();
            _addAssistantMessage(
              text: answer,
              badge: '사진 출처 검사',
            );
            _speakProgress(answer);
            return;
          }

          // Core에 하나의 발화로 확정된 시점부터 다음 사용자 발화는
          // 새 말풍선으로 시작한다. 확정 전의 짧은 쉼은 같은 말풍선에 남는다.
          _liveTranscriptSpeaker = null;
          _liveTranscriptMessageIndex = null;

          final clarifications = _clarifications(mission);
          final responseMode =
              mission['response_mode']?.toString().trim() ?? '';

          if (clarifications.isNotEmpty ||
              responseMode == 'clarify') {
            final reply = _reply(mission);
            setState(() {
              _messages.add(
                _Message(
                  isUser: false,
                  text: reply,
                  mission: mission,
                  requestContext: requestContext,
                ),
              );
            });
            _toBottom();
            _speakProgress(reply);
            return;
          }

          if (responseMode == 'research' ||
              mission['ready_to_research'] == true) {
            await _runRealResearch(mission, forceComplete: true);
            return;
          }

          final reply = _reply(mission);
          setState(() {
            _messages.add(
              _Message(
                isUser: false,
                text: reply,
                mission: mission,
                requestContext: requestContext,
              ),
            );
          });
          _toBottom();
          _speakProgress(reply);
        },
        onDiagnostic: (message) {
          if (!mounted || _liveVoice != liveVoice) return;
          // Keep subsequent Live speech separate from the exact diagnostic.
          _liveTranscriptSpeaker = null;
          _liveTranscriptMessageIndex = null;
          _addAssistantMessage(text: message, badge: 'Core 오류 진단');
        },
        onError: (message) {
          if (!mounted || _liveVoice != liveVoice) return;

          _liveNeedsReconnect = _keepLiveVoice;

          setState(() {
            _liveConnecting = false;
            _liveActive = false;
            _liveStatus = _keepLiveVoice
                ? '재연결 대기'
                : '연결 오류';
          });

          if (_appInForeground && _keepLiveVoice) {
            unawaited(_reconnectLiveVoice());
          } else if (!_keepLiveVoice) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text(message)),
            );
          }
        },
      );

      _liveVoice = liveVoice;
      await liveVoice.start();

      if (!_micEnabled) {
        await liveVoice.pauseAudio();
      }
    } catch (caught) {
      _liveVoice = null;

      if (!automatic) {
        _micEnabled = false;
      }

      if (!mounted) return;

      final message = caught is ArabaApiException
          ? caught.message
          : 'GPT-Live 음성 대화를 시작하지 못했어요.';

      _liveNeedsReconnect = _keepLiveVoice;

      setState(() {
        _liveConnecting = false;
        _liveActive = false;
        _liveStatus = _keepLiveVoice
            ? '재연결 대기'
            : '연결 실패';
      });

      if (!automatic) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(message)),
        );
      }
    }
  }

  void _appendLiveTranscript({
    required bool isUser,
    required String delta,
  }) {
    if (delta.isEmpty) return;

    final speaker = isUser ? 'user' : 'assistant';
    final existingIndex = _liveTranscriptMessageIndex;

    if (_liveTranscriptSpeaker != speaker ||
        existingIndex == null ||
        existingIndex < 0 ||
        existingIndex >= _messages.length) {
      _messages.add(
        _Message(
          isUser: isUser,
          text: delta,
        ),
      );
      _liveTranscriptSpeaker = speaker;
      _liveTranscriptMessageIndex = _messages.length - 1;
      return;
    }

    _messages[existingIndex].text += delta;
  }

  void _addAssistantMessage({
    required String text,
    String? badge,
    List<Map<String, dynamic>>? businesses,
    String? actionQuestion,
    List<String>? actions,
  }) {
    if (!mounted) return;

    setState(() {
      _messages.add(
        _Message(
          isUser: false,
          text: text,
          badge: badge,
          businesses: businesses,
          actionQuestion: actionQuestion,
          actions: actions,
        ),
      );
    });
    _toBottom();
  }

  void _speakProgress(String text) {
    _liveVoice?.speakCommentary(text);
  }

  String _trainerRequestFor(_Message message) {
    final messageIndex = _messages.indexOf(message);
    if (messageIndex <= 0) return '';

    for (var index = messageIndex - 1; index >= 0; index--) {
      final candidate = _messages[index];
      if (candidate.isUser && candidate.text.trim().isNotEmpty) {
        return candidate.text.trim();
      }
    }
    return '';
  }

  _Message? _latestTrainableAssistant() {
    for (var index = _messages.length - 1; index >= 0; index--) {
      final message = _messages[index];
      if (message.isUser) continue;

      final trainable = message.mission != null ||
          (message.businesses?.isNotEmpty ?? false) ||
          message.requestContext != null;
      if (trainable) return message;
    }
    return null;
  }

  bool _looksLikeUserCorrection(String text) {
    final compact = text
        .replaceAll(RegExp(r'\s+'), '')
        .toLowerCase();

    return RegExp(
      r'잘못|틀렸|아니야|아니고|정정|엉뚱|이상해|왜.*못|'
      r'검색.*안|답.*안|그게아니|여기가아니|다시해야',
    ).hasMatch(compact);
  }

  void _recordUserFeedbackCandidate(
    _Message message,
    String feedback, {
    required String inputSource,
  }) {
    final requestText = _trainerRequestFor(message);
    if (requestText.isEmpty || feedback.trim().isEmpty) return;

    unawaited(
      () async {
        try {
          final apiKey = await _keyStore.read();
          if (apiKey == null) return;

          final mission = message.mission ?? const <String, dynamic>{};
          final category =
              mission['category']?.toString().trim() ?? '';

          await _api.submitLiveTrainingFeedback(
            verdict: 'wrong',
            requestText: requestText,
            assistantResponse: message.text,
            apiKey: apiKey,
            category: category,
            trainerNote: feedback.trim(),
            actorRole: 'user',
            context: {
              if (message.mission != null) 'mission': message.mission,
              if (message.businesses != null)
                'businesses': message.businesses,
              if (message.requestContext != null)
                'request_context': message.requestContext,
              'source': 'android_user_correction',
              'input_source': inputSource,
            },
          );
        } catch (_) {
          // 사용자 요청 자체를 방해하지 않도록 학습 후보 저장 실패는
          // 현재 검색/대화 흐름과 분리한다.
        }
      }(),
    );
  }

  void _toggleTrainerMode() {
    setState(() {
      _trainerMode = !_trainerMode;
      if (!_trainerMode) {
        _trainerFeedbackTarget = null;
      }
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          _trainerMode
              ? '훈련사 모드 ON · 결과 아래에서 정상/잘못됨을 평가할 수 있어요.'
              : '훈련사 모드를 종료했어요.',
        ),
      ),
    );
  }

  void _beginTrainerFeedback(_Message message) {
    if (_trainerSubmitting) return;

    setState(() {
      _trainerFeedbackTarget = message;
    });
    _controller.clear();
    _focus.requestFocus();

    _addAssistantMessage(
      text: '이 결과의 잘못된 점과 어떻게 고쳐야 하는지 말씀하거나 입력해주세요. '
          '음성과 텍스트를 같은 훈련 지시로 처리합니다.',
      badge: '훈련 지시 대기',
    );

    if (_liveActive && _micEnabled) {
      _speakProgress(
        '잘못된 점과 원하는 동작을 말씀해주세요. '
        '말씀하신 내용을 훈련 지시로 반영하겠습니다.',
      );
    }
  }

  Future<void> _submitTrainerFeedback(
    _Message message, {
    required bool correct,
    String trainerNote = '',
    String expectedBehavior = '',
    String inputSource = 'button',
  }) async {
    if (_trainerSubmitting) return;

    final requestText = _trainerRequestFor(message);
    if (requestText.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('이 응답에 연결된 사용자 요청을 찾지 못했어요.'),
        ),
      );
      return;
    }

    trainerNote = trainerNote.trim();
    expectedBehavior = expectedBehavior.trim();

    if (!correct &&
        trainerNote.isEmpty &&
        expectedBehavior.isEmpty) {
      _beginTrainerFeedback(message);
      return;
    }

    try {
      setState(() => _trainerSubmitting = true);
      final apiKey = await _keyStore.read();
      if (apiKey == null) {
        throw const ArabaApiException(
          'MY에서 OpenAI API Key를 먼저 저장해주세요.',
        );
      }

      final mission = message.mission ?? const <String, dynamic>{};
      final category = mission['category']?.toString().trim() ?? '';
      final result = await _api.submitLiveTrainingFeedback(
        verdict: correct ? 'correct' : 'wrong',
        requestText: requestText,
        assistantResponse: message.text,
        apiKey: apiKey,
        category: category,
        trainerNote: trainerNote,
        expectedBehavior: expectedBehavior,
        actorRole: 'trainer',
        context: {
          if (message.mission != null) 'mission': message.mission,
          if (message.businesses != null) 'businesses': message.businesses,
          if (message.requestContext != null)
            'request_context': message.requestContext,
          if (message.badge != null) 'badge': message.badge,
          'source': 'android_live_trainer',
          'input_source': inputSource,
        },
      );

      if (!mounted) return;

      if (correct) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('정상 사례로 학습 데이터에 저장했어요.'),
          ),
        );
        return;
      }

      final rawDiagnosis = result['diagnosis'];
      final diagnosis = rawDiagnosis is Map
          ? Map<String, dynamic>.from(rawDiagnosis)
          : <String, dynamic>{};
      final rootCause = diagnosis['root_cause']?.toString().trim() ?? '';
      final instruction =
          diagnosis['corrective_instruction']?.toString().trim() ?? '';
      final verification =
          diagnosis['verification']?.toString().trim() ?? '';
      final needsCodeFix = diagnosis['needs_code_fix'] == true;
      final learned = result['learned'] == true;
      final labCaseId = result['lab_case_id'];
      final labStatus = result['lab_status']?.toString().trim() ?? '';

      final lines = <String>[
        if (labCaseId != null)
          'ARABA Lab #$labCaseId · ${labStatus.isEmpty ? '진단 등록' : labStatus}',
        if (rootCause.isNotEmpty) '원인: $rootCause',
        if (instruction.isNotEmpty)
          learned ? '즉시 학습 규칙: $instruction' : '보완 방향: $instruction',
        if (verification.isNotEmpty) '재검증: $verification',
      ];

      _addAssistantMessage(
        text: lines.isEmpty
            ? (result['message']?.toString() ?? '훈련 피드백을 저장했어요.')
            : lines.join('\n'),
        badge: needsCodeFix
            ? 'ARABA Lab · 코드 보완'
            : (learned ? 'ARABA Lab · 학습 반영' : 'ARABA Lab · 진단 완료'),
      );
    } catch (error) {
      if (!mounted) return;
      final text = error is ArabaApiException
          ? error.message
          : '실시간 훈련 피드백 처리에 실패했어요.';
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(text)),
      );
    } finally {
      if (mounted) {
        setState(() => _trainerSubmitting = false);
      }
    }
  }

  bool _isStatusQuestion(String text) {
    final compact = text
        .replaceAll(RegExp(r'\s+'), '')
        .toLowerCase();

    return compact.contains('알아보고있') ||
        compact.contains('찾고있') ||
        compact.contains('확인중') ||
        compact.contains('진행중');
  }

  String _statusAnswerForLastResearch(
    String text,
  ) {
    if (_lastBusinesses.isEmpty) {
      return '현재 이어서 확인 중인 업체 정보는 없어요.';
    }

    final business = _lastBusinesses.first;
    final name =
        business['name']?.toString().trim() ?? '해당 업체';
    final naver = business['naver'];
    final naverMap = naver is Map
        ? Map<String, dynamic>.from(naver)
        : <String, dynamic>{};
    final rawHours = naverMap['opening_hours'];
    final hours = rawHours is List
        ? rawHours
            .map((item) => item.toString().trim())
            .where((item) => item.isNotEmpty)
            .toList()
        : <String>[];

    if (text.contains('영업시간') ||
        text.contains('운영시간')) {
      if (hours.isNotEmpty) {
        return '$name 영업시간은 ${hours.join(' · ')}로 확인됐어요.';
      }
      return '$name 업체 자체는 확인됐고, 영업시간은 아직 확인되지 않았어요. '
          '네이버 상세정보나 실제 전화로 확인해야 합니다.';
    }

    return '$name 업체는 확인됐어요. 추가로 필요한 정보를 말씀하면 '
        '같은 업체를 기준으로 이어서 확인할게요.';
  }

  bool _isDetailFollowUp(
    Map<String, dynamic> mission,
  ) {
    final target =
        mission['target_business']?.toString().trim() ?? '';
    if (target.isEmpty) return false;

    final facts = mission['required_facts'];
    if (facts is! List || facts.isEmpty) {
      return false;
    }

    final joined = facts
        .map((item) => item.toString())
        .join(' ');

    return RegExp(
      r'영업시간|운영시간|가격|요금|전화|주소|주차|메뉴|예약|재고',
    ).hasMatch(joined);
  }

  String _detailAnswer(
    Map<String, dynamic> mission,
    Map<String, dynamic> business,
  ) {
    final name =
        business['name']?.toString().trim() ?? '해당 업체';
    final naver = business['naver'];
    final naverMap = naver is Map
        ? Map<String, dynamic>.from(naver)
        : <String, dynamic>{};
    final rawHours = naverMap['opening_hours'];
    final hours = rawHours is List
        ? rawHours
            .map((item) => item.toString().trim())
            .where((item) => item.isNotEmpty)
            .toList()
        : <String>[];
    final rawPrices = naverMap['prices'];
    final prices = rawPrices is List
        ? rawPrices
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList()
        : <Map<String, dynamic>>[];
    final parkingAvailable =
        naverMap['parking_available'];
    final phone =
        business['phone']?.toString().trim() ?? '';
    final address =
        business['address']?.toString().trim() ?? '';
    final facts = mission['required_facts'];
    final requested = facts is List
        ? facts.map((item) => item.toString()).join(' ')
        : '';

    final parts = <String>[];

    if (RegExp(r'영업시간|운영시간').hasMatch(requested)) {
      parts.add(
        hours.isNotEmpty
            ? '영업시간: ${hours.join(' · ')}'
            : '영업시간: 아직 확인되지 않음',
      );
    }

    if (RegExp(r'가격|요금|메뉴').hasMatch(requested)) {
      if (prices.isEmpty) {
        parts.add('가격: 아직 확인되지 않음');
      } else {
        final text = prices.take(4).map((item) {
          final label =
              item['name']?.toString().trim() ?? '';
          final price =
              item['price']?.toString().trim() ?? '';
          return label.isEmpty
              ? price
              : '$label $price';
        }).where((item) => item.isNotEmpty).join(' · ');
        if (text.isNotEmpty) {
          parts.add('가격: $text');
        }
      }
    }

    if (requested.contains('전화') && phone.isNotEmpty) {
      parts.add('전화: $phone');
    }
    if (requested.contains('주소') && address.isNotEmpty) {
      parts.add('주소: $address');
    }
    if (requested.contains('주차')) {
      if (parkingAvailable == true) {
        parts.add('주차: 가능');
      } else if (parkingAvailable == false) {
        parts.add('주차: 불가');
      } else {
        parts.add('주차: 확인되지 않음');
      }
    }

    if (parts.isEmpty) {
      return '$name에서 요청한 상세정보를 아직 확인하지 못했어요.';
    }

    return '$name\n${parts.join('\n')}';
  }

  List<Map<String, dynamic>> _businessesFrom(
    Map<String, dynamic> result,
  ) {
    final value = result['businesses'];
    if (value is! List) return const [];

    return value
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  void _startResearchProgress() {
    setState(() {
      _researching = true;
      _researchStage = '상점 찾는 중…';
    });
  }

  void _updateResearchStage(
    String stage, {
    int? revision,
  }) {
    if (!mounted ||
        !_researching ||
        (revision != null && revision != _researchRevision)) {
      return;
    }
    setState(() => _researchStage = stage);
    _toBottom();
  }

  void _stopResearchProgress({
    int? revision,
  }) {
    if (!mounted ||
        (revision != null && revision != _researchRevision)) {
      return;
    }

    setState(() {
      _researching = false;
      _researchStage = '';
    });
  }

  List<String> _businessNames(
    List<Map<String, dynamic>> businesses,
  ) {
    return businesses
        .map((item) => item['name']?.toString().trim() ?? '')
        .where((name) => name.isNotEmpty)
        .toList();
  }

  String _namedMatchAnswer(
    List<Map<String, dynamic>> businesses,
  ) {
    final names = _businessNames(businesses);
    if (names.isEmpty) {
      return '';
    }
    if (names.length == 1) {
      return '조건에 맞는 곳은 ${names.first}입니다.';
    }
    return '조건에 맞는 곳은 ${names.join(' · ')}입니다.';
  }

  Future<void> _enrichVisibleCards(
    Map<String, dynamic> mission,
    List<Map<String, dynamic>> initialBusinesses,
    int messageIndex,
    int revision, {
    required String openAiApiKey,
    String? naverClientId,
    String? naverClientSecret,
    String? googlePlacesApiKey,
  }) async {
    try {
      final result = await _api.enrichBusinesses(
        mission,
        initialBusinesses,
        openAiApiKey: openAiApiKey,
        naverClientId: naverClientId,
        naverClientSecret: naverClientSecret,
        googlePlacesApiKey: googlePlacesApiKey,
      );

      if (!mounted || revision != _researchRevision) return;
      final updated = _businessesFrom(result);
      if (messageIndex >= _messages.length) {
        return;
      }

      // Matching may intentionally remove candidates, but it must never
      // introduce a place that was not in the Kakao-verified candidate set.
      final originalNames = initialBusinesses
          .map((item) => item['name']?.toString().trim() ?? '')
          .where((name) => name.isNotEmpty)
          .toSet();
      for (final business in updated) {
        final updatedName =
            business['name']?.toString().trim() ?? '';
        if (!originalNames.contains(updatedName)) return;
      }

      final rawCoverage = result['coverage'];
      final coverage = rawCoverage is Map
          ? Map<String, dynamic>.from(rawCoverage)
          : <String, dynamic>{};
      int count(String key) {
        final raw = coverage[key];
        return raw is num ? raw.round() : 0;
      }

      final hours = count('hours');
      final parking = count('parking');
      final prices = count('prices');
      final photos = count('photos');
      final total = updated.length;
      final anyDetails = hours + parking + prices + photos > 0;
      final statusCounts = <String, int>{};
      String providerErrorType = '';
      int? providerHttpStatus;
      for (final business in updated) {
        final raw = business['openai_web'];
        if (raw is! Map) continue;
        final info = Map<String, dynamic>.from(raw);
        final status = info['status']?.toString() ?? '';
        if (status.isNotEmpty) {
          statusCounts[status] = (statusCounts[status] ?? 0) + 1;
        }
        if (status == 'provider_error') {
          providerErrorType = info['error_type']?.toString() ?? '';
          final http = info['upstream_http_status'];
          if (http is num) providerHttpStatus = http.round();
        }
      }
      String detailFailure = '';
      if (!anyDetails) {
        if ((statusCounts['provider_error'] ?? 0) > 0) {
          final statusCode = providerHttpStatus == null
              ? ''
              : ' HTTP $providerHttpStatus';
          detailFailure =
              'GPT 웹검색 API 오류: $providerErrorType$statusCode'
              ' · ${statusCounts['provider_error']}곳';
        } else if ((statusCounts['web_search_not_run'] ?? 0) > 0) {
          detailFailure = 'GPT 웹검색이 실제 실행되지 않았어요.';
        } else if ((statusCounts['missing_sources'] ?? 0) > 0) {
          detailFailure =
              '출처 없는 응답 ${statusCounts['missing_sources']}곳.';
        } else if ((statusCounts['identity_not_confirmed'] ?? 0) > 0) {
          detailFailure =
              '동일 업체 확인 실패 ${statusCounts['identity_not_confirmed']}곳.';
        } else if ((statusCounts['not_returned'] ?? 0) > 0) {
          detailFailure =
              'GPT 구조화 응답 누락 ${statusCounts['not_returned']}곳.';
        } else if ((statusCounts['no_detail_found'] ?? 0) > 0) {
          detailFailure = '출처를 조사했지만 상세정보가 확인되지 않았어요.';
        } else {
          detailFailure = '추가로 확인 가능한 상세정보가 없었어요.';
        }
      }

      final rawMatching = result['matching'];
      final matching = rawMatching is Map
          ? Map<String, dynamic>.from(rawMatching)
          : <String, dynamic>{};
      final rawCriteria = matching['criteria'];
      final hasCriteria =
          rawCriteria is List && rawCriteria.isNotEmpty;
      final answerReady = matching['answer_ready'] == true;
      final matchingSummary =
          matching['summary']?.toString().trim() ?? '';
      final matchedCount = matching['matched_count'] is num
          ? (matching['matched_count'] as num).round()
          : updated.length;
      final unverifiedCount =
          matching['unverified_count'] is num
              ? (matching['unverified_count'] as num).round()
              : 0;
      final excludedCount =
          matching['excluded_count'] is num
              ? (matching['excluded_count'] as num).round()
              : 0;
      final namedAnswer = hasCriteria
          ? _namedMatchAnswer(updated)
          : '';

      final remembered = updated.isNotEmpty
          ? updated
          : initialBusinesses;
      _rememberBusinessGroup(mission, remembered);

      final detailStatus = anyDetails
          ? '각 카드에 확인된 정보를 반영했어요.'
          : '$detailFailure 출처가 없는 값은 임의로 채우지 않았어요.';
      setState(() {
        final message = _messages[messageIndex];
        message.businesses = updated;
        message.badge = hasCriteria
            ? (
                answerReady
                    ? '조건 판정 완료'
                    : '조건 근거 추가 확인 필요'
              )
            : (
                anyDetails
                    ? '상세정보 보강 완료'
                    : '상세정보 추가 확인 필요'
              );
        final decisionText = hasCriteria
            ? [
                if (namedAnswer.isNotEmpty) namedAnswer,
                if (matchingSummary.isNotEmpty &&
                    matchingSummary != namedAnswer)
                  matchingSummary,
                '조건충족 $matchedCount · 미확인 $unverifiedCount · '
                    '불일치 $excludedCount',
              ].join('\n')
            : '';
        message.text =
            '${decisionText.isEmpty ? '' : '$decisionText\n'}'
            '업체 $total곳의 실제 정보를 확인했어요.\n'
            '영업시간 $hours/$total · 주차 $parking/$total · '
            '가격 $prices/$total · 사진 $photos/$total\n'
            '$detailStatus';
      });

      if (hasCriteria) {
        final spokenResult = namedAnswer.isNotEmpty
            ? namedAnswer
            : (
                matchingSummary.isNotEmpty
                    ? matchingSummary
                    : '조건을 확인했지만 확정해서 추천할 업체는 아직 없어요.'
              );
        _speakProgress(spokenResult);
      }
    } catch (error) {
      if (!mounted ||
          revision != _researchRevision ||
          messageIndex >= _messages.length) {
        return;
      }
      setState(() {
        _messages[messageIndex].badge = '상세정보 보강 실패';
        _messages[messageIndex].text =
            '업체 위치는 찾았지만 GPT 상세조회 요청에 실패했어요. '
            '${error is ArabaApiException ? error.message : error.runtimeType.toString()}';
      });
    }
  }


  void _rememberBusinessGroup(
    Map<String, dynamic> mission,
    List<Map<String, dynamic>> businesses,
  ) {
    _lastBusinesses = businesses;
    _conversationContext.rememberBusinessResults(mission, businesses);
    if (businesses.isEmpty) return;
    final category = mission['category']?.toString().trim() ?? '';
    final subject = mission['subject']?.toString().trim() ?? '';
    final location = mission['location']?.toString().trim() ?? '';
    _recentBusinessGroups.removeWhere((group) =>
        group['category'] == category &&
        group['subject'] == subject &&
        group['location'] == location);
    _recentBusinessGroups.insert(0, {
      'category': category,
      'subject': subject,
      'location': location,
      'businesses': businesses
          .map((item) => Map<String, dynamic>.from(item))
          .toList(),
    });
    if (_recentBusinessGroups.length > 3) {
      _recentBusinessGroups.removeRange(
        3, _recentBusinessGroups.length);
    }
  }

  List<Map<String, dynamic>> _comparisonCandidates(
      Map<String, dynamic> mission) {
    final request =
        (mission['user_goal'] ?? mission['summary'] ?? '')
            .toString().replaceAll(RegExp(r'\s+'), '');
    if (RegExp(r'아까|이전에|전에찾은|처음찾은').hasMatch(request)) {
      for (final group in _recentBusinessGroups) {
        final subject =
            group['subject']?.toString().replaceAll(' ', '') ?? '';
        final category =
            group['category']?.toString().replaceAll(' ', '') ?? '';
        final specific = subject.length >= 2 ? subject : category;
        if (specific.length < 2 || !request.contains(specific)) {
          continue;
        }
        final saved = group['businesses'];
        if (saved is List) {
          return saved
              .whereType<Map>()
              .map((item) => Map<String, dynamic>.from(item))
              .toList();
        }
      }
    }
    return _lastBusinesses;
  }

  // Reuse the visible result set for contextual comparison follow-ups.
  bool _isRecentPlaceComparison(
    Map<String, dynamic> mission,
  ) {
    if (_comparisonCandidates(mission).isEmpty) return false;
    final mode =
        mission['search_mode']?.toString().trim() ?? '';
    final attributes = mission['attributes'];
    final reuse = attributes is Map &&
        attributes['reuse_recent_results'] == true;
    return mode == 'comparison' && reuse;
  }

  Future<void> _runRecentPlaceComparison(
    Map<String, dynamic> mission,
    int revision,
  ) async {
    final candidates = _comparisonCandidates(mission)
        .map((item) => Map<String, dynamic>.from(item))
        .toList();

    final openAiApiKey = await _keyStore.read();
    if (openAiApiKey == null) {
      throw const ArabaApiException(
        'MY에서 OpenAI API Key를 먼저 저장해주세요.',
      );
    }

    final naverCredentials = await _naverStore.read();
    final googlePlacesApiKey =
        await _googlePlacesStore.read();
    _updateResearchStage(
      '직전 업체를 새로 검색하지 않고 조건별 근거를 판정하는 중…',
      revision: revision,
    );

    final result = await _api.enrichBusinesses(
      mission,
      candidates,
      openAiApiKey: openAiApiKey,
      naverClientId: naverCredentials?.clientId,
      naverClientSecret: naverCredentials?.clientSecret,
      googlePlacesApiKey: googlePlacesApiKey,
    );

    if (!mounted || revision != _researchRevision) {
      return;
    }

    final selected = _businessesFrom(result);
    final rawMatching = result['matching'];
    final matching = rawMatching is Map
        ? Map<String, dynamic>.from(rawMatching)
        : <String, dynamic>{};

    final summary =
        matching['summary']?.toString().trim() ?? '';
    final answerReady = matching['answer_ready'] == true;
    final matchedCount = matching['matched_count'] is num
        ? (matching['matched_count'] as num).round()
        : selected.length;
    final unverifiedCount =
        matching['unverified_count'] is num
            ? (matching['unverified_count'] as num).round()
            : 0;
    final excludedCount =
        matching['excluded_count'] is num
            ? (matching['excluded_count'] as num).round()
            : 0;

    final remembered = selected.isNotEmpty
        ? selected
        : candidates;
    _rememberBusinessGroup(mission, remembered);

    if (selected.length == 1) {
      _conversationContext.rememberBusiness(
        selected.first,
      );
    }

    final namedAnswer = _namedMatchAnswer(selected);
    final answer = namedAnswer.isNotEmpty
        ? namedAnswer
        : (
            summary.isNotEmpty
                ? summary
                : (
                    answerReady
                        ? '조건을 모두 만족하는 업체 $matchedCount곳을 확인했어요.'
                        : '조건을 판정했지만 아직 최종 확정할 근거가 부족해요.'
                  )
          );
    final summaryLine = summary.isNotEmpty &&
            summary != answer
        ? '\n$summary'
        : '';

    _addAssistantMessage(
      text: '$answer$summaryLine\n'
          '조건충족 $matchedCount · 미확인 $unverifiedCount · '
          '불일치 $excludedCount',
      badge: answerReady
          ? '조건 비교 완료'
          : '조건 근거 추가 확인 필요',
      businesses: selected,
    );
    _speakProgress(answer);
  }

  Future<void> _runRealResearch(
    Map<String, dynamic> mission, {
    bool forceComplete = false,
  }) async {
    final researchRevision = ++_researchRevision;
    _startResearchProgress();
    // Required conditions must be checked before a confirmed recommendation.
    final rawCriteria = mission['criteria'];
    final hasRequiredCriteria = rawCriteria is List &&
        rawCriteria.any((item) =>
            item is Map && item['required'] != false);
    final quickCards = !forceComplete &&
        !hasRequiredCriteria && !_isDetailFollowUp(mission);

    try {
      if (_isRecentPlaceComparison(mission)) {
        await _runRecentPlaceComparison(
          mission,
          researchRevision,
        );
        return;
      }
      final openAiApiKey = await _keyStore.read();
      final kakaoRestApiKey = await _kakaoStore.read();
      final googlePlacesApiKey =
          await _googlePlacesStore.read();

      if (openAiApiKey == null) {
        throw const ArabaApiException(
          'MY에서 OpenAI API Key를 먼저 저장해주세요.',
        );
      }

      final naverCredentials = await _naverStore.read();

      _updateResearchStage(
        naverCredentials == null
            ? '상점 찾는 중…'
            : '상점 찾고 네이버 정보 확인하는 중…',
        revision: researchRevision,
      );

      final result = await _api.searchBusinesses(
        mission,
        kakaoRestApiKey: kakaoRestApiKey,
        openAiApiKey: openAiApiKey,
        naverClientId: naverCredentials?.clientId,
        naverClientSecret: naverCredentials?.clientSecret,
        googlePlacesApiKey: googlePlacesApiKey,
        quickCards: quickCards,
      );

      if (!mounted || researchRevision != _researchRevision) {
        return;
      }

      if (result['needs_location_clarification'] == true) {
        final question =
            result['clarification_question']?.toString().trim() ??
                '말씀하신 위치를 확인하지 못했어요. 정확한 지역이나 기준 장소를 다시 말씀해주세요.';
        _addAssistantMessage(
          text: question,
          badge: '위치 확인 필요',
        );
        _speakProgress(question);
        return;
      }

      final businesses = _businessesFrom(result);
      final searchQuery =
          result['search_query']?.toString().trim() ?? '';

      if (businesses.length == 1) {
        _conversationContext.rememberBusiness(
          businesses.first,
        );
      }
      _rememberBusinessGroup(mission, businesses);

      if (businesses.isEmpty) {
        const noResult =
            '관련 업종만 걸러서 찾아봤지만 조건에 맞는 실제 업체를 찾지 못했어요.';
        _addAssistantMessage(
          text: noResult,
          badge: '검색 결과 없음',
        );
        _speakProgress(noResult);
        return;
      }

      if (quickCards) {
        final messageIndex = _messages.length;
        _addAssistantMessage(
          text: '지역·업종이 일치하는 후보 ${businesses.length}곳을 찾았어요. '
              '기본 카드를 먼저 보여드리고, '
              '사진·영업시간·주차·가격을 추가 확인하고 있어요.',
          badge: '상세정보 확인 중',
          businesses: businesses,
        );
        _speakProgress(
          '요청한 지역에서 ${businesses.length}곳을 찾았어요. '
          '카드를 보여드리고 상세정보를 더 확인할게요.',
        );
        unawaited(
          _enrichVisibleCards(
            mission,
            businesses,
            messageIndex,
            researchRevision,
            openAiApiKey: openAiApiKey,
            naverClientId: naverCredentials?.clientId,
            naverClientSecret: naverCredentials?.clientSecret,
            googlePlacesApiKey: googlePlacesApiKey,
          ),
        );
        return;
      }

      final naverMatched =
          result['naver_matched_count'] is num
              ? (result['naver_matched_count'] as num).round()
              : 0;
      final naverPageChecked =
          result['naver_page_checked_count'] is num
              ? (result['naver_page_checked_count'] as num).round()
              : 0;
      final naverConfigured =
          naverCredentials != null;
      final openAiWebEnriched =
          result['openai_web_enriched_count'] is num
              ? (result['openai_web_enriched_count'] as num)
                  .round()
              : 0;
      final representativePhotos =
          result['representative_photo_count'] is num
              ? (result['representative_photo_count'] as num)
                  .round()
              : 0;
      final openingHoursCount =
          result['opening_hours_count'] is num
              ? (result['opening_hours_count'] as num)
                  .round()
              : 0;
      final parkingInfoCount =
          result['parking_info_count'] is num
              ? (result['parking_info_count'] as num)
                  .round()
              : 0;
      final priceInfoCount =
          result['price_info_count'] is num
              ? (result['price_info_count'] as num)
                  .round()
              : 0;
      final rawWebStatuses =
          result['openai_web_status_counts'];
      final webStatuses = rawWebStatuses is Map
          ? Map<String, dynamic>.from(
              rawWebStatuses,
            )
          : <String, dynamic>{};
      int webStatusCount(String key) {
        final value = webStatuses[key];
        return value is num ? value.round() : 0;
      }
      final webProviderErrors =
          webStatusCount('provider_error');
      final webIdentityMisses =
          webStatusCount('identity_not_confirmed');
      final webNotReturned =
          webStatusCount('not_returned');
      final webNoDetail =
          webStatusCount('no_detail_found');

      final evaluationValue =
          result['evaluation'];
      final evaluation =
          evaluationValue is Map
              ? Map<String, dynamic>.from(
                  evaluationValue,
                )
              : <String, dynamic>{};
      final rawMissingFacts =
          evaluation['missing_facts'];
      final missingFacts =
          rawMissingFacts is List
              ? rawMissingFacts
                  .map(
                    (item) =>
                        item.toString().trim(),
                  )
                  .where(
                    (item) => item.isNotEmpty,
                  )
                  .toList()
              : <String>[];
      _updateResearchStage(
        '영업시간·주차·가격·사진을 웹에서 확인하는 중…',
        revision: researchRevision,
      );

      if (_isDetailFollowUp(mission)) {
        final target = mission['target_business']
                ?.toString()
                .trim() ??
            '';
        final selected = businesses.firstWhere(
          (item) {
            final name =
                item['name']?.toString().trim() ?? '';
            return target.isEmpty ||
                name.contains(target) ||
                target.contains(name);
          },
          orElse: () => businesses.first,
        );
        final detail = _detailAnswer(
          mission,
          selected,
        );

        _addAssistantMessage(
          text: detail,
          badge: '상세 확인',
          businesses: [selected],
        );
        _speakProgress(detail);
        return;
      }

      final sourceSummary = [
        '현재 조건에 맞는 후보 ${businesses.length}곳을 확인했어요.',
        if (naverConfigured)
          '네이버 동일 업체 $naverMatched곳'
          ' · 상세페이지 $naverPageChecked곳 확인.',
        if (!naverConfigured)
          '네이버 API는 미설정 상태예요.',
        if (openAiWebEnriched > 0)
          '웹검색으로 $openAiWebEnriched곳의 부족정보를 보강했어요.',
        if (representativePhotos > 0)
          '대표사진 $representativePhotos곳을 확보했어요.',
        '상세정보는 영업시간 $openingHoursCount/${businesses.length}, '
            '주차 $parkingInfoCount/${businesses.length}, '
            '가격 $priceInfoCount/${businesses.length}, '
            '사진 $representativePhotos/${businesses.length} 확인.',
        if (
          openAiWebEnriched == 0 &&
          webNoDetail > 0
        )
          '동일 업체는 찾았지만 상세정보를 확인하지 못한 곳이 $webNoDetail곳 있어요.',
        if (
          openAiWebEnriched == 0 &&
          webProviderErrors > 0
        )
          '웹 보강 호출 실패 $webProviderErrors곳.',
        if (
          openAiWebEnriched == 0 &&
          webProviderErrors == 0 &&
          webIdentityMisses > 0
        )
          '웹에서 동일 업체 확인 실패 $webIdentityMisses곳.',
        if (
          openAiWebEnriched == 0 &&
          webNotReturned > 0
        )
          '웹검색 응답 누락 $webNotReturned곳.',
      ].join(' ');

      final searchDetail = searchQuery.isEmpty
          ? ''
          : '\n\n검색 기준: $searchQuery';

      final evidenceDetail = [
        '\n\n상세정보 확인: 영업시간 $openingHoursCount/${businesses.length}'
            ' · 주차 $parkingInfoCount/${businesses.length}'
            ' · 가격 $priceInfoCount/${businesses.length}'
            ' · 사진 $representativePhotos/${businesses.length}',
        if (missingFacts.isNotEmpty)
          '\n아직 확인이 필요한 정보: ${missingFacts.join(' · ')}',
      ].join();

      final missionLocation =
          mission['location']?.toString().trim() ?? '';
      final missionCategory =
          mission['category']?.toString().trim() ?? '업체';
      final locationContext = mission['location_context'];
      final locationType = locationContext is Map
          ? locationContext['type']?.toString().trim() ?? ''
          : '';
      final spokenLocation = missionLocation.isEmpty
          ? ''
          : (
              locationType == 'reference_point'
                  ? '$missionLocation 주변에서 '
                  : '$missionLocation에서 '
            );
      final spokenSummary =
          '$spokenLocation$missionCategory ${businesses.length}곳을 확인했어요. '
          '검증된 결과를 화면 카드로 보여드릴게요.';
      _addAssistantMessage(
        text:
            '$sourceSummary$evidenceDetail$searchDetail',
        badge: missingFacts.isNotEmpty
            ? '추가 확인 필요'
            : (
                openAiWebEnriched > 0
                    ? '카카오 + 웹 검증'
                    : (
                        naverConfigured
                            ? '카카오 + 네이버 검증'
                            : '카카오 검증'
                      )
              ),
        businesses: businesses,
      );
      _speakProgress(spokenSummary);    } catch (error) {
      if (!mounted || researchRevision != _researchRevision) {
        return;
      }

      final message = error is ArabaApiException
          ? error.message
          : '실제 업체 조사 중 문제가 생겼어요.';

      _addAssistantMessage(
        text: message,
        badge: '조사 오류',
      );
      _speakProgress(message);
    } finally {
      _stopResearchProgress(
        revision: researchRevision,
      );
    }
  }

  Future<void> _handleResearchAction(
    String action,
    _Message source,
  ) async {
    if (_researching) return;

    setState(() {
      _messages.add(
        _Message(
          isUser: true,
          text: action,
        ),
      );
    });
    _toBottom();

    if (action == '예약하기' ||
        action.startsWith('예약:')) {
      setState(() => _researching = true);

      final selectedTime = action.startsWith('예약:')
          ? action.substring('예약:'.length).trim()
          : '';

      final businesses =
          source.businesses ?? const [];
      final first = businesses.isNotEmpty
          ? businesses.first
          : const <String, dynamic>{};
      final businessName =
          first['name']?.toString().trim() ?? '추천 업체';

      final calling = selectedTime.isEmpty
          ? '$businessName에 가능한 예약시간을 다시 확인하고 있어요. 지금은 가상 통화입니다.'
          : '$businessName에 $selectedTime 예약 가능 여부를 확인하고 있어요. 지금은 가상 통화입니다.';

      _addAssistantMessage(
        text: calling,
        badge: '가상 예약',
      );
      _speakProgress(calling);

      final done = selectedTime.isEmpty
          ? '가상 예약 확인을 마쳤어요. 실제 예약은 아직 이루어지지 않았습니다.'
          : '$businessName의 $selectedTime 예약이 가능하다고 가정해 가상 예약을 완료했어요. '
              '실제 통화 기능이 연결되면 같은 흐름으로 확정 예약까지 진행합니다.';

      _addAssistantMessage(
        text: done,
        badge: '가상 예약 완료',
      );
      _speakProgress(done);

      if (mounted) {
        setState(() => _researching = false);
      }
      return;
    }

    if (action == '다른 후보 보기') {
      final businesses = source.businesses ?? const [];
      _addAssistantMessage(
        text: '다른 후보도 함께 비교해볼게요. 현재는 가상 테스트 결과입니다.',
        badge: '다른 후보',
        businesses: businesses,
      );
      _speakProgress('다른 후보도 함께 비교해서 보여드릴게요.');
      return;
    }

    _addAssistantMessage(
      text: '알겠어요. 여기까지 정리해둘게요.',
    );
    _speakProgress('알겠어요. 여기까지 정리해둘게요.');
  }

  void _toBottom({bool force = false}) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      if (_userBrowsingHistory && !force) return;

      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 240),
        curve: Curves.easeOut,
      );
    });
  }

  bool _handleChatScroll(ScrollNotification notification) {
    if (notification is ScrollStartNotification &&
        notification.dragDetails != null) {
      _userBrowsingHistory = true;
    } else if (notification is ScrollUpdateNotification &&
        notification.dragDetails != null) {
      _userBrowsingHistory = true;
    } else if (notification is ScrollEndNotification) {
      final remaining =
          notification.metrics.maxScrollExtent -
          notification.metrics.pixels;

      if (remaining <= 40) {
        _userBrowsingHistory = false;
      }
    }

    return false;
  }

  List<Map<String, dynamic>> _clarifications(
    Map<String, dynamic> mission,
  ) {
    final value = mission['clarification_questions'];
    if (value is! List) return const [];

    return value
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .where((item) {
          final question = item['question']?.toString().trim() ?? '';
          return question.isNotEmpty;
        })
        .toList();
  }

  String _reply(Map<String, dynamic> mission) {
    final summary = mission['summary']?.toString().trim() ?? '';
    final directAnswer =
        mission['direct_answer']?.toString().trim() ?? '';
    final responseMode =
        mission['response_mode']?.toString().trim() ?? '';
    final clarifications = _clarifications(mission);

    if (clarifications.isNotEmpty) {
      final question =
          clarifications.first['question']?.toString().trim() ?? '';
      if (question.isNotEmpty) {
        return summary.isEmpty
            ? question
            : '$summary\n\n$question';
      }
      return summary.isEmpty
          ? '진행에 필요한 정보를 알려주세요.'
          : '$summary\n\n진행에 필요한 정보를 알려주세요.';
    }

    if (responseMode == 'answer' && directAnswer.isNotEmpty) {
      return directAnswer;
    }

    return summary.isEmpty ? '요청을 이해했어요.' : summary;
  }

  Future<void> _pickResearchImage(
    ImageSource source,
  ) async {
    if (_sending || _researching) return;

    try {
      final image = await _imagePicker.pickImage(
        source: source,
        imageQuality: 88,
        maxWidth: 2200,
      );

      if (image == null) return;

      final apiKey = await _keyStore.read();

      if (apiKey == null) {
        throw const ArabaApiException(
          'MY에서 OpenAI API Key를 먼저 저장해주세요.',
        );
      }

      final bytes = await image.readAsBytes();

      setState(() {
        _sending = true;
        _messages.add(
          _Message(
            isUser: true,
            text: '사진 첨부 · ${image.name}',
          ),
        );
      });
      _toBottom();

      final result = await _api.analyzeResearchImage(
        bytes: bytes,
        filename: image.name,
        mimeType: image.mimeType ?? 'image/jpeg',
        context:
            _conversationContext.enrichRequest(
          '사진에서 현재 조사에 필요한 정보를 확인해줘.',
        ),
        apiKey: apiKey,
      );

      final summary =
          result['summary']?.toString().trim() ?? '';
      final rawAttributes = result['attributes'];
      final attributes = rawAttributes is Map
          ? Map<String, dynamic>.from(rawAttributes)
          : <String, dynamic>{};
      final rawWarnings = result['warnings'];
      final warnings = rawWarnings is List
          ? rawWarnings
                .map((item) => item.toString().trim())
                .where((item) => item.isNotEmpty)
                .toList()
          : <String>[];

      if (attributes.isNotEmpty) {
        _conversationContext.rememberAttributes(
          attributes,
        );
      }

      if (!mounted) return;

      final attributeText = attributes.entries
          .map(
            (entry) =>
                '${entry.key} ${entry.value}',
          )
          .join(' · ');

      final parts = <String>[
        if (summary.isNotEmpty) summary,
        if (attributes.isNotEmpty)
          '확인한 정보: $attributeText',
        if (warnings.isNotEmpty)
          '확인이 더 필요한 부분: ${warnings.join(' · ')}',
      ];

      setState(() {
        _messages.add(
          _Message(
            isUser: false,
            text: parts.isEmpty
                ? '사진은 확인했지만 현재 조사에 추가할 정보를 찾지 못했어요.'
                : '${parts.join('\n\n')}\n\n이 정보는 다음 조사와 대화에 반영할게요.',
            badge: '사진 판독',
          ),
        );
      });
      _toBottom();
    } catch (error) {
      if (!mounted) return;

      final message = error is ArabaApiException
          ? error.message
          : '사진을 확인하는 중 문제가 생겼어요.';

      setState(() {
        _messages.add(
          _Message(
            isUser: false,
            text: message,
            isError: true,
            badge: '사진 오류',
          ),
        );
      });
      _toBottom();
    } finally {
      if (mounted) {
        setState(() {
          _sending = false;
        });
      }
    }
  }

  Future<void> _showImageSourcePicker() async {
    if (_sending || _researching) return;

    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(
              16,
              8,
              16,
              20,
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                ListTile(
                  leading: const Icon(
                    Icons.photo_camera_outlined,
                  ),
                  title: const Text('사진 촬영'),
                  subtitle: const Text(
                    '지금 필요한 정보를 카메라로 찍어서 판독',
                  ),
                  onTap: () {
                    Navigator.of(sheetContext).pop();
                    unawaited(
                      _pickResearchImage(
                        ImageSource.camera,
                      ),
                    );
                  },
                ),
                ListTile(
                  leading: const Icon(
                    Icons.photo_library_outlined,
                  ),
                  title: const Text('갤러리에서 선택'),
                  subtitle: const Text(
                    '이미 찍어둔 사진·견적서·라벨 등을 판독',
                  ),
                  onTap: () {
                    Navigator.of(sheetContext).pop();
                    unawaited(
                      _pickResearchImage(
                        ImageSource.gallery,
                      ),
                    );
                  },
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Future<void> _send() async {
    final text = _controller.text.trim();

    if (text.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('알아볼 내용을 입력해주세요.')),
      );
      return;
    }

    _controller.clear();
    _userBrowsingHistory = false;
    _toBottom(force: true);

    final trainerTarget = _trainerFeedbackTarget;
    if (_trainerMode && trainerTarget != null) {
      setState(() {
        _messages.add(
          _Message(
            isUser: true,
            text: text,
          ),
        );
        _trainerFeedbackTarget = null;
      });
      _toBottom();

      await _submitTrainerFeedback(
        trainerTarget,
        correct: false,
        trainerNote: text,
        inputSource: 'text',
      );
      return;
    }

    if (!_trainerMode && _looksLikeUserCorrection(text)) {
      final previous = _latestTrainableAssistant();
      if (previous != null) {
        _recordUserFeedbackCandidate(
          previous,
          text,
          inputSource: 'text',
        );
      }
    }

    if (_isStatusQuestion(text)) {
      setState(() {
        _messages.add(
          _Message(
            isUser: true,
            text: text,
          ),
        );
        _messages.add(
          _Message(
            isUser: false,
            text: _statusAnswerForLastResearch(
              text,
            ),
          ),
        );
      });
      _toBottom();
      return;
    }

    if (_isPhotoEvidenceQuestion(text) && _lastBusinesses.isNotEmpty) {
      setState(() {
        _messages.add(_Message(isUser: true, text: text));
        _messages.add(_Message(
          isUser: false,
          text: _photoEvidenceAnswer(),
          badge: '사진 출처 검사',
        ));
      });
      _toBottom();
      return;
    }
    await _requestMission(
      displayText: text,
      requestText: text,
    );
  }

  Future<void> _answerClarification({
    required String question,
    required String option,
    required String requestContext,
  }) async {
    _liveVoice?.resetPendingMissionContext();

    final combinedRequest = [
      requestContext,
      '',
      '사용자 추가 답변:',
      '$question: $option',
    ].join('\n');

    await _requestMission(
      displayText: option,
      requestText: combinedRequest,
    );
  }

  bool _needsDeviceLocation(String text) {
    final compact = text.replaceAll(
      RegExp(r'\s+'),
      '',
    );
    return RegExp(
      r'내(?:가)?(?:있는|있는곳|위치|주변|근처)|'
      r'현재위치|현위치|내위치|'
      r'여기(?:주변|근처)|'
      r'지금있는곳|지금여기|'
      r'가까운곳|가까운업체|가까운가게',
    ).hasMatch(compact);
  }


  bool _isPhotoEvidenceQuestion(String text) {
    final compact = text.replaceAll(RegExp(r'\s+'), '');
    return RegExp(r'사진|이미지|대표사진').hasMatch(compact) &&
        RegExp(r'출처|근거|실제|맞는사진|어디서').hasMatch(compact);
  }

  String _photoEvidenceAnswer() {
    if (_lastBusinesses.isEmpty) {
      return '출처를 확인할 업체 결과가 없어요. 먼저 업체를 찾아주세요.';
    }
    final lines = <String>[];
    for (final business in _lastBusinesses) {
      final name = business['name']?.toString().trim() ?? '업체';
      final url = business['image_url']?.toString().trim() ?? '';
      final source = business['image_source']?.toString().trim() ?? '';
      final verified = business['image_identity_verified'] == true ||
          source == 'kakao_place' ||
          source == 'naver_place' ||
          source == 'business_official';
      if (url.isEmpty || !verified) {
        lines.add('• $name: 업체 사진 미확인 (검증된 사진 출처 없음)');
        continue;
      }
      final evidence = business['image_source_url']?.toString().trim() ??
          business['place_url']?.toString().trim() ?? '';
      final citation = evidence.isEmpty
          ? ' (원본 링크 미제공)'
          : '\n  확인 링크: $evidence';
      lines.add('• $name: 사진 제공처 $source$citation');
    }
    return '현재 카드에 연결된 사진의 검증 상태입니다.\n'
        '${lines.join('\n')}\n'
        '사진이 없는 업체는 실제 사진임을 검증할 근거가 없어 숨겼습니다. '
        '이 결과를 사진 검증 완료로 표시하지 않습니다.';
  }

  Future<void> _requestMission({
    required String displayText,
    required String requestText,
  }) async {
    if (_sending) return;

    setState(() {
      _messages.add(
        _Message(
          isUser: true,
          text: displayText,
        ),
      );
      _sending = true;
    });
    _toBottom();

    try {
      final apiKey = await _keyStore.read();

      if (apiKey == null) {
        throw const ArabaApiException(
          'MY에서 OpenAI API Key를 먼저 저장해주세요.',
        );
      }

      final contextualRequest =
          _conversationContext.enrichRequest(requestText);
      Map<String, dynamic>? deviceContext;
      if (_needsDeviceLocation(requestText)) {
        try {
          deviceContext =
              await _deviceLocation.currentContext();
        } catch (_) {
          deviceContext = null;
        }
      }
      final result = await _api.createMission(
        contextualRequest,
        apiKey: apiKey,
        deviceContext: deviceContext,
      );

      if (!mounted) return;

      final rawMissions = result['missions'];
      final missions = rawMissions is List
          ? rawMissions
              .whereType<Map>()
              .map((item) => Map<String, dynamic>.from(item))
              .toList()
          : <Map<String, dynamic>>[
              if (result['mission'] is Map)
                Map<String, dynamic>.from(result['mission'] as Map),
            ];
      if (missions.isEmpty) {
        throw const ArabaApiException(
          '서버가 실행할 요청을 반환하지 않았어요.',
        );
      }

      for (var index = 0; index < missions.length; index++) {
        if (!mounted) return;
        final mission = missions[index];
        _conversationContext.rememberMission(mission);
        if (missions.length > 1) {
          _addAssistantMessage(
            text: '요청 ${index + 1}/${missions.length}: '
                '${mission['summary'] ?? mission['title'] ?? '개별 요청'}',
            badge: '복수 요청 처리',
          );
        }
        final clarifications = _clarifications(mission);
        final responseMode =
            mission['response_mode']?.toString().trim() ?? '';

        if (clarifications.isNotEmpty || responseMode == 'clarify') {
          setState(() {
            _messages.add(
              _Message(
                isUser: false,
                text: _reply(mission),
                mission: mission,
                requestContext: contextualRequest,
              ),
            );
          });
        } else if (responseMode == 'research' ||
            mission['ready_to_research'] == true) {
          if (missions.length == 1) {
            setState(() => _sending = false);
          }
          await _runRealResearch(
            mission,
            forceComplete: missions.length > 1,
          );
        } else {
          setState(() {
            _messages.add(
              _Message(
                isUser: false,
                text: _reply(mission),
                mission: mission,
                requestContext: contextualRequest,
              ),
            );
          });
        }
      }
    } catch (error) {
      if (!mounted) return;

      final message = error is ArabaApiException
          ? error.diagnosticText
          : '요청 처리 중 문제가 생겼어요. 잠시 후 다시 시도해주세요.';

      setState(() {
        _messages.add(
          _Message(
            isUser: false,
            text: message,
            isError: true,
          ),
        );
      });
    } finally {
      if (mounted) {
        setState(() => _sending = false);
        _toBottom();
      }
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _keepLiveVoice = false;
    _micEnabled = false;
    _liveVoice?.stop(force: true);
    _controller.dispose();
    _scroll.dispose();
    _focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF7F8FC),
      appBar: AppBar(
        backgroundColor: Colors.white,
        surfaceTintColor: Colors.white,
        titleSpacing: 20,
        title: const Row(
          children: [
            Text(
              'ARABA',
              style: TextStyle(fontWeight: FontWeight.w900),
            ),
            SizedBox(width: 8),
            Text(
              '알아봐',
              style: TextStyle(
                fontSize: 14,
                color: Color(0xFF667085),
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: InkWell(
              onTap: _toggleTrainerMode,
              borderRadius: BorderRadius.circular(30),
              child: Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 7,
                ),
                decoration: BoxDecoration(
                  color: _trainerMode
                      ? const Color(0xFFECFDF3)
                      : const Color(0xFFEEF4FF),
                  borderRadius: BorderRadius.circular(30),
                  border: Border.all(
                    color: _trainerMode
                        ? const Color(0xFF12B76A)
                        : const Color(0xFFD6E4FF),
                  ),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      _trainerMode
                          ? Icons.school_rounded
                          : Icons.model_training_rounded,
                      size: 15,
                      color: _trainerMode
                          ? const Color(0xFF027A48)
                          : const Color(0xFF3157D5),
                    ),
                    const SizedBox(width: 5),
                    Text(
                      _trainerMode
                          ? '훈련사 ON'
                          : '실시간 머신러닝',
                      style: TextStyle(
                        color: _trainerMode
                            ? const Color(0xFF027A48)
                            : const Color(0xFF3157D5),
                        fontSize: 11,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Stack(
              children: [
                Column(
                  children: [
                Expanded(
                  child: NotificationListener<ScrollNotification>(
                    onNotification: _handleChatScroll,
                    child: ListView.builder(
                      controller: _scroll,
                      padding: const EdgeInsets.fromLTRB(
                        16,
                        22,
                        16,
                        18,
                      ),
                      itemCount: _messages.length +
                          (_sending ? 1 : 0) +
                          (_researching ? 1 : 0),
                      itemBuilder: (context, index) {
                        if (index >= _messages.length) {
                          final extraIndex =
                              index - _messages.length;

                          if (_sending && extraIndex == 0) {
                            return const _InlineStatusText(
                              text: '요청 이해 중…',
                            );
                          }

                          return _InlineStatusText(
                            text: _researchStage.isEmpty
                                ? '확인 중…'
                                : _researchStage,
                          );
                        }

                        final message = _messages[index];

                        if (message.isUser) {
                          return _UserBubble(text: message.text);
                        }

                        return _AssistantBubble(
                          message: message,
                          onClarification: ({
                            required question,
                            required option,
                            required requestContext,
                          }) {
                            _answerClarification(
                              question: question,
                              option: option,
                              requestContext: requestContext,
                            );
                          },
                          onAction: (action) {
                            _handleResearchAction(
                              action,
                              message,
                            );
                          },
                          trainerMode: _trainerMode,
                          trainerSubmitting: _trainerSubmitting,
                          onTrainerFeedback: (correct) {
                            if (correct) {
                              _submitTrainerFeedback(
                                message,
                                correct: true,
                              );
                            } else {
                              _beginTrainerFeedback(message);
                            }
                          },
                        );
                      },
                    ),
                  ),
                ),
                if (_liveConnecting || _liveActive)
                  _LivePanel(
                    status: _liveStatus,
                    active: _liveActive,
                  ),
                _Composer(
                  controller: _controller,
                  focusNode: _focus,
                  listening:
                      _liveActive && _micEnabled,
                  sending:
                      _sending || _liveConnecting,
                  micDisabled:
                      _liveConnecting,
                  onImage: _showImageSourcePicker,
                  onMic: _toggleLiveVoice,
                  onSend: _send,
                ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Message {
  final bool isUser;
  String text;
  final Map<String, dynamic>? mission;
  final String? requestContext;
  final bool isError;
  String? badge;
  List<Map<String, dynamic>>? businesses;
  final String? actionQuestion;
  final List<String>? actions;

  _Message({
    required this.isUser,
    required this.text,
    this.mission,
    this.requestContext,
    this.isError = false,
    this.badge,
    this.businesses,
    this.actionQuestion,
    this.actions,
  });
}

class _UserBubble extends StatelessWidget {
  final String text;

  const _UserBubble({
    required this.text,
  });

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 560),
        margin: const EdgeInsets.only(left: 54, bottom: 14),
        padding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 12,
        ),
        decoration: const BoxDecoration(
          color: Color(0xFF3157D5),
          borderRadius: BorderRadius.only(
            topLeft: Radius.circular(18),
            topRight: Radius.circular(18),
            bottomLeft: Radius.circular(18),
            bottomRight: Radius.circular(5),
          ),
        ),
        child: Text(
          text,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 15,
            height: 1.45,
          ),
        ),
      ),
    );
  }
}

class _AssistantBubble extends StatelessWidget {
  final _Message message;
  final void Function({
    required String question,
    required String option,
    required String requestContext,
  }) onClarification;
  final ValueChanged<String> onAction;
  final bool trainerMode;
  final bool trainerSubmitting;
  final ValueChanged<bool> onTrainerFeedback;

  const _AssistantBubble({
    required this.message,
    required this.onClarification,
    required this.onAction,
    required this.trainerMode,
    required this.trainerSubmitting,
    required this.onTrainerFeedback,
  });

  List<Map<String, dynamic>> _clarifications() {
    final value = message.mission?['clarification_questions'];
    if (value is! List) return const [];

    return value
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .where((item) {
          final question = item['question']?.toString().trim() ?? '';
          final options = item['options'];
          return question.isNotEmpty && options is List && options.isNotEmpty;
        })
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    final clarifications = _clarifications();
    final canTrain = message.mission != null ||
        (message.businesses?.isNotEmpty ?? false) ||
        message.badge != null;

    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 600),
        margin: const EdgeInsets.only(right: 34, bottom: 14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 34,
              height: 34,
              decoration: BoxDecoration(
                color: const Color(0xFF101828),
                borderRadius: BorderRadius.circular(11),
              ),
              alignment: Alignment.center,
              child: const Text(
                'A',
                style: TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.w900,
                ),
              ),
            ),
            const SizedBox(width: 9),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 13,
                    ),
                    decoration: BoxDecoration(
                      color: message.isError
                          ? const Color(0xFFFFF1F0)
                          : Colors.white,
                      borderRadius: const BorderRadius.only(
                        topLeft: Radius.circular(5),
                        topRight: Radius.circular(18),
                        bottomLeft: Radius.circular(18),
                        bottomRight: Radius.circular(18),
                      ),
                      border: Border.all(
                        color: message.isError
                            ? const Color(0xFFFFCCC7)
                            : const Color(0xFFE4E7EC),
                      ),
                    ),
                    child: Text(
                      message.text,
                      style: const TextStyle(
                        color: Color(0xFF101828),
                        fontSize: 15,
                        height: 1.5,
                      ),
                    ),
                  ),
                  if (message.badge != null) ...[
                    const SizedBox(height: 8),
                    _StatusBadge(text: message.badge!),
                  ],
                  if (message.requestContext != null &&
                      clarifications.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    for (final clarification in clarifications)
                      _ClarificationCard(
                        question:
                            clarification['question']?.toString() ?? '',
                        options: (clarification['options'] as List)
                            .map((item) => item.toString())
                            .where((item) => item.trim().isNotEmpty)
                            .toList(),
                        onSelected: (option) {
                          onClarification(
                            question:
                                clarification['question']?.toString() ?? '',
                            option: option,
                            requestContext: message.requestContext!,
                          );
                        },
                      ),
                  ],
                  if (message.businesses != null &&
                      message.businesses!.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    _BusinessCards(
                      businesses: message.businesses!,
                    ),
                  ],
                  if (message.actionQuestion != null &&
                      message.actions != null &&
                      message.actions!.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    _ActionCard(
                      question: message.actionQuestion!,
                      actions: message.actions!,
                      onSelected: onAction,
                    ),
                  ],
                  if (trainerMode && canTrain) ...[
                    const SizedBox(height: 8),
                    _TrainerFeedbackBar(
                      submitting: trainerSubmitting,
                      onCorrect: () => onTrainerFeedback(true),
                      onWrong: () => onTrainerFeedback(false),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _TrainerFeedbackBar extends StatelessWidget {
  final bool submitting;
  final VoidCallback onCorrect;
  final VoidCallback onWrong;

  const _TrainerFeedbackBar({
    required this.submitting,
    required this.onCorrect,
    required this.onWrong,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: 10,
        vertical: 8,
      ),
      decoration: BoxDecoration(
        color: const Color(0xFFF6FEF9),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: const Color(0xFFA6F4C5),
        ),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.school_outlined,
            size: 16,
            color: Color(0xFF027A48),
          ),
          const SizedBox(width: 6),
          const Expanded(
            child: Text(
              '훈련사 평가',
              style: TextStyle(
                color: Color(0xFF027A48),
                fontSize: 11.5,
                fontWeight: FontWeight.w900,
              ),
            ),
          ),
          TextButton(
            onPressed: submitting ? null : onCorrect,
            child: const Text('정상'),
          ),
          const SizedBox(width: 4),
          FilledButton.tonal(
            onPressed: submitting ? null : onWrong,
            child: Text(
              submitting ? '분석 중…' : '잘못됨 · 학습',
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusBadge extends StatelessWidget {
  final String text;

  const _StatusBadge({
    required this.text,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: 10,
        vertical: 5,
      ),
      decoration: BoxDecoration(
        color: const Color(0xFFF2F4F7),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(
          color: const Color(0xFFE4E7EC),
        ),
      ),
      child: Text(
        text,
        style: const TextStyle(
          color: Color(0xFF475467),
          fontSize: 12,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class _BusinessImageFallback extends StatelessWidget {
  final String message;
  final double iconSize;

  const _BusinessImageFallback({
    required this.message,
    this.iconSize = 38,
  });

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: const Color(0xFFEEF4FF),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.storefront_rounded,
              size: iconSize,
              color: const Color(0xFF3157D5),
            ),
            const SizedBox(height: 8),
            Text(
              message,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: Color(0xFF667085),
                fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _BusinessCards extends StatelessWidget {
  final List<Map<String, dynamic>> businesses;
  final ArabaApi _api = ArabaApi();

  _BusinessCards({
    required this.businesses,
  });

  Future<void> _openPlace(String placeUrl) async {
    final uri = Uri.tryParse(placeUrl);
    if (uri == null) return;

    await launchUrl(
      uri,
      mode: LaunchMode.externalApplication,
    );
  }

  Future<void> _callPhone(String phone) async {
    final normalized = phone.replaceAll(
      RegExp(r'[^0-9+]'),
      '',
    );
    if (normalized.isEmpty) return;

    final uri = Uri(
      scheme: 'tel',
      path: normalized,
    );
    await launchUrl(uri);
  }

  String _priceText(
    List<Map<String, dynamic>> prices,
  ) {
    return prices
        .take(8)
        .map((item) {
          final name =
              item['name']?.toString().trim() ?? '';
          final price =
              item['price']?.toString().trim() ?? '';
          if (price.isEmpty) return '';
          return name.isEmpty ? price : '$name $price';
        })
        .where((item) => item.isNotEmpty)
        .join(' · ');
  }

  Future<void> _leaveExperience(
    BuildContext context,
    Map<String, dynamic> business,
  ) async {
    final name =
        business['name']?.toString().trim() ?? '업체';
    final controller = TextEditingController();

    final text = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('$name 이용 경험'),
        content: TextField(
          controller: controller,
          autofocus: true,
          minLines: 3,
          maxLines: 6,
          decoration: const InputDecoration(
            hintText:
                '예: 주차장은 좁았고 15분 정도 기다렸지만 설명은 자세했어요.',
            border: OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () =>
                Navigator.of(dialogContext).pop(),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(
              controller.text.trim(),
            ),
            child: const Text('경험 저장'),
          ),
        ],
      ),
    );

    controller.dispose();
    if (text == null || text.trim().isEmpty) return;

    try {
      final rawBusinessId = business['araba_business_id'];
      final businessId = rawBusinessId is num
          ? rawBusinessId.round()
          : int.tryParse(rawBusinessId?.toString() ?? '');
      final providerPlaceId =
          business['id']?.toString().trim();

      final result = await _api.submitBusinessExperience(
        businessId: businessId,
        providerPlaceId: providerPlaceId,
        text: text,
        verifiedVisit: false,
      );

      business['experience_count'] =
          result['experience_count'] ?? 1;
      business['verified_experience_count'] =
          result['verified_experience_count'] ?? 0;

      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '$name 이용 경험을 ARABA 경험 DB에 저장했어요.',
          ),
        ),
      );
    } catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            error is ArabaApiException
                ? error.message
                : '이용 경험 저장에 실패했어요.',
          ),
        ),
      );
    }
  }

  Future<void> _showBusinessDetail(
    BuildContext context,
    Map<String, dynamic> business,
  ) async {
    final name =
        business['name']?.toString().trim() ?? '업체';
    final description =
        business['description']?.toString().trim() ?? '';
    final address =
        business['address']?.toString().trim() ?? '';
    final phone =
        business['phone']?.toString().trim() ?? '';
    final imageUrl =
        business['image_url']?.toString().trim() ?? '';
    final imageSource =
        business['image_source']?.toString().trim() ?? '';
    final rawImageAttributions =
        business['image_attributions'];
    final imageAttributions =
        rawImageAttributions is List
            ? rawImageAttributions
                .whereType<Map>()
                .map(
                  (item) =>
                      Map<String, dynamic>.from(item),
                )
                .toList()
            : <Map<String, dynamic>>[];
    final imageAuthor =
        imageAttributions.isNotEmpty
            ? imageAttributions.first['display_name']
                    ?.toString()
                    .trim() ??
                ''
            : '';
    final imageAuthorUri =
        imageAttributions.isNotEmpty
            ? imageAttributions.first['uri']
                    ?.toString()
                    .trim() ??
                ''
            : '';
    final imageGoogleMapsUri =
        business['image_google_maps_uri']
                ?.toString()
                .trim() ??
            '';
    final imageCredit =
        imageSource == 'google_places_verified'
            ? (
                imageAuthor.isNotEmpty
                    ? 'Google Maps · 사진: $imageAuthor'
                    : 'Google Maps'
              )
            : (
                imageSource == 'kakao_place'
                    ? '카카오 등록사진'
                    : (
                        imageSource == 'naver_place'
                            ? '네이버 플레이스 확인사진'
                            : '업체 확인사진'
                      )
              );
    final placeUrl =
        business['place_url']?.toString().trim() ?? '';
    final naverValue = business['naver'];
    final naver = naverValue is Map
        ? Map<String, dynamic>.from(naverValue)
        : <String, dynamic>{};
    final naverUrl =
        (
          naver['page_url'] ??
          naver['link'] ??
          naver['search_url']
        )?.toString().trim() ??
            '';
    final webValue = business['web'];
    final web = webValue is Map
        ? Map<String, dynamic>.from(webValue)
        : <String, dynamic>{};
    final rawSources = web['sources'];
    final webSources = rawSources is List
        ? rawSources
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList()
        : <Map<String, dynamic>>[];
    final webSourceUrl = webSources.isNotEmpty
        ? webSources.first['url']?.toString().trim() ?? ''
        : '';
    final openAiWebValue = business['openai_web'];
    final openAiWeb = openAiWebValue is Map
        ? Map<String, dynamic>.from(openAiWebValue)
        : <String, dynamic>{};
    final rawOpenAiSources = openAiWeb['sources'];
    final openAiSources = rawOpenAiSources is List
        ? rawOpenAiSources
            .map((item) => item.toString().trim())
            .where((item) => item.isNotEmpty)
            .toList()
        : <String>[];
    final openAiSourceUrl = openAiSources.isNotEmpty
        ? openAiSources.first
        : '';
    final experienceCount =
        business['experience_count'] is num
            ? (business['experience_count'] as num).round()
            : int.tryParse(
                  business['experience_count']?.toString() ?? '',
                ) ??
                0;
    final verifiedExperienceCount =
        business['verified_experience_count'] is num
            ? (business['verified_experience_count'] as num)
                .round()
            : 0;
    final rawExperienceSnippets =
        business['experience_snippets'];
    final experienceSnippets =
        rawExperienceSnippets is List
            ? rawExperienceSnippets
                .map((item) => item.toString().trim())
                .where((item) => item.isNotEmpty)
                .take(2)
                .toList()
            : <String>[];
    final cacheHit =
        business['araba_cache_hit'] == true;

    final priceLink =
        (naver['price_link'] ?? web['price_link'])
                ?.toString()
                .trim() ??
            '';
    final rawHours = naver['opening_hours'];
    final openingHours = rawHours is List
        ? rawHours
            .map((item) => item.toString().trim())
            .where((item) => item.isNotEmpty)
            .toList()
        : <String>[];
    final rawPrices = naver['prices'];
    final prices = rawPrices is List
        ? rawPrices
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList()
        : <Map<String, dynamic>>[];
    final parkingAvailable =
        naver['parking_available'];
    final priceText = _priceText(prices);
    final isOpenNow = business['is_open_now'];
    final orderableNow = business['orderable_now'];
    final currentStatusValue = business['current_status'];
    final currentStatus = currentStatusValue is Map
        ? Map<String, dynamic>.from(currentStatusValue)
        : <String, dynamic>{};
    final checkedAt =
        currentStatus['checked_at']?.toString().trim() ?? '';

    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      backgroundColor: Colors.transparent,
      builder: (sheetContext) {
        return DraggableScrollableSheet(
          initialChildSize: 0.78,
          minChildSize: 0.48,
          maxChildSize: 0.95,
          expand: false,
          builder: (context, controller) {
            return Material(
              color: Colors.white,
              borderRadius: const BorderRadius.vertical(
                top: Radius.circular(28),
              ),
              clipBehavior: Clip.antiAlias,
              child: ListView(
                controller: controller,
                padding: EdgeInsets.zero,
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(
                      16,
                      10,
                      12,
                      8,
                    ),
                    child: Row(
                      children: [
                        const Spacer(),
                        Container(
                          width: 38,
                          height: 4,
                          decoration: BoxDecoration(
                            color: const Color(0xFFD0D5DD),
                            borderRadius: BorderRadius.circular(20),
                          ),
                        ),
                        const Spacer(),
                        IconButton(
                          onPressed: () =>
                              Navigator.of(sheetContext).pop(),
                          icon: const Icon(
                            Icons.close_rounded,
                          ),
                        ),
                      ],
                    ),
                  ),
                  if (imageUrl.isNotEmpty)
                    SizedBox(
                      height: 230,
                      width: double.infinity,
                      child: Stack(
                        fit: StackFit.expand,
                        children: [
                          Image.network(
                            imageUrl,
                            fit: BoxFit.cover,
                            cacheWidth: 1000,
                            errorBuilder: (
                              context,
                              error,
                              stackTrace,
                            ) {
                              return const _BusinessImageFallback(
                                message: '사진 주소는 있지만 이미지를 불러오지 못했어요',
                                iconSize: 54,
                              );
                            },
                          ),
                          Positioned(
                            left: 16,
                            bottom: 14,
                            child: DecoratedBox(
                              decoration: BoxDecoration(
                                color: const Color(0xCC101828),
                                borderRadius: BorderRadius.circular(22),
                              ),
                              child: Padding(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 10,
                                  vertical: 6,
                                ),
                                child: Text(
                                  imageCredit,
                                  style: const TextStyle(
                                    color: Colors.white,
                                    fontSize: 11,
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    )
                  else
                    const SizedBox(
                      height: 150,
                      child: ColoredBox(
                        color: Color(0xFFEEF4FF),
                        child: Center(
                          child: Icon(
                            Icons.storefront_rounded,
                            size: 54,
                            color: Color(0xFF3157D5),
                          ),
                        ),
                      ),
                    ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(
                      20,
                      20,
                      20,
                      26,
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          name,
                          style: const TextStyle(
                            color: Color(0xFF101828),
                            fontSize: 24,
                            fontWeight: FontWeight.w900,
                            height: 1.18,
                          ),
                        ),
                        if (description.isNotEmpty) ...[
                          const SizedBox(height: 6),
                          Text(
                            description,
                            style: const TextStyle(
                              color: Color(0xFF667085),
                              fontSize: 14,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ],
                        const SizedBox(height: 18),
                        if (isOpenNow is bool)
                          _BusinessDetailRow(
                            icon: isOpenNow
                                ? Icons.store_mall_directory_rounded
                                : Icons.store_mall_directory_outlined,
                            title: '현재 상태 · KST',
                            value: [
                              isOpenNow ? '영업 중' : '영업시간 외',
                              if (orderableNow == true)
                                '영업시간 기준 주문 가능',
                              if (checkedAt.isNotEmpty)
                                '확인 $checkedAt',
                            ].join(' · '),
                          ),
                        if (openingHours.isNotEmpty)
                          _BusinessDetailRow(
                            icon: Icons.schedule_rounded,
                            title: '영업시간',
                            value: openingHours.join('\n'),
                          )
                        else
                          const _BusinessDetailRow(
                            icon: Icons.schedule_rounded,
                            title: '영업시간',
                            value: '확인되지 않음',
                            muted: true,
                          ),
                        if (address.isNotEmpty)
                          _BusinessDetailRow(
                            icon: Icons.location_on_outlined,
                            title: '주소',
                            value: address,
                          ),
                        if (phone.isNotEmpty)
                          _BusinessDetailRow(
                            icon: Icons.phone_outlined,
                            title: '전화',
                            value: phone,
                          ),
                        if (parkingAvailable != null)
                          _BusinessDetailRow(
                            icon: Icons.local_parking_outlined,
                            title: '주차',
                            value: parkingAvailable == true
                                ? '가능'
                                : '불가',
                          ),
                        if (priceText.isNotEmpty)
                          _BusinessDetailRow(
                            icon: Icons.sell_outlined,
                            title: '가격',
                            value: priceText,
                          ),
                        if (experienceCount > 0)
                          _BusinessDetailRow(
                            icon: Icons.forum_outlined,
                            title: '이용경험',
                            value: [
                              'ARABA 경험 $experienceCount건'
                                  '${verifiedExperienceCount > 0 ? ' · 이용확인 $verifiedExperienceCount건' : ''}',
                              ...experienceSnippets,
                            ].join('\n'),
                          ),
                        const SizedBox(height: 20),
                        Row(
                          children: [
                            Expanded(
                              child: OutlinedButton.icon(
                                onPressed: phone.isEmpty
                                    ? null
                                    : () => _callPhone(phone),
                                icon: const Icon(
                                  Icons.phone_rounded,
                                ),
                                label: const Text('전화'),
                                style: OutlinedButton.styleFrom(
                                  minimumSize:
                                      const Size.fromHeight(48),
                                ),
                              ),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: FilledButton.icon(
                                onPressed: placeUrl.isEmpty
                                    ? null
                                    : () => _openPlace(placeUrl),
                                icon: const Icon(
                                  Icons.map_outlined,
                                ),
                                label: const Text('카카오맵'),
                                style: FilledButton.styleFrom(
                                  minimumSize:
                                      const Size.fromHeight(48),
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 10),
                        SizedBox(
                          width: double.infinity,
                          child: OutlinedButton.icon(
                            onPressed: () =>
                                _leaveExperience(context, business),
                            icon: const Icon(
                              Icons.rate_review_outlined,
                            ),
                            label: const Text(
                              '이용 경험 남기기',
                            ),
                            style: OutlinedButton.styleFrom(
                              minimumSize:
                                  const Size.fromHeight(48),
                            ),
                          ),
                        ),
                        if (naverUrl.isNotEmpty) ...[
                          const SizedBox(height: 10),
                          SizedBox(
                            width: double.infinity,
                            child: OutlinedButton.icon(
                              onPressed: () =>
                                  _openPlace(naverUrl),
                              icon: const Icon(
                                Icons.open_in_new_rounded,
                              ),
                              label: const Text(
                                '네이버 플레이스에서 보기',
                              ),
                              style: OutlinedButton.styleFrom(
                                minimumSize:
                                    const Size.fromHeight(48),
                              ),
                            ),
                          ),
                        ],
                        if (imageGoogleMapsUri.isNotEmpty) ...[
                          const SizedBox(height: 10),
                          SizedBox(
                            width: double.infinity,
                            child: OutlinedButton.icon(
                              onPressed: () =>
                                  _openPlace(imageGoogleMapsUri),
                              icon: const Icon(
                                Icons.map_rounded,
                              ),
                              label: const Text(
                                'Google Maps에서 사진 출처 보기',
                              ),
                              style: OutlinedButton.styleFrom(
                                minimumSize:
                                    const Size.fromHeight(48),
                              ),
                            ),
                          ),
                        ],
                        if (imageAuthorUri.isNotEmpty) ...[
                          const SizedBox(height: 10),
                          SizedBox(
                            width: double.infinity,
                            child: OutlinedButton.icon(
                              onPressed: () =>
                                  _openPlace(imageAuthorUri),
                              icon: const Icon(
                                Icons.person_outline_rounded,
                              ),
                              label: Text(
                                imageAuthor.isNotEmpty
                                    ? '사진 제공자 $imageAuthor 보기'
                                    : '사진 제공자 보기',
                              ),
                              style: OutlinedButton.styleFrom(
                                minimumSize:
                                    const Size.fromHeight(48),
                              ),
                            ),
                          ),
                        ],
                        if (priceLink.isNotEmpty) ...[
                          const SizedBox(height: 10),
                          SizedBox(
                            width: double.infinity,
                            child: OutlinedButton.icon(
                              onPressed: () =>
                                  _openPlace(priceLink),
                              icon: const Icon(
                                Icons.receipt_long_outlined,
                              ),
                              label: const Text(
                                '가격 정보 출처 보기',
                              ),
                              style: OutlinedButton.styleFrom(
                                minimumSize:
                                    const Size.fromHeight(48),
                              ),
                            ),
                          ),
                        ] else if (
                          webSourceUrl.isNotEmpty ||
                          openAiSourceUrl.isNotEmpty
                        ) ...[
                          const SizedBox(height: 10),
                          SizedBox(
                            width: double.infinity,
                            child: OutlinedButton.icon(
                              onPressed: () => _openPlace(
                                  webSourceUrl.isNotEmpty
                                      ? webSourceUrl
                                      : openAiSourceUrl,
                                ),
                              icon: const Icon(
                                Icons.language_rounded,
                              ),
                              label: const Text(
                                '웹 보강 출처 보기',
                              ),
                              style: OutlinedButton.styleFrom(
                                minimumSize:
                                    const Size.fromHeight(48),
                              ),
                            ),
                          ),
                        ],
                        const SizedBox(height: 12),
                        Text(
                          cacheHit
                              ? 'ARABA DB에 축적된 정보를 우선 사용하고, 오래되거나 부족한 항목만 다시 확인합니다.'
                              : (
                                  naver['matched'] == true
                                      ? '카카오 장소정보와 네이버 플레이스를 교차확인한 업체입니다.'
                                      : '카카오 장소정보로 확인한 업체입니다.'
                                ),
                          style: const TextStyle(
                            color: Color(0xFF98A2B3),
                            fontSize: 11.5,
                            height: 1.4,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  String _won(dynamic value) {
    if (value is! num) return '';
    final digits = value.round().toString();
    final buffer = StringBuffer();

    for (var i = 0; i < digits.length; i++) {
      if (i > 0 && (digits.length - i) % 3 == 0) {
        buffer.write(',');
      }
      buffer.write(digits[i]);
    }

    return '${buffer.toString()}원';
  }

  @override
  Widget build(BuildContext context) {
    final hasMock = businesses.any(
      (item) => item['mock_total_price'] is num,
    );

    return SizedBox(
      height: hasMock ? 620 : 600,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: businesses.length,
        separatorBuilder: (context, index) =>
            const SizedBox(width: 10),
        itemBuilder: (context, index) {
          final business = businesses[index];
          final name = business['name']?.toString() ?? '업체';
          final description =
              business['description']?.toString() ?? '';
          final address =
              business['address']?.toString().trim() ?? '';
          final phone =
              business['phone']?.toString().trim() ?? '';
          final placeUrl =
              business['place_url']?.toString().trim() ?? '';
          final imageUrl =
              business['image_url']?.toString().trim() ?? '';
          final imageSource =
              business['image_source']?.toString().trim() ?? '';
          final rawImageAttributions =
              business['image_attributions'];
          final imageAttributions =
              rawImageAttributions is List
                  ? rawImageAttributions
                      .whereType<Map>()
                      .map(
                        (item) => Map<String, dynamic>.from(
                          item,
                        ),
                      )
                      .toList()
                  : <Map<String, dynamic>>[];
          final imageAuthor =
              imageAttributions.isNotEmpty
                  ? imageAttributions.first['display_name']
                          ?.toString()
                          .trim() ??
                      ''
                  : '';
          final imageCredit =
              imageSource == 'google_places_verified'
                  ? (
                      imageAuthor.isNotEmpty
                          ? 'Google Maps · $imageAuthor'
                          : 'Google Maps'
                    )
                  : (
                      imageSource == 'kakao_place'
                          ? '카카오 등록사진'
                          : (
                              imageSource == 'naver_place'
                                  ? '네이버 확인사진'
                                  : '업체 확인사진'
                            )
                    );
          final callResult =
              business['mock_call_result']?.toString().trim() ?? '';
          final cacheHit =
              business['araba_cache_hit'] == true;
          final experienceCount =
              business['experience_count'] is num
                  ? (business['experience_count'] as num).round()
                  : 0;
          final rank = business['economic_rank'];
          final totalPrice = business['mock_total_price'];
          final distance = business['distance_km'];
          final driveMinutes = business['drive_minutes'];
          final waitMinutes = business['mock_wait_minutes'];
          final workMinutes = business['mock_work_minutes'];
          final effectiveCost = business['effective_cost'];
          final stock = business['mock_stock'];
          final naverValue = business['naver'];
          final naver = naverValue is Map
              ? Map<String, dynamic>.from(naverValue)
              : <String, dynamic>{};
          final naverMatched = naver['matched'] == true;
          final naverPageChecked =
              naver['page_checked'] == true;
          final naverPageUrl =
              (
                naver['page_url'] ??
                naver['link'] ??
                naver['search_url']
              )?.toString().trim() ??
                  '';
          final rawOpeningHours = naver['opening_hours'];
          final openingHours = rawOpeningHours is List
              ? rawOpeningHours
                    .map((item) => item.toString().trim())
                    .where((item) => item.isNotEmpty)
                    .toList()
              : <String>[];
          final rawPrices = naver['prices'];
          final naverPrices = rawPrices is List
              ? rawPrices
                    .whereType<Map>()
                    .map((item) => Map<String, dynamic>.from(item))
                    .toList()
              : <Map<String, dynamic>>[];
          final parkingAvailable =
              naver['parking_available'];
          final priceLink =
              naver['price_link']?.toString().trim() ?? '';
          final webValue = business['web'];
          final web = webValue is Map
              ? Map<String, dynamic>.from(webValue)
              : <String, dynamic>{};
          final webSourcesValue = web['sources'];
          final webSources = webSourcesValue is List
              ? webSourcesValue
                  .whereType<Map>()
                  .map(
                    (item) =>
                        Map<String, dynamic>.from(item),
                  )
                  .toList()
              : <Map<String, dynamic>>[];
          final webSourceUrl = webSources.isNotEmpty
              ? webSources.first['url']
                      ?.toString()
                      .trim() ??
                  ''
              : '';
          final openAiWebValue =
              business['openai_web'];
          final openAiWeb = openAiWebValue is Map
              ? Map<String, dynamic>.from(
                  openAiWebValue,
                )
              : <String, dynamic>{};
          final rawOpenAiSources =
              openAiWeb['sources'];
          final openAiSources =
              rawOpenAiSources is List
                  ? rawOpenAiSources
                      .map(
                        (item) =>
                            item.toString().trim(),
                      )
                      .where(
                        (item) => item.isNotEmpty,
                      )
                      .toList()
                  : <String>[];
          final openAiSourceUrl =
              openAiSources.isNotEmpty
                  ? openAiSources.first
                  : '';
          final webVerified =
              openAiWeb['matched'] == true ||
              web['status'] == 'matched';
          final isOpenNow = business['is_open_now'];
          final orderableNow = business['orderable_now'];

          return GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: () => _showBusinessDetail(
              context,
              business,
            ),
            child: Container(
            width: hasMock ? 300 : 282,
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(
                color: rank == 1
                    ? const Color(0xFF7F9CF5)
                    : const Color(0xFFE4E7EC),
                width: rank == 1 ? 1.5 : 1,
              ),
              boxShadow: const [
                BoxShadow(
                  color: Color(0x0D101828),
                  blurRadius: 8,
                  offset: Offset(0, 3),
                ),
              ],
            ),
            clipBehavior: Clip.antiAlias,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  height: 146,
                  width: double.infinity,
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      if (imageUrl.isNotEmpty)
                        Image.network(
                          imageUrl,
                          fit: BoxFit.cover,
                          cacheWidth: 700,
                          errorBuilder: (
                            context,
                            error,
                            stackTrace,
                          ) {
                            return const _BusinessImageFallback(
                              message: '이미지 로딩 실패',
                              iconSize: 38,
                            );
                          },
                        )
                      else
                        const _BusinessImageFallback(
                          message: '업체 사진 정보 없음',
                          iconSize: 38,
                        ),
                      if (imageUrl.isNotEmpty)
                        Positioned(
                          left: 8,
                          bottom: 8,
                          child: DecoratedBox(
                            decoration: BoxDecoration(
                              color: const Color(0xCC101828),
                              borderRadius: BorderRadius.circular(20),
                            ),
                            child: Padding(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 8,
                                vertical: 4,
                              ),
                              child: Text(
                                imageCredit,
                                style: const TextStyle(
                                  color: Colors.white,
                                  fontSize: 10,
                                  fontWeight: FontWeight.w800,
                                ),
                              ),
                            ),
                          ),
                        ),
                      Positioned(
                        top: 8,
                        right: 8,
                        child: DecoratedBox(
                          decoration: const BoxDecoration(
                            color: Colors.white,
                            borderRadius: BorderRadius.all(
                              Radius.circular(20),
                            ),
                          ),
                          child: Padding(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 8,
                              vertical: 4,
                            ),
                            child: Text(
                              rank is num
                                  ? (
                                      totalPrice is num
                                          ? '경제성 ${rank.round()}위'
                                          : '추천 ${rank.round()}위'
                                    )
                                  : (
                                      webVerified
                                          ? '카카오+웹'
                                          : (
                                              naverMatched
                                                  ? '카카오+네이버'
                                                  : '카카오 확인'
                                            )
                                    ),
                              style: TextStyle(
                                color: rank == 1
                                    ? const Color(0xFF1939A6)
                                    : const Color(0xFF3157D5),
                                fontSize: 10.5,
                                fontWeight: FontWeight.w900,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(
                      12,
                      11,
                      12,
                      10,
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          name,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w900,
                            color: Color(0xFF101828),
                          ),
                        ),
                        if (description.isNotEmpty) ...[
                          const SizedBox(height: 4),
                          Text(
                            description,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              color: Color(0xFF667085),
                              fontSize: 11.5,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                        if (totalPrice is num) ...[
                          const SizedBox(height: 8),
                          Text(
                            '가상 최종금액 ${_won(totalPrice)}',
                            style: const TextStyle(
                              color: Color(0xFF101828),
                              fontSize: 13,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                          const SizedBox(height: 5),
                          Wrap(
                            spacing: 7,
                            runSpacing: 5,
                            children: [
                              if (stock is bool)
                                _MetricChip(
                                  icon: stock
                                      ? Icons.check_circle_outline_rounded
                                      : Icons.cancel_outlined,
                                  text: stock ? '재고 있음' : '재고 없음',
                                ),
                              if (distance is num)
                                _MetricChip(
                                  icon: Icons.route_outlined,
                                  text:
                                      '${distance.toStringAsFixed(1)}km',
                                ),
                              if (driveMinutes is num)
                                _MetricChip(
                                  icon: Icons.directions_car_outlined,
                                  text:
                                      '이동 ${driveMinutes.round()}분',
                                ),
                              if (waitMinutes is num)
                                _MetricChip(
                                  icon: Icons.schedule_outlined,
                                  text:
                                      '대기 ${waitMinutes.round()}분',
                                ),
                              if (workMinutes is num)
                                _MetricChip(
                                  icon: Icons.build_outlined,
                                  text:
                                      '작업 ${workMinutes.round()}분',
                                ),
                            ],
                          ),
                          if (effectiveCost is num) ...[
                            const SizedBox(height: 7),
                            Text(
                              '시간·이동비 포함 경제성 비용 '
                              '${_won(effectiveCost)}',
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                color: Color(0xFF3157D5),
                                fontSize: 11.5,
                                height: 1.3,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ],
                        ],
                        if (naverMatched) ...[
                          const SizedBox(height: 7),
                          Row(
                            children: [
                              Icon(
                                naverPageChecked
                                    ? Icons.verified_outlined
                                    : Icons.sync_alt_rounded,
                                size: 15,
                                color: const Color(0xFF3157D5),
                              ),
                              const SizedBox(width: 4),
                              Expanded(
                                child: Text(
                                  naverPageChecked
                                      ? '네이버 플레이스 상세페이지 확인'
                                      : '네이버 지역검색 동일 업체 확인',
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    color: Color(0xFF3157D5),
                                    fontSize: 11.2,
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ],
                        if (isOpenNow is bool) ...[
                          const SizedBox(height: 6),
                          Row(
                            children: [
                              Icon(
                                isOpenNow
                                    ? Icons.storefront_rounded
                                    : Icons.storefront_outlined,
                                size: 15,
                                color: isOpenNow
                                    ? const Color(0xFF027A48)
                                    : const Color(0xFF667085),
                              ),
                              const SizedBox(width: 4),
                              Expanded(
                                child: Text(
                                  isOpenNow
                                      ? (
                                          orderableNow == true
                                              ? '지금 영업 중 · 영업시간 기준 주문 가능'
                                              : '지금 영업 중'
                                        )
                                      : '현재 영업시간 외',
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(
                                    color: isOpenNow
                                        ? const Color(0xFF027A48)
                                        : const Color(0xFF667085),
                                    fontSize: 11.3,
                                    fontWeight: FontWeight.w900,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ],
                        const SizedBox(height: 6),
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Icon(
                              Icons.schedule_outlined,
                              size: 15,
                              color: Color(0xFF667085),
                            ),
                            const SizedBox(width: 4),
                            Expanded(
                              child: Text(
                                openingHours.isNotEmpty
                                    ? '영업시간: ${openingHours.take(2).join(' · ')}'
                                    : '영업시간: 확인되지 않음',
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                  color: openingHours.isNotEmpty
                                      ? const Color(0xFF344054)
                                      : const Color(0xFF98A2B3),
                                  fontSize: 11.3,
                                  height: 1.35,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                          ],
                        ),
                        if (naverPrices.isNotEmpty) ...[
                          const SizedBox(height: 6),
                          Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Icon(
                                Icons.sell_outlined,
                                size: 15,
                                color: Color(0xFF667085),
                              ),
                              const SizedBox(width: 4),
                              Expanded(
                                child: Text(
                                  '가격: ${naverPrices.take(2).map((item) {
                                    final name = item['name']?.toString().trim() ?? '';
                                    final price = item['price']?.toString().trim() ?? '';
                                    return name.isEmpty ? price : '$name $price';
                                  }).where((item) => item.isNotEmpty).join(' · ')}',
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    color: Color(0xFF344054),
                                    fontSize: 11.3,
                                    height: 1.35,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ],
                        if (naverPrices.isEmpty)
                          const Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Icon(
                                Icons.sell_outlined,
                                size: 15,
                                color: Color(0xFF98A2B3),
                              ),
                              SizedBox(width: 4),
                              Expanded(
                                child: Text(
                                  '가격: 확인되지 않음',
                                  style: TextStyle(
                                    color: Color(0xFF98A2B3),
                                    fontSize: 11.3,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        const SizedBox(height: 6),
                        Row(
                          children: [
                            const Icon(
                              Icons.local_parking_outlined,
                              size: 15,
                              color: Color(0xFF667085),
                            ),
                            const SizedBox(width: 4),
                            Expanded(
                              child: Text(
                                parkingAvailable == true
                                    ? '주차 가능'
                                    : (
                                        parkingAvailable == false
                                            ? '주차 불가'
                                            : '주차 정보 확인 필요'
                                      ),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                  color: parkingAvailable == null
                                      ? const Color(0xFF98A2B3)
                                      : const Color(0xFF344054),
                                  fontSize: 11.3,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                          ],
                        ),
                        if (address.isNotEmpty) ...[
                          const SizedBox(height: 7),
                          Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Icon(
                                Icons.location_on_outlined,
                                size: 15,
                                color: Color(0xFF667085),
                              ),
                              const SizedBox(width: 4),
                              Expanded(
                                child: Text(
                                  address,
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    color: Color(0xFF475467),
                                    fontSize: 11.5,
                                    height: 1.35,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ],
                        const SizedBox(height: 5),
                        Row(
                          children: [
                            const Icon(
                              Icons.phone_outlined,
                              size: 15,
                              color: Color(0xFF667085),
                            ),
                            const SizedBox(width: 4),
                            Expanded(
                              child: Text(
                                phone.isEmpty
                                    ? '공개 전화번호 없음'
                                    : phone,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(
                                  color: phone.isEmpty
                                      ? const Color(0xFF98A2B3)
                                      : const Color(0xFF344054),
                                  fontSize: 11.5,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                          ],
                        ),
                        if (callResult.isNotEmpty) ...[
                          const SizedBox(height: 6),
                          Text(
                            callResult,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              color: Color(0xFF667085),
                              fontSize: 10.5,
                              height: 1.3,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                        const Spacer(),
                        Row(
                          children: [
                            Expanded(
                              child: Text(
                                cacheHit
                                    ? 'ARABA DB 재사용'
                                        '${experienceCount > 0 ? ' · 경험 $experienceCount건' : ''}'
                                    : (
                                        webVerified
                                            ? '카카오 후보 · 웹검색 보강'
                                            : (
                                                naverMatched
                                                    ? '카카오 후보 · 네이버 교차확인'
                                                    : '카카오맵 장소검색'
                                              )
                                      ),
                                style: const TextStyle(
                                  color: Color(0xFF667085),
                                  fontSize: 10.5,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                            if (naverPageUrl.isNotEmpty)
                              TextButton(
                                onPressed: () =>
                                    _openPlace(naverPageUrl),
                                style: TextButton.styleFrom(
                                  visualDensity: VisualDensity.compact,
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 4,
                                  ),
                                ),
                                child: const Text(
                                  '네이버',
                                  style: TextStyle(
                                    fontSize: 10.5,
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                              ),
                            if (
                              priceLink.isNotEmpty ||
                              webSourceUrl.isNotEmpty ||
                              openAiSourceUrl.isNotEmpty
                            )
                              TextButton(
                                onPressed: () => _openPlace(
                                  priceLink.isNotEmpty
                                      ? priceLink
                                      : (
                                          webSourceUrl.isNotEmpty
                                              ? webSourceUrl
                                              : openAiSourceUrl
                                        ),
                                ),
                                style: TextButton.styleFrom(
                                  visualDensity: VisualDensity.compact,
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 4,
                                  ),
                                ),
                                child: Text(
                                  priceLink.isNotEmpty
                                      ? '가격표'
                                      : '웹',
                                  style: const TextStyle(
                                    fontSize: 10.5,
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                              ),
                            TextButton(
                              onPressed: placeUrl.isEmpty
                                  ? null
                                  : () => _openPlace(placeUrl),
                              style: TextButton.styleFrom(
                                visualDensity: VisualDensity.compact,
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 5,
                                ),
                              ),
                              child: const Text(
                                '카카오',
                                style: TextStyle(
                                  fontSize: 11,
                                  fontWeight: FontWeight.w800,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
          );
        },
      ),
    );
  }
}

class _BusinessDetailRow extends StatelessWidget {
  final IconData icon;
  final String title;
  final String value;
  final bool muted;

  const _BusinessDetailRow({
    required this.icon,
    required this.title,
    required this.value,
    this.muted = false,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(
        bottom: 16,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            icon,
            size: 21,
            color: muted
                ? const Color(0xFF98A2B3)
                : const Color(0xFF475467),
          ),
          const SizedBox(width: 12),
          SizedBox(
            width: 68,
            child: Text(
              title,
              style: TextStyle(
                color: muted
                    ? const Color(0xFF98A2B3)
                    : const Color(0xFF475467),
                fontSize: 13,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: TextStyle(
                color: muted
                    ? const Color(0xFF98A2B3)
                    : const Color(0xFF101828),
                fontSize: 13.5,
                height: 1.45,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _MetricChip extends StatelessWidget {
  final IconData icon;
  final String text;

  const _MetricChip({
    required this.icon,
    required this.text,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: 7,
        vertical: 4,
      ),
      decoration: BoxDecoration(
        color: const Color(0xFFF2F4F7),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            icon,
            size: 12,
            color: const Color(0xFF667085),
          ),
          const SizedBox(width: 4),
          Text(
            text,
            style: const TextStyle(
              color: Color(0xFF475467),
              fontSize: 10.5,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

class _ActionCard extends StatelessWidget {
  final String question;
  final List<String> actions;
  final ValueChanged<String> onSelected;

  const _ActionCard({
    required this.question,
    required this.actions,
    required this.onSelected,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFF9FAFB),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: const Color(0xFFE4E7EC),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            question,
            style: const TextStyle(
              color: Color(0xFF101828),
              fontSize: 14,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final action in actions)
                FilledButton.tonal(
                  onPressed: () => onSelected(action),
                  child: Text(action),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _ClarificationCard extends StatelessWidget {
  final String question;
  final List<String> options;
  final ValueChanged<String> onSelected;

  const _ClarificationCard({
    required this.question,
    required this.options,
    required this.onSelected,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFEEF4FF),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: const Color(0xFFD6E4FF),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            question,
            style: const TextStyle(
              color: Color(0xFF1939A6),
              fontSize: 14,
              fontWeight: FontWeight.w800,
              height: 1.35,
            ),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final option in options)
                OutlinedButton(
                  onPressed: () => onSelected(option),
                  style: OutlinedButton.styleFrom(
                    backgroundColor: Colors.white,
                    foregroundColor: const Color(0xFF3157D5),
                    side: const BorderSide(
                      color: Color(0xFF9DB7FF),
                    ),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(20),
                    ),
                  ),
                  child: Text(option),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _InlineStatusText extends StatefulWidget {
  final String text;

  const _InlineStatusText({
    required this.text,
  });

  @override
  State<_InlineStatusText> createState() =>
      _InlineStatusTextState();
}

class _InlineStatusTextState
    extends State<_InlineStatusText>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _opacity;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(
        milliseconds: 650,
      ),
    );
    _opacity = Tween<double>(
      begin: 0.35,
      end: 1.0,
    ).animate(
      CurvedAnimation(
        parent: _controller,
        curve: Curves.easeInOut,
      ),
    );
    _controller.repeat(
      reverse: true,
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _opacity,
      child: Padding(
        padding: const EdgeInsets.only(
          left: 43,
          right: 34,
          bottom: 12,
        ),
        child: Text(
          widget.text,
          style: const TextStyle(
            color: Color(0xFF667085),
            fontSize: 13,
            height: 1.35,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}
class _LivePanel extends StatelessWidget {
  final String status;
  final bool active;

  const _LivePanel({
    required this.status,
    required this.active,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(12, 0, 12, 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF101828),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          Icon(
            active
                ? Icons.graphic_eq_rounded
                : Icons.sync_rounded,
            size: 18,
            color: Colors.white,
          ),
          const SizedBox(width: 7),
          Expanded(
            child: Text(
              'GPT-Live · $status',
              style: const TextStyle(
                color: Colors.white,
                fontSize: 13,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
          const Text(
            '대화는 채팅에 기록',
            style: TextStyle(
              color: Color(0xFF98A2B3),
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  final TextEditingController controller;
  final FocusNode focusNode;
  final bool listening;
  final bool sending;
  final bool micDisabled;
  final VoidCallback onImage;
  final VoidCallback onMic;
  final VoidCallback onSend;

  const _Composer({
    required this.controller,
    required this.focusNode,
    required this.listening,
    required this.sending,
    required this.micDisabled,
    required this.onImage,
    required this.onMic,
    required this.onSend,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(
          top: BorderSide(
            color: Color(0xFFEAECF0),
          ),
        ),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          IconButton(
            tooltip: '사진으로 정보 보내기',
            onPressed: sending ? null : onImage,
            icon: const Icon(
              Icons.add_a_photo_outlined,
              color: Color(0xFF475467),
            ),
          ),
          IconButton(
            tooltip: listening
                ? '음성 입력 중지'
                : '음성으로 말하기',
            onPressed:
                micDisabled ? null : onMic,
            icon: Icon(
              listening
                  ? Icons.mic_rounded
                  : Icons.mic_none_rounded,
              color: listening
                  ? const Color(0xFFD92D20)
                  : const Color(0xFF475467),
            ),
          ),
          Expanded(
            child: Container(
              padding: const EdgeInsets.symmetric(
                horizontal: 14,
              ),
              decoration: BoxDecoration(
                color: const Color(0xFFF2F4F7),
                borderRadius: BorderRadius.circular(22),
              ),
              child: TextField(
                controller: controller,
                focusNode: focusNode,
                enabled: !sending,
                minLines: 1,
                maxLines: 5,
                decoration: const InputDecoration(
                  hintText: '알아볼 내용을 입력하세요',
                  hintStyle: TextStyle(
                    color: Color(0xFF98A2B3),
                  ),
                  border: InputBorder.none,
                ),
              ),
            ),
          ),
          const SizedBox(width: 8),
          FilledButton(
            onPressed: sending ? null : onSend,
            style: FilledButton.styleFrom(
              minimumSize: const Size(54, 44),
              padding: const EdgeInsets.symmetric(
                horizontal: 14,
              ),
            ),
            child: sending
                ? const SizedBox(
                    width: 17,
                    height: 17,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white,
                    ),
                  )
                : const Text('보내기'),
          ),
        ],
      ),
    );
  }
}
