import 'package:flutter/material.dart';

import '../../services/api_key_store.dart';
import '../../services/araba_api.dart';
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

  LiveVoiceService? _liveVoice;

  final List<_Message> _messages = [
    const _Message(
      isUser: false,
      text: '무엇을 알아볼까요? 말하듯이 편하게 적어주세요.',
    ),
  ];

  bool _liveConnecting = false;
  bool _liveActive = false;
  bool _sending = false;
  bool _researching = false;
  String _liveStatus = '';
  String _liveUserTranscript = '';
  String _liveAssistantTranscript = '';
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
        _liveUserTranscript = '';
        _liveAssistantTranscript = '';
      });

      late final LiveVoiceService liveVoice;
      liveVoice = LiveVoiceService(
        api: _api,
        apiKey: apiKey,
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
            if (isUser) {
              _liveUserTranscript += delta;
            } else {
              _liveAssistantTranscript += delta;
            }
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

          unawaited(_runResearchSimulation(mission));
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
          isLiveTranscript: true,
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

  Future<void> _runResearchSimulation(
    Map<String, dynamic> mission,
  ) async {
    if (_researching) return;

    setState(() => _researching = true);

    const startText = '조건 정리가 끝났어요. 업체를 찾고 있어요. 현재 0곳 찾았어요.';
    _addAssistantMessage(
      text: startText,
      badge: '조사 중',
    );
    _speakProgress('조건 정리가 끝났어요. 바로 업체를 찾아볼게요.');

    try {
      final result = await _api.simulateResearch(mission);
      final businesses = _businessesFrom(result);

      await Future<void>.delayed(
        const Duration(milliseconds: 650),
      );

      _addAssistantMessage(
        text: '${businesses.length}곳 찾았어요. 비교할 후보를 카드로 보여드릴게요.',
        badge: '가상 테스트',
        businesses: businesses,
      );
      _speakProgress(
        '${businesses.length}곳을 찾았어요. 조건을 비교하고 있습니다.',
      );

      final lifeInfo = result['life_info'];
      if (lifeInfo is List) {
        for (final item in lifeInfo.take(2)) {
          final tip = item.toString().trim();
          if (tip.isEmpty) continue;

          await Future<void>.delayed(
            const Duration(milliseconds: 750),
          );
          _addAssistantMessage(
            text: tip,
            badge: '알아두면 좋아요',
          );
        }
      }

      await Future<void>.delayed(
        const Duration(milliseconds: 700),
      );

      const callText =
          '이 업체들에 전화해서 가격, 가능 여부 같은 최신 정보를 확인할게요. '
          '지금은 실제 전화 대신 가상 통화로 테스트합니다.';
      _addAssistantMessage(
        text: callText,
        badge: '전화 확인',
      );
      _speakProgress(callText);

      await Future<void>.delayed(
        const Duration(milliseconds: 1200),
      );

      _addAssistantMessage(
        text: '가상 전화 확인을 마쳤어요. 각 업체 카드에 통화 확인 결과를 표시했어요.',
        badge: '통화 결과',
        businesses: businesses,
      );
      _speakProgress('가상 전화 확인을 마쳤어요. 이제 가장 적합한 곳을 추천할게요.');

      final recommendation = result['recommendation'];
      final recommendationMap = recommendation is Map
          ? Map<String, dynamic>.from(recommendation)
          : <String, dynamic>{};
      final summary =
          recommendationMap['summary']?.toString().trim() ??
          '비교가 끝났어요.';
      final finalQuestion =
          result['final_question']?.toString().trim() ??
          '이 업체로 진행할까요?';
      final rawActions = result['actions'];
      final actions = rawActions is List
          ? rawActions
                .map((item) => item.toString())
                .where((item) => item.trim().isNotEmpty)
                .toList()
          : <String>[];

      await Future<void>.delayed(
        const Duration(milliseconds: 650),
      );

      _addAssistantMessage(
        text: summary,
        badge: '추천',
        businesses: businesses.take(1).toList(),
        actionQuestion: finalQuestion,
        actions: actions,
      );
      _speakProgress('$summary $finalQuestion');
    } catch (error) {
      final message = error is ArabaApiException
          ? error.message
          : '조사 시뮬레이션 중 문제가 생겼어요.';

      _addAssistantMessage(
        text: message,
        badge: '오류',
      );
    } finally {
      if (mounted) {
        setState(() => _researching = false);
      }
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

  void _toBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 240),
        curve: Curves.easeOut,
      );
    });
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
    final text = _controller.text.trim();

    if (text.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('알아볼 내용을 입력해주세요.')),
      );
      return;
    }

    _controller.clear();
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

      final result = await _api.createMission(
        requestText,
        apiKey: apiKey,
      );

      if (!mounted) return;

      final mission = result['mission'];
      if (mission is! Map<String, dynamic>) {
        throw const ArabaApiException(
          '서버 응답 형식이 올바르지 않아요.',
        );
      }

      setState(() {
        _messages.add(
          _Message(
            isUser: false,
            text: _reply(mission),
            mission: mission,
            requestContext: requestText,
          ),
        );
      });
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
            child: Column(
              children: [
                Expanded(
                  child: ListView.builder(
                    controller: _scroll,
                    padding: const EdgeInsets.fromLTRB(
                      16,
                      22,
                      16,
                      18,
                    ),
                    itemCount: _messages.length + (_sending ? 1 : 0),
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
                      );
                    },
                  ),
                ),
                if (_liveConnecting ||
                    _liveActive ||
                    _liveUserTranscript.isNotEmpty ||
                    _liveAssistantTranscript.isNotEmpty)
                  _LivePanel(
                    status: _liveStatus,
                    active: _liveActive,
                    userTranscript: _liveUserTranscript,
                    assistantTranscript: _liveAssistantTranscript,
                  ),
                _Composer(
                  controller: _controller,
                  focusNode: _focus,
                  listening: _liveActive,
                  sending: _sending || _liveConnecting,
                  onMic: _toggleLiveVoice,
                  onSend: _send,
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
  final String text;
  final Map<String, dynamic>? mission;
  final String? requestContext;
  final bool isError;

  const _Message({
    required this.isUser,
    required this.text,
    this.mission,
    this.requestContext,
    this.isError = false,
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

  const _AssistantBubble({
    required this.message,
    required this.onClarification,
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
                ],
              ),
            ),
          ],
        ),
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

class _LivePanel extends StatelessWidget {
  final String status;
  final bool active;
  final String userTranscript;
  final String assistantTranscript;

  const _LivePanel({
    required this.status,
    required this.active,
    required this.userTranscript,
    required this.assistantTranscript,
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
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                active
                    ? Icons.graphic_eq_rounded
                    : Icons.sync_rounded,
                size: 18,
                color: Colors.white,
              ),
              const SizedBox(width: 7),
              Text(
                'GPT-Live · $status',
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 13,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ],
          ),
          if (userTranscript.trim().isNotEmpty) ...[
            const SizedBox(height: 9),
            Text(
              '나  $userTranscript',
              style: const TextStyle(
                color: Color(0xFFD0D5DD),
                fontSize: 13,
                height: 1.35,
              ),
            ),
          ],
          if (assistantTranscript.trim().isNotEmpty) ...[
            const SizedBox(height: 5),
            Text(
              'ARABA  $assistantTranscript',
              style: const TextStyle(
                color: Colors.white,
                fontSize: 13,
                height: 1.35,
              ),
            ),
          ],
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
