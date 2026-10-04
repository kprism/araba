import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;

import '../../services/api_key_store.dart';
import '../../services/araba_api.dart';

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
  final _speech = stt.SpeechToText();

  final List<_Message> _messages = [
    const _Message(
      isUser: false,
      text: '무엇을 알아볼까요? 말하듯이 편하게 적어주세요.',
    ),
  ];

  bool _speechReady = false;
  bool _listening = false;
  bool _sending = false;

  @override
  void initState() {
    super.initState();
    _initSpeech();
  }

  Future<void> _initSpeech() async {
    try {
      final available = await _speech.initialize(
        onStatus: (status) {
          if (!mounted) return;
          final listening = status == 'listening';
          if (_listening != listening) {
            setState(() => _listening = listening);
          }
        },
        onError: (error) {
          if (!mounted) return;
          setState(() => _listening = false);
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('음성 인식 오류: ${error.errorMsg}')),
          );
        },
      );
      if (mounted) setState(() => _speechReady = available);
    } catch (_) {
      if (mounted) setState(() => _speechReady = false);
    }
  }

  Future<void> _toggleListening() async {
    if (_listening) {
      await _speech.stop();
      if (mounted) setState(() => _listening = false);
      return;
    }

    if (!_speechReady) await _initSpeech();

    if (!_speechReady) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('마이크 및 음성 인식 권한을 확인해주세요.'),
        ),
      );
      return;
    }

    await _speech.listen(
      onResult: (result) {
        if (!mounted) return;
        setState(() {
          _controller.text = result.recognizedWords;
          _controller.selection = TextSelection.collapsed(
            offset: _controller.text.length,
          );
        });
      },
      listenOptions: stt.SpeechListenOptions(
        localeId: 'ko_KR',
        listenMode: stt.ListenMode.dictation,
        partialResults: true,
      ),
    );

    if (mounted) setState(() => _listening = true);
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

  List<String> _strings(dynamic value) {
    if (value is! List) return const [];
    return value
        .map((item) => item.toString().trim())
        .where((item) => item.isNotEmpty)
        .toList();
  }

  String _reply(Map<String, dynamic> mission) {
    final summary = mission['summary']?.toString().trim() ?? '';
    final missing = _strings(mission['missing_information']);

    if (mission['ready_to_research'] != true && missing.isNotEmpty) {
      return summary.isEmpty
          ? '조사를 시작하려면 정보가 조금 더 필요해요.'
          : '$summary\n\n조사를 시작하려면 정보가 조금 더 필요해요.';
    }

    return summary.isEmpty
        ? '요청을 정리했어요. 이대로 진행할까요?'
        : '$summary\n\n이대로 진행할까요?';
  }

  Future<void> _send() async {
    final text = _controller.text.trim();

    if (text.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('알아볼 내용을 입력해주세요.')),
      );
      return;
    }

    setState(() {
      _messages.add(_Message(isUser: true, text: text));
      _controller.clear();
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

      final result = await _api.createMission(text, apiKey: apiKey);

      if (!mounted) return;

      final mission = result['mission'];
      if (mission is! Map<String, dynamic>) {
        throw const ArabaApiException('Mission 응답 형식이 올바르지 않습니다.');
      }

      setState(() {
        _messages.add(
          _Message(
            isUser: false,
            text: _reply(mission),
            mission: mission,
            originalRequest: text,
          ),
        );
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _messages.add(
          _Message(
            isUser: false,
            text: '요청을 처리하지 못했어요. ${error.toString()}',
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

  void _edit(String text) {
    setState(() {
      _controller.text = text;
      _controller.selection = TextSelection.collapsed(offset: text.length);
    });
    _focus.requestFocus();
  }

  void _notYet(String label) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('$label 기능은 조사 실행 엔진 단계에서 연결됩니다.')),
    );
  }

  @override
  void dispose() {
    _speech.stop();
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
            padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 6),
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
                    padding: const EdgeInsets.fromLTRB(16, 22, 16, 18),
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
                        onEdit: message.originalRequest == null
                            ? null
                            : () => _edit(message.originalRequest!),
                        onWeb: () => _notYet('웹 조사'),
                        onPhone: () => _notYet('전화 조사'),
                      );
                    },
                  ),
                ),
                _Composer(
                  controller: _controller,
                  focusNode: _focus,
                  listening: _listening,
                  sending: _sending,
                  onMic: _toggleListening,
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
  final String? originalRequest;
  final bool isError;

  const _Message({
    required this.isUser,
    required this.text,
    this.mission,
    this.originalRequest,
    this.isError = false,
  });
}

