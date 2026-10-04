import 'package:flutter/material.dart';

import '../../services/api_key_store.dart';
import '../../services/araba_api.dart';

class MyScreen extends StatefulWidget {
  const MyScreen({super.key});

  @override
  State<MyScreen> createState() => _MyScreenState();
}

class _MyScreenState extends State<MyScreen> {
  final ArabaApi _api = ArabaApi();
  final ApiKeyStore _apiKeyStore = ApiKeyStore();
  final TextEditingController _apiKeyController = TextEditingController();
  final TextEditingController _phoneController = TextEditingController();

  bool _loading = true;
  bool _saving = false;
  bool _testing = false;
  bool _voiceTesting = false;
  bool _voiceReady = false;

  bool _serverConnected = false;
  bool _openAiConfigured = false;
  bool _openAiConnected = false;

  String? _maskedKey;
  String? _message;

  @override
  void initState() {
    super.initState();
    _loadStatus();
  }

  @override
  void dispose() {
    _apiKeyController.dispose();
    _phoneController.dispose();
    super.dispose();
  }

  String? _maskKey(String? key) {
    final value = key?.trim();

    if (value == null || value.isEmpty) {
      return null;
    }

    if (value.length <= 12) {
      return '********';
    }

    return '${value.substring(0, 7)}'
        '••••••••••••'
        '${value.substring(value.length - 4)}';
  }

  Future<void> _loadStatus() async {
    setState(() {
      _loading = true;
      _message = null;
    });

    String? savedKey;

    try {
      savedKey = await _apiKeyStore.read();

      if (mounted) {
        setState(() {
          _openAiConfigured = savedKey != null;
          _maskedKey = _maskKey(savedKey);
        });
      }

      await _api.health();

      if (!mounted) {
        return;
      }

      setState(() {
        _serverConnected = true;
      });

      try {
        final voice = await _api.voiceStatus();

        if (mounted) {
          setState(() {
            _voiceReady = voice['ready'] == true;
          });
        }
      } catch (_) {
        if (mounted) {
          setState(() {
            _voiceReady = false;
          });
        }
      }
    } catch (error) {
      if (!mounted) {
        return;
      }

      setState(() {
        _serverConnected = false;
        _message = error.toString();
      });
    } finally {
      if (mounted) {
        setState(() {
          _loading = false;
        });
      }
    }
  }

  Future<void> _saveKey() async {
    final key = _apiKeyController.text.trim();

    if (key.isEmpty) {
      _showMessage('OpenAI API Key를 입력해주세요.');
      return;
    }

    setState(() {
      _saving = true;
      _message = null;
    });

    try {
      await _apiKeyStore.write(key);

      if (!mounted) {
        return;
      }

      _apiKeyController.clear();

      setState(() {
        _openAiConfigured = true;
        _openAiConnected = false;
        _maskedKey = _maskKey(key);
        _message = 'OpenAI API Key가 이 기기에 안전하게 저장되었습니다.';
      });
    } catch (error) {
      if (!mounted) {
        return;
      }

      setState(() {
        _message = error.toString();
      });
    } finally {
      if (mounted) {
        setState(() {
          _saving = false;
        });
      }
    }
  }

  Future<void> _testConnection() async {
    setState(() {
      _testing = true;
      _message = null;
    });

    try {
      final key = await _apiKeyStore.read();

      if (key == null) {
        throw const ArabaApiException(
          'OpenAI API Key를 먼저 저장해주세요.',
        );
      }

      final result = await _api.testOpenAi(key);

      if (!mounted) {
        return;
      }

      setState(() {
        _serverConnected = true;
        _openAiConfigured = true;
        _openAiConnected = result['connected'] == true;
        _maskedKey = _maskKey(key);
        _message = result['message']?.toString();
      });
    } catch (error) {
      if (!mounted) {
        return;
      }

      setState(() {
        _openAiConnected = false;
        _message = error.toString();
      });
    } finally {
      if (mounted) {
        setState(() {
          _testing = false;
        });
      }
    }
  }

  Future<void> _startVoiceTestCall() async {
    final phone = _phoneController.text.trim();

    if (phone.isEmpty) {
      _showMessage('전화를 받을 휴대폰 번호를 입력해주세요.');
      return;
    }

    setState(() {
      _voiceTesting = true;
      _message = null;
    });

    try {
      final result = await _api.startVoiceTestCall(phone);

      if (!mounted) {
        return;
      }

      setState(() {
        _message = result['message']?.toString() ??
            'AI 테스트 전화를 시작했습니다.';
      });
    } catch (error) {
      if (!mounted) {
        return;
      }

      setState(() {
        _message = error.toString();
      });
    } finally {
      if (mounted) {
        setState(() {
          _voiceTesting = false;
        });
      }
    }
  }

