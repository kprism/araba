import 'dart:async';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../services/api_key_store.dart';
import '../../services/araba_api.dart';
import '../../services/conversation_context.dart';
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
  final _naverStore = NaverCredentialStore();
  final _voicePreferenceStore = VoicePreferenceStore();
  final _conversationContext = ConversationContext();

  LiveVoiceService? _liveVoice;
  bool _keepLiveVoice = false;
  bool _liveNeedsReconnect = false;
  bool _appInForeground = true;
  bool _autoReconnectingLive = false;
  List<Map<String, dynamic>> _lastBusinesses = const [];

  final List<_Message> _messages = [
    _Message(
      isUser: false,
      text: '무엇을 알아볼까요? 말하듯이 편하게 적어주세요.',
    ),
  ];

  bool _liveConnecting = false;
  bool _liveActive = false;
  bool _sending = false;
  bool _researching = false;
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
      unawaited(live.resumeAudio());
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

    if (current != null &&
        (_liveActive ||
            _liveConnecting ||
            current.isStarted)) {
      _keepLiveVoice = false;
      _liveNeedsReconnect = false;

      setState(() {
        _liveConnecting = false;
        _liveActive = false;
        _liveStatus = '종료 중';
      });

      await current.stop();
      _liveVoice = null;

      if (mounted) {
        setState(() => _liveStatus = '종료됨');
      }
      return;
    }

    if (current != null) {
      try {
        await current.stop(force: true);
      } catch (_) {}
      _liveVoice = null;
    }

    _keepLiveVoice = true;
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
            _liveStatus = status;
            _liveActive = liveVoice.isStarted;
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
        onMission: (mission, requestContext) {
          if (!mounted || _liveVoice != liveVoice) return;

          final clarifications = _clarifications(mission);

          if (clarifications.isNotEmpty) {
            setState(() {
              _messages.add(
                _Message(
                  isUser: false,
                  text: _reply(mission),
                  mission: mission,
                  requestContext: requestContext,
                ),
              );
            });
            _toBottom();
            return;
          }

          unawaited(_runRealResearch(mission));
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
    } catch (caught) {
      _liveVoice = null;

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

  void _updateResearchStage(String stage) {
    if (!mounted || !_researching) return;
    setState(() => _researchStage = stage);
    _toBottom();
  }

  void _stopResearchProgress() {
    if (!mounted) return;

    setState(() {
      _researching = false;
      _researchStage = '';
    });
  }

  Future<void> _runRealResearch(
    Map<String, dynamic> mission,
  ) async {
    if (_researching) return;

    _startResearchProgress();

    try {
      final kakaoRestApiKey = await _kakaoStore.read();

      if (kakaoRestApiKey == null) {
        throw const ArabaApiException(
          'MY의 관리자 API 설정에서 Kakao REST API Key를 먼저 등록해주세요.',
        );
      }

      final naverCredentials = await _naverStore.read();

      _updateResearchStage(
        naverCredentials == null
            ? '상점 찾는 중…'
            : '상점 찾고 네이버 정보 확인하는 중…',
      );

      final result = await _api.searchBusinesses(
        mission,
        kakaoRestApiKey: kakaoRestApiKey,
        naverClientId: naverCredentials?.clientId,
        naverClientSecret: naverCredentials?.clientSecret,
      );
      final businesses = _businessesFrom(result);
      final searchQuery =
          result['search_query']?.toString().trim() ?? '';

      if (businesses.length == 1) {
        _conversationContext.rememberBusiness(
          businesses.first,
        );
      }
      _lastBusinesses = businesses;

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

      _updateResearchStage(
        naverConfigured
            ? '영업시간·가격 등 상세정보 확인하는 중…'
            : '결과 정리하는 중…',
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
        );
        _speakProgress(detail);
        return;
      }

      final sourceSummary = naverConfigured
          ? '카카오맵에서 관련 업체 ${businesses.length}곳을 찾고, '
              '네이버에서 $naverMatched곳을 같은 업체로 교차확인했어요. '
              '그중 $naverPageChecked곳은 네이버 상세페이지까지 확인했습니다.'
          : '카카오맵에서 관련 업체 ${businesses.length}곳을 찾았어요. '
              'MY에 Naver Search API 정보를 등록하면 '
              '네이버 플레이스까지 2차 교차확인합니다.';

      final searchDetail = searchQuery.isEmpty
          ? ''
          : '\n\n검색 기준: $searchQuery';

      _addAssistantMessage(
        text: '$sourceSummary$searchDetail',
        badge: naverConfigured
            ? '카카오 + 네이버 검증'
            : '카카오 검증',
        businesses: businesses,
      );
      _speakProgress(sourceSummary);
    } catch (error) {
      final message = error is ArabaApiException
          ? error.message
          : '실제 업체 조사 중 문제가 생겼어요.';

      _addAssistantMessage(
        text: message,
        badge: '조사 오류',
      );
    } finally {
      _stopResearchProgress();
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
          final options = item['options'];
          return question.isNotEmpty && options is List && options.isNotEmpty;
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
      return summary.isEmpty
          ? '한 가지만 더 알려주세요.'
          : '$summary\n\n한 가지만 더 알려주세요.';
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
    if (_researching) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('현재 알아보는 작업을 진행하고 있어요.'),
        ),
      );
      return;
    }

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

  Future<void> _requestMission({
    required String displayText,
    required String requestText,
  }) async {
    if (_sending || _researching) return;

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
      final result = await _api.createMission(
        contextualRequest,
        apiKey: apiKey,
      );

      if (!mounted) return;

      final mission = result['mission'];
      if (mission is! Map<String, dynamic>) {
        throw const ArabaApiException(
          '서버 응답 형식이 올바르지 않아요.',
        );
      }

      _conversationContext.rememberMission(mission);
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
      } else if (
          responseMode == 'research' ||
          mission['ready_to_research'] == true) {
        setState(() => _sending = false);
        await _runRealResearch(mission);
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
    } catch (error) {
      if (!mounted) return;

      final message = error is ArabaApiException
          ? error.message
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
          Container(
            margin: const EdgeInsets.only(right: 16),
            padding: const EdgeInsets.symmetric(
              horizontal: 11,
              vertical: 6,
            ),
            decoration: BoxDecoration(
              color: const Color(0xFFEEF4FF),
              borderRadius: BorderRadius.circular(30),
            ),
            child: const Text(
              'POC',
              style: TextStyle(
                color: Color(0xFF3157D5),
                fontSize: 12,
                fontWeight: FontWeight.w800,
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
                  listening: _liveActive,
                  sending:
                      _sending || _liveConnecting || _researching,
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
  final String? badge;
  final List<Map<String, dynamic>>? businesses;
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

  const _AssistantBubble({
    required this.message,
    required this.onClarification,
    required this.onAction,
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
                ],
              ),
            ),
          ],
        ),
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

class _BusinessCards extends StatelessWidget {
  final List<Map<String, dynamic>> businesses;

  const _BusinessCards({
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
      height: hasMock ? 472 : 454,
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
          final callResult =
              business['mock_call_result']?.toString().trim() ?? '';
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
              (naver['page_url'] ?? naver['link'])
                      ?.toString()
                      .trim() ??
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

          return Container(
            width: hasMock ? 286 : 258,
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
                  height: 118,
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
                            return const ColoredBox(
                              color: Color(0xFFEEF4FF),
                              child: Center(
                                child: Icon(
                                  Icons.storefront_rounded,
                                  size: 38,
                                  color: Color(0xFF3157D5),
                                ),
                              ),
                            );
                          },
                        )
                      else
                        const ColoredBox(
                          color: Color(0xFFEEF4FF),
                          child: Center(
                            child: Icon(
                              Icons.storefront_rounded,
                              size: 38,
                              color: Color(0xFF3157D5),
                            ),
                          ),
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
                                imageSource == 'kakao_place'
                                    ? '카카오 등록사진'
                                    : (
                                        imageSource == 'naver_place'
                                            ? '네이버 플레이스 사진'
                                            : '업체 사진'
                                      ),
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
                                      naverMatched
                                          ? '카카오+네이버'
                                          : '카카오 확인'
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
                        if (openingHours.isNotEmpty) ...[
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
                                  '영업시간: ${openingHours.take(2).join(' · ')}',
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
                                naverMatched
                                    ? '카카오 후보 · 네이버 교차확인'
                                    : '카카오맵 장소검색',
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
                                    horizontal: 5,
                                  ),
                                ),
                                child: const Text(
                                  '네이버',
                                  style: TextStyle(
                                    fontSize: 11,
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
          );
        },
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

class _InlineStatusText extends StatelessWidget {
  final String text;

  const _InlineStatusText({
    required this.text,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(
        left: 43,
        right: 34,
        bottom: 12,
      ),
      child: Text(
        text,
        style: const TextStyle(
          color: Color(0xFF667085),
          fontSize: 13,
          height: 1.35,
          fontWeight: FontWeight.w500,
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
  final VoidCallback onImage;
  final VoidCallback onMic;
  final VoidCallback onSend;

  const _Composer({
    required this.controller,
    required this.focusNode,
    required this.listening,
    required this.sending,
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
            onPressed: sending ? null : onMic,
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