class _UserBubble extends StatelessWidget {
  final String text;
  const _UserBubble({required this.text});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 560),
        margin: const EdgeInsets.only(left: 54, bottom: 14),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
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
  final VoidCallback? onEdit;
  final VoidCallback onWeb;
  final VoidCallback onPhone;

  const _AssistantBubble({
    required this.message,
    required this.onEdit,
    required this.onWeb,
    required this.onPhone,
  });

  List<String> _strings(String key) {
    final value = message.mission?[key];
    if (value is! List) return const [];
    return value
        .map((item) => item.toString().trim())
        .where((item) => item.isNotEmpty)
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    final mission = message.mission;
    final ready = mission?['ready_to_research'] == true;
    final phone = mission?['may_need_phone_call'] == true;
    final missing = _strings('missing_information');

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
                  if (mission != null) ...[
                    const SizedBox(height: 9),
                    if (!ready && missing.isNotEmpty)
                      _ChoiceCard(
                        icon: Icons.edit_note_rounded,
                        title: '추가 정보 입력',
                        description: missing.join(' · '),
                        onTap: onEdit,
                      )
                    else ...[
                      _ChoiceCard(
                        icon: Icons.search_rounded,
                        title: '웹에서 먼저 찾아봐',
                        description: '검색 가능한 최신 정보를 먼저 확인합니다.',
                        onTap: onWeb,
                      ),
                      if (phone) ...[
                        const SizedBox(height: 8),
                        _ChoiceCard(
                          icon: Icons.call_outlined,
                          title: '필요하면 전화까지 해',
                          description: '웹으로 부족하면 업체에 직접 확인합니다.',
                          onTap: onPhone,
                        ),
                      ],
                    ],
                    if (onEdit != null) ...[
                      const SizedBox(height: 8),
                      _ChoiceCard(
                        icon: Icons.tune_rounded,
                        title: '조건을 수정할게',
                        description: '방금 요청을 다시 입력합니다.',
                        onTap: onEdit,
                      ),
                    ],
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

class _ChoiceCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String description;
  final VoidCallback? onTap;

  const _ChoiceCard({
    required this.icon,
    required this.title,
    required this.description,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: const Color(0xFFEEF4FF),
      borderRadius: BorderRadius.circular(14),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
          child: Row(
            children: [
              Icon(icon, size: 21, color: const Color(0xFF3157D5)),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        color: Color(0xFF1939A6),
                        fontSize: 14,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      description,
                      style: const TextStyle(
                        color: Color(0xFF475467),
                        fontSize: 12,
                        height: 1.35,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(
                Icons.chevron_right_rounded,
                color: Color(0xFF3157D5),
              ),
            ],
          ),
        ),
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
        padding: EdgeInsets.only(left: 43, right: 34, bottom: 14),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.all(Radius.circular(18)),
          ),
          child: Padding(
            padding: EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                SizedBox(width: 9),
                Text(
                  '요청을 정리하고 있어요…',
                  style: TextStyle(color: Color(0xFF667085)),
                ),
              ],
            ),
          ),
        ),
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
        border: Border(top: BorderSide(color: Color(0xFFEAECF0))),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          IconButton(
            tooltip: listening ? '음성 입력 중지' : '음성으로 말하기',
            onPressed: onMic,
            icon: Icon(
              listening ? Icons.mic_rounded : Icons.mic_none_rounded,
              color: listening
                  ? const Color(0xFFD92D20)
                  : const Color(0xFF475467),
            ),
          ),
          Expanded(
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 14),
              decoration: BoxDecoration(
                color: const Color(0xFFF2F4F7),
                borderRadius: BorderRadius.circular(22),
              ),
              child: TextField(
                controller: controller,
                focusNode: focusNode,
                minLines: 1,
                maxLines: 5,
                decoration: const InputDecoration(
                  hintText: '알아볼 내용을 입력하세요',
                  hintStyle: TextStyle(color: Color(0xFF98A2B3)),
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
              padding: const EdgeInsets.symmetric(horizontal: 14),
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