  void _showMessage(String message) {
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('MY', style: TextStyle(fontWeight: FontWeight.w800)),
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(22, 24, 22, 120),
              children: [
                const Text(
                  '개발 설정',
                  style: TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.w900,
                    letterSpacing: -1,
                  ),
                ),
                const SizedBox(height: 8),
                const Text(
                  'POC 단계에서만 사용하는 개발자 설정입니다.',
                  style: TextStyle(color: Color(0xFF667085)),
                ),
                const SizedBox(height: 24),
                _StatusCard(
                  loading: _loading,
                  serverConnected: _serverConnected,
                  openAiConfigured: _openAiConfigured,
                  openAiConnected: _openAiConnected,
                  voiceReady: _voiceReady,
                ),
                const SizedBox(height: 18),
                Container(
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(18),
                    border: Border.all(color: const Color(0xFFEAECF0)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'OpenAI API',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        _maskedKey == null
                            ? '등록된 API Key가 없습니다.'
                            : '등록된 Key: $_maskedKey',
                        style: const TextStyle(color: Color(0xFF667085)),
                      ),
                      const SizedBox(height: 18),
                      TextField(
                        controller: _apiKeyController,
                        obscureText: true,
                        enableSuggestions: false,
                        autocorrect: false,
                        decoration: const InputDecoration(
                          labelText: 'OpenAI API Key',
                          hintText: 'sk-...',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 14),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton(
                          onPressed: _saving ? null : _saveKey,
                          child: Padding(
                            padding: const EdgeInsets.symmetric(vertical: 13),
                            child: _saving
                                ? const SizedBox(
                                    width: 20,
                                    height: 20,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const Text('API Key 저장'),
                          ),
                        ),
                      ),
                      const SizedBox(height: 10),
                      SizedBox(
                        width: double.infinity,
                        child: OutlinedButton.icon(
                          onPressed: !_openAiConfigured || _testing
                              ? null
                              : _testConnection,
                          icon: _testing
                              ? const SizedBox(
                                  width: 18,
                                  height: 18,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                              : const Icon(Icons.bolt_rounded),
                          label: const Text('OpenAI 연결 테스트'),
                        ),
                      ),
                    ],
                  ),
                ),

                const SizedBox(height: 18),
                Container(
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(18),
                    border: Border.all(color: const Color(0xFFEAECF0)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Row(
                        children: [
                          Icon(Icons.phone_in_talk_rounded),
                          SizedBox(width: 8),
                          Text(
                            'AI 음성통화 테스트',
                            style: TextStyle(
                              fontSize: 18,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        _voiceReady
                            ? '준비 완료. ARABA가 아래 번호로 직접 전화를 겁니다.'
                            : 'Twilio 전화 설정이 완료되면 여기서 실제 AI 통화를 테스트할 수 있습니다.',
                        style: const TextStyle(
                          color: Color(0xFF667085),
                          height: 1.4,
                        ),
                      ),
                      const SizedBox(height: 16),
                      TextField(
                        controller: _phoneController,
                        keyboardType: TextInputType.phone,
                        decoration: const InputDecoration(
                          labelText: '테스트 휴대폰 번호',
                          hintText: '010-1234-5678',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 12),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton.icon(
                          onPressed: _voiceTesting
                              ? null
                              : _startVoiceTestCall,
                          icon: _voiceTesting
                              ? const SizedBox(
                                  width: 18,
                                  height: 18,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                    color: Colors.white,
                                  ),
                                )
                              : const Icon(Icons.call_rounded),
                          label: Text(
                            _voiceTesting
                                ? '전화 거는 중...'
                                : '내 휴대폰으로 AI 테스트 전화 걸기',
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                if (_message != null) ...[
                  const SizedBox(height: 16),
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: const Color(0xFFEEF4FF),
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: Text(
                      _message!,
                      style: const TextStyle(color: Color(0xFF344054)),
                    ),
                  ),
                ],
                const SizedBox(height: 18),
                Text(
                  'API 서버: ${_api.baseUrl}',
                  style: const TextStyle(
                    color: Color(0xFF98A2B3),
                    fontSize: 12,
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

class _StatusCard extends StatelessWidget {
  final bool loading;
  final bool serverConnected;
  final bool openAiConfigured;
  final bool openAiConnected;
  final bool voiceReady;

  const _StatusCard({
    required this.loading,
    required this.serverConnected,
    required this.openAiConfigured,
    required this.openAiConnected,
    required this.voiceReady,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: const Color(0xFF101828),
        borderRadius: BorderRadius.circular(17),
      ),
      child: Column(
        children: [
          _StatusRow(
            name: 'ARABA API',
            value: loading
                ? 'CHECKING'
                : serverConnected
                ? 'CONNECTED'
                : 'OFFLINE',
            active: serverConnected,
          ),
          const SizedBox(height: 10),
          _StatusRow(
            name: 'OpenAI Key',
            value: openAiConfigured ? 'CONFIGURED' : 'NOT SET',
            active: openAiConfigured,
          ),
          const SizedBox(height: 10),
          _StatusRow(
            name: 'OpenAI',
            value: openAiConnected ? 'CONNECTED' : 'NOT TESTED',
            active: openAiConnected,
          ),
          const SizedBox(height: 10),
          _StatusRow(
            name: 'AI Voice',
            value: voiceReady ? 'READY' : 'NOT SET',
            active: voiceReady,
          ),
        ],
      ),
    );
  }
}

class _StatusRow extends StatelessWidget {
  final String name;
  final String value;
  final bool active;

  const _StatusRow({
    required this.name,
    required this.value,
    required this.active,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(
          Icons.circle,
          size: 9,
          color: active ? const Color(0xFF32D583) : const Color(0xFF667085),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Text(name, style: const TextStyle(color: Colors.white)),
        ),
        Text(
          value,
          style: TextStyle(
            color: active ? const Color(0xFF32D583) : const Color(0xFF98A2B3),
            fontSize: 12,
            fontWeight: FontWeight.w800,
          ),
        ),
      ],
    );
  }
}
