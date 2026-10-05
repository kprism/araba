import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../services/api_key_store.dart';
import '../../services/araba_api.dart';
import '../../services/conversation_context.dart';
import '../../services/kakao_credential_store.dart';
import '../../services/live_voice_service.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _controller = TextEditingController();
  final _scroll = ScrollController();
  final _focus = FocusNode();
  final _api = ArabaApi();
  final _keyStore = ApiKeyStore();
  final _kakaoStore = KakaoCredentialStore();
  final _conversationContext = ConversationContext();

  LiveVoiceService? _liveVoice;
  Timer? _researchTipTimer;

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
  bool _showResearchTips = false;
  bool _userBrowsingHistory = false;
  String _liveStatus = '';
  String _researchStage = '';
  List<String> _researchTips = const [];
  int _researchTipIndex = 0;
  String? _liveTranscriptSpeaker;
  int? _liveTranscriptMessageIndex;

  Future<void> _toggleLiveVoice() async {
    final current = _liveVoice;

    if (current != null) {
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

    try {
      final apiKey = await _keyStore.read();

      if (apiKey == null) {
        throw const ArabaApiException(
          'MY에서 OpenAI API Key를 먼저 저장해주세요.',
        );
      }

      if (!mounted) return;

      setState(() {
        _liveConnecting = true;
        _liveActive = false;
        _liveStatus = 'GPT-Live 연결 중';
      });

      late final LiveVoiceService liveVoice;
      liveVoice = LiveVoiceService(
        api: _api,
        apiKey: apiKey,
        conversationContext: _conversationContext,
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

          setState(() {
            _liveConnecting = false;
            _liveActive = false;
            _liveStatus = '연결 오류';
          });

          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(message)),
          );
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

      setState(() {
        _liveConnecting = false;
        _liveActive = false;
        _liveStatus = '연결 실패';
      });

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(message)),
      );
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

  List<String> _researchTipsFor(
    Map<String, dynamic> mission,
  ) {
    final category =
        mission['category']?.toString().trim() ?? '';
    final subject =
        mission['subject']?.toString().toLowerCase() ?? '';

    if (category == '자동차' && subject.contains('타이어')) {
      return const [
        '타이어는 같은 규격이라도 제조주차에 따라 가격과 선호도가 달라질 수 있어요.',
        '견적을 비교할 때 장착비, 휠밸런스, 폐타이어 처리비 포함 여부를 같이 보세요.',
        '앞 타이어 2개만 교체할 때는 좌우 같은 모델과 규격으로 맞추는 게 기본입니다.',
        '가장 싼 가격만 보기보다 재고와 당일 장착 가능 시간까지 같이 확인하면 헛걸음을 줄일 수 있어요.',
      ];
    }

    if (category == '자동차') {
      return const [
        '정비 견적은 부품값과 공임이 따로 표시되는지 확인하면 비교가 쉬워요.',
        '방문 전 재고와 당일 작업 가능 시간을 확인하면 대기 시간을 줄일 수 있어요.',
        '같은 작업도 차량 모델과 부품 등급에 따라 실제 결제금액이 달라질 수 있어요.',
      ];
    }

    return const [
      '검색 중에는 표시 가격보다 추가비용과 실제 이용 가능 여부를 함께 확인하고 있어요.',
      '후기보다 영업시간, 재고, 예약 가능 여부처럼 자주 바뀌는 정보를 우선 확인하는 게 좋아요.',
      '후보가 너무 적으면 가까운 상위 지역까지 자동으로 범위를 넓혀 다시 찾아볼게요.',
    ];
  }

  String get _currentResearchTip {
    if (_researchTips.isEmpty) return '';
    return _researchTips[
      _researchTipIndex % _researchTips.length
    ];
  }

  void _startResearchProgress(
    Map<String, dynamic> mission,
  ) {
    _researchTipTimer?.cancel();
    final tips = _researchTipsFor(mission);

    setState(() {
      _researching = true;
      _showResearchTips = true;
      _researchStage = '실제 업체를 빠르게 찾는 중';
      _researchTips = tips;
      _researchTipIndex = 0;
    });

    _researchTipTimer = Timer.periodic(
      const Duration(seconds: 3),
      (_) {
        if (!mounted ||
            !_researching ||
            _researchTips.length < 2) {
          return;
        }

        setState(() {
          _researchTipIndex =
              (_researchTipIndex + 1) % _researchTips.length;
        });
      },
    );
  }

  void _updateResearchStage(String stage) {
    if (!mounted || !_researching) return;
    setState(() => _researchStage = stage);
  }

  void _stopResearchProgress() {
    _researchTipTimer?.cancel();
    _researchTipTimer = null;

    if (!mounted) return;

    setState(() {
      _researching = false;
      _showResearchTips = false;
      _researchStage = '';
      _researchTips = const [];
      _researchTipIndex = 0;
    });
  }

  void _dismissResearchTips() {
    if (!mounted) return;
    setState(() => _showResearchTips = false);
  }

  Future<void> _runRealResearch(
    Map<String, dynamic> mission,
  ) async {
    if (_researching) return;

    _startResearchProgress(mission);

    const startText =
        '조건 정리가 끝났어요. 실제 업체를 빠르게 찾고 있어요.';
    _addAssistantMessage(
      text: startText,
      badge: '실제 검색 중',
    );
    _speakProgress(
      '조건 정리가 끝났어요. 실제 업체를 바로 찾아볼게요.',
    );

    try {
      final kakaoRestApiKey = await _kakaoStore.read();

      if (kakaoRestApiKey == null) {
        throw const ArabaApiException(
          'MY의 관리자 API 설정에서 Kakao REST API Key를 먼저 등록해주세요.',
        );
      }

      _updateResearchStage('카카오맵에서 관련 업체만 검색 중');

      final result = await _api.searchBusinesses(
        mission,
        kakaoRestApiKey: kakaoRestApiKey,
      );
      final businesses = _businessesFrom(result);
      final searchQuery =
          result['search_query']?.toString().trim() ?? '';

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

      _updateResearchStage(
        '${businesses.length}곳 확인 · 가상 통화 준비 중',
      );

      _addAssistantMessage(
        text: searchQuery.isEmpty
            ? '${businesses.length}곳의 실제 관련 업체를 찾았어요.'
            : '카카오맵에서 “$searchQuery”로 관련 업체 '
                '${businesses.length}곳을 찾았어요.',
        badge: '실제 관련 업체',
        businesses: businesses,
      );

      _updateResearchStage(
        '가상 통화로 가격·재고·대기시간 확인 중',
      );

      const callText =
          '이제 실제 업체 목록을 대상으로 가상 통화를 돌려서 '
          '최종 결제금액, 재고, 대기시간, 작업시간을 같은 기준으로 비교할게요.';
      _speakProgress(callText);

      final originValue = result['reference_origin'];
      final origin = originValue is Map
          ? Map<String, dynamic>.from(originValue)
          : null;

      final mockResult = await _api.simulateMockCalls(
        mission,
        businesses,
        origin: origin,
      );
      final calledBusinesses = _businessesFrom(mockResult);
      final recommendation = mockResult['recommendation'];

      if (calledBusinesses.isEmpty ||
          recommendation is! Map) {
        throw const ArabaApiException(
          '가상 통화 비교 결과 형식이 올바르지 않아요.',
        );
      }

      _updateResearchStage(
        '가격·거리·시간까지 경제성 비교 중',
      );

      _addAssistantMessage(
        text: '가상 통화를 마쳤어요. 실제 업체별로 같은 질문을 했다고 가정해 '
            '가격, 재고, 대기시간과 작업시간을 비교했습니다.',
        badge: '가상 통화 비교',
        businesses: calledBusinesses,
      );

      final name =
          recommendation['name']?.toString().trim() ?? '1순위 업체';
      final price =
          recommendation['mock_total_price'];
      final distance =
          recommendation['distance_km'];
      final driveMinutes =
          recommendation['drive_minutes'];
      final totalTimeMinutes =
          recommendation['total_time_minutes'];
      final effective =
          recommendation['effective_cost'];
      final reason =
          recommendation['reason']?.toString().trim() ?? '';
      final basis =
          mockResult['basis']?.toString().trim() ?? '';

      String won(dynamic value) {
        if (value is! num) return '-';
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

      final distanceText = distance is num
          ? '${distance.toStringAsFixed(1)}km'
          : '거리 추정 없음';
      final driveText = driveMinutes is num
          ? '약 ${driveMinutes.round()}분'
          : '이동시간 추정 없음';
      final totalTimeText = totalTimeMinutes is num
          ? '왕복 이동·대기·작업 포함 약 ${totalTimeMinutes.round()}분'
          : '총 소요시간 추정 없음';

      final summary =
          '가상 통화 기준 경제성 1순위는 $name입니다. '
          '총 결제금액 ${won(price)}, 이동거리 $distanceText, '
          '편도 차량 이동 $driveText, $totalTimeText이며, '
          '실제 지출과 시간비용까지 반영한 경제성 비용은 '
          '${won(effective)}입니다.'
          '${reason.isEmpty ? '' : '\n\n$reason'}'
          '${basis.isEmpty ? '' : '\n\n기준: $basis'}';

      _addAssistantMessage(
        text: summary,
        badge: '경제성 1순위 · 가상 테스트',
        businesses: calledBusinesses,
        actionQuestion: '이 비교에서 다른 후보의 상세 조건도 볼까요?',
        actions: const [
          '다른 후보 보기',
          '여기까지',
        ],
      );
      _speakProgress(summary);
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

    if (action == '예약하기') {
      setState(() => _researching = true);

      const calling =
          '추천 업체에 예약 전화를 걸고 있어요. 지금은 가상 통화로 진행합니다.';
      _addAssistantMessage(
        text: calling,
        badge: '가상 예약',
      );
      _speakProgress(calling);

      await Future<void>.delayed(
        const Duration(milliseconds: 1400),
      );

      const done =
          '가상 예약 시뮬레이션이 완료됐어요. 실제 예약은 아직 이루어지지 않았습니다. '
          '다음 단계에서 실제 예약 성공 시 ARABA 일정에 자동 등록하고 사전 알림까지 연결할게요.';
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
    final clarifications = _clarifications(mission);

    if (clarifications.isNotEmpty) {
      return summary.isEmpty
          ? '알아보기 전에 한 가지만 더 알려주세요.'
          : '$summary\n\n알아보기 전에 한 가지만 더 알려주세요.';
    }

    return summary.isEmpty ? '요청을 이해했어요.' : summary;
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

      if (clarifications.isNotEmpty) {
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
      } else if (mission['ready_to_research'] == true) {
        unawaited(_runRealResearch(mission));
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
    _researchTipTimer?.cancel();
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
                      itemCount:
                          _messages.length + (_sending ? 1 : 0),
                      itemBuilder: (context, index) {
                        if (index == _messages.length) {
                          return const _ThinkingBubble();
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
                  onMic: _toggleLiveVoice,
                  onSend: _send,
                ),
                  ],
                ),
                if (_researching &&
                    _showResearchTips &&
                    _researchTips.isNotEmpty)
                  Positioned(
                    left: 14,
                    right: 14,
                    bottom:
                        (_liveConnecting || _liveActive) ? 138 : 76,
                    child: _ResearchTipPopup(
                      stage: _researchStage,
                      tip: _currentResearchTip,
                      onClose: _dismissResearchTips,
                    ),
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
      height: hasMock ? 392 : 306,
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
                Container(
                  height: 74,
                  width: double.infinity,
                  color: const Color(0xFFEEF4FF),
                  child: Stack(
                    children: [
                      const Center(
                        child: Icon(
                          Icons.storefront_rounded,
                          size: 36,
                          color: Color(0xFF3157D5),
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
                                  ? '경제성 ${rank.round()}위'
                                  : '실제 업체',
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
                            const Expanded(
                              child: Text(
                                '카카오맵 장소검색',
                                style: TextStyle(
                                  color: Color(0xFF667085),
                                  fontSize: 10.5,
                                  fontWeight: FontWeight.w700,
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
                                  horizontal: 7,
                                ),
                              ),
                              child: const Text(
                                '지도 보기',
                                style: TextStyle(
                                  fontSize: 11.5,
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

class _ThinkingBubble extends StatelessWidget {
  const _ThinkingBubble();

  @override
  Widget build(BuildContext context) {
    return const Align(
      alignment: Alignment.centerLeft,
      child: Padding(
        padding: EdgeInsets.only(
          left: 43,
          right: 34,
          bottom: 14,
        ),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.all(
              Radius.circular(18),
            ),
          ),
          child: Padding(
            padding: EdgeInsets.symmetric(
              horizontal: 16,
              vertical: 12,
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                  ),
                ),
                SizedBox(width: 9),
                Text(
                  '요청을 정리하고 있어요…',
                  style: TextStyle(
                    color: Color(0xFF667085),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ResearchTipPopup extends StatelessWidget {
  final String stage;
  final String tip;
  final VoidCallback onClose;

  const _ResearchTipPopup({
    required this.stage,
    required this.tip,
    required this.onClose,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 10),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(
        color: const Color(0xFFF0F5FF),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: const Color(0xFFB7CCFF),
        ),
        boxShadow: const [
          BoxShadow(
            color: Color(0x1A3157D5),
            blurRadius: 14,
            offset: Offset(0, 5),
          ),
        ],
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(
            width: 20,
            height: 20,
            child: CircularProgressIndicator(
              strokeWidth: 2.4,
            ),
          ),
          const SizedBox(width: 11),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        stage,
                        style: const TextStyle(
                          color: Color(0xFF1939A6),
                          fontSize: 13,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: '닫기',
                      visualDensity: VisualDensity.compact,
                      onPressed: onClose,
                      icon: const Icon(
                        Icons.close_rounded,
                        size: 19,
                        color: Color(0xFF667085),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                const Text(
                  '기다리는 동안 알아두면 좋아요',
                  style: TextStyle(
                    color: Color(0xFF667085),
                    fontSize: 11,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 3),
                AnimatedSwitcher(
                  duration: Duration(milliseconds: 250),
                  child: Text(
                    tip,
                    key: ValueKey(tip),
                    style: const TextStyle(
                      color: Color(0xFF344054),
                      fontSize: 12.5,
                      height: 1.4,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
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
  final VoidCallback onMic;
  final VoidCallback onSend;

  const _Composer({
    required this.controller,
    required this.focusNode,
    required this.listening,
    required this.sending,
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
