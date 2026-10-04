import 'package:flutter/material.dart';

import '../../services/araba_api.dart';

class MyScreen extends StatefulWidget {
  const MyScreen({super.key});

  @override
  State<MyScreen> createState() => _MyScreenState();
}

class _MyScreenState extends State<MyScreen> {
  final ArabaApi _api = ArabaApi();
  final TextEditingController _apiKeyController = TextEditingController();

  bool _loading = true;
  bool _saving = false;
  bool _testing = false;

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
    super.dispose();
  }

  Future<void> _loadStatus() async {
    setState(() {
      _loading = true;
      _message = null;
    });

    try {
      await _api.health();

      final status = await _api.openAiStatus();

      if (!mounted) {
        return;
      }

      setState(() {
        _serverConnected = true;
        _openAiConfigured = status['configured'] == true;
        _maskedKey = status['masked']?.toString();
      });
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
      final result = await _api.saveOpenAiKey(key);

      if (!mounted) {
        return;
      }

      _apiKeyController.clear();

      setState(() {
        _serverConnected = true;
        _openAiConfigured = true;
        _openAiConnected = false;
        _maskedKey = result['masked']?.toString();
        _message = result['message']?.toString();
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
      final result = await _api.testOpenAi();

      if (!mounted) {
        return;
      }

      setState(() {
        _serverConnected = true;
        _openAiConfigured = true;
        _openAiConnected = result['connected'] == true;
        _maskedKey = result['masked']?.toString() ?? _maskedKey;
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

  const _StatusCard({
    required this.loading,
    required this.serverConnected,
    required this.openAiConfigured,
    required this.openAiConnected,
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
