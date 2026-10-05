import 'package:flutter/material.dart';

import '../../services/api_key_store.dart';
import '../../services/araba_api.dart';
import '../../services/kakao_credential_store.dart';
import '../../services/twilio_credential_store.dart';
import '../../services/voice_preference_store.dart';

class MyScreen extends StatefulWidget {
  const MyScreen({super.key});

  @override
  State<MyScreen> createState() => _MyScreenState();
}

class _MyScreenState extends State<MyScreen> {
  final ArabaApi _api = ArabaApi();
  final ApiKeyStore _apiKeyStore = ApiKeyStore();
  final KakaoCredentialStore _kakaoStore = KakaoCredentialStore();
  final TwilioCredentialStore _twilioStore = TwilioCredentialStore();
  final VoicePreferenceStore _voicePreferenceStore = VoicePreferenceStore();
  final TextEditingController _apiKeyController = TextEditingController();
  final TextEditingController _kakaoKeyController = TextEditingController();
  final TextEditingController _twilioSidController = TextEditingController();
  final TextEditingController _twilioTokenController = TextEditingController();
  final TextEditingController _twilioFromController = TextEditingController();
  final TextEditingController _twilioCallerIdController =
      TextEditingController();
  final TextEditingController _phoneController = TextEditingController();
  final TextEditingController _trainingCategoryController =
      TextEditingController();

  bool _loading = true;
  bool _saving = false;
  bool _testing = false;
  bool _voiceTesting = false;
  bool _kakaoSaving = false;
  bool _twilioSaving = false;
  bool _voiceReady = false;
  bool _kakaoConfigured = false;
  bool _twilioConfigured = false;
  bool _trainingBusy = false;

  bool _serverConnected = false;
  bool _openAiConfigured = false;
  bool _openAiConnected = false;

  String? _maskedKey;
  String? _maskedKakaoKey;
  String? _maskedTwilioSid;
  String? _twilioFromNumber;
  String? _twilioCallerIdNumber;
  String _voiceGender = 'female';
  String _voiceSpeed = 'medium';
  Map<String, dynamic> _trainingStatus = const {};
  String? _message;

  @override
  void initState() {
    super.initState();
    _loadStatus();
  }

  @override
  void dispose() {
    _apiKeyController.dispose();
    _kakaoKeyController.dispose();
    _twilioSidController.dispose();
    _twilioTokenController.dispose();
    _twilioFromController.dispose();
    _twilioCallerIdController.dispose();
    _phoneController.dispose();
    _trainingCategoryController.dispose();
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
      final kakaoKey = await _kakaoStore.read();
      final twilioCredentials = await _twilioStore.read();
      final voicePreferences = await _voicePreferenceStore.read();

      if (mounted) {
        setState(() {
          _openAiConfigured = savedKey != null;
          _maskedKey = _maskKey(savedKey);
          _kakaoConfigured = kakaoKey != null;
          _maskedKakaoKey = _maskKey(kakaoKey);
          _twilioConfigured = twilioCredentials != null;
          _maskedTwilioSid = _maskKey(
            twilioCredentials?.accountSid,
          );
          _twilioFromNumber = twilioCredentials?.fromNumber;
          _twilioCallerIdNumber = twilioCredentials?.callerIdNumber;
          _voiceGender = voicePreferences.gender;
          _voiceSpeed = voicePreferences.speed;
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
            _voiceReady = voice['ready'] == true &&
                _openAiConfigured &&
                _twilioConfigured;
          });
        }
      } catch (_) {
        if (mounted) {
          setState(() {
            _voiceReady = false;
          });
        }
      }

      try {
        final training = await _api.trainingStatus();

        if (mounted) {
          setState(() {
            _trainingStatus = training;
          });
        }
      } catch (_) {
        // 학습 상태 조회 실패는 MY 전체 로딩을 막지 않는다.
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
        _voiceReady = _twilioConfigured;
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

  Future<void> _saveKakaoKey() async {
    final key = _kakaoKeyController.text.trim();

    if (key.isEmpty) {
      _showMessage('Kakao REST API Key를 입력해주세요.');
      return;
    }

    setState(() {
      _kakaoSaving = true;
      _message = null;
    });

    try {
      await _kakaoStore.write(key);

      if (!mounted) {
        return;
      }

      _kakaoKeyController.clear();

      setState(() {
        _kakaoConfigured = true;
        _maskedKakaoKey = _maskKey(key);
        _message = 'Kakao REST API Key가 이 기기에 안전하게 저장되었습니다.';
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
          _kakaoSaving = false;
        });
      }
    }
  }

  Future<void> _deleteKakaoKey() async {
    setState(() {
      _kakaoSaving = true;
      _message = null;
    });

    try {
      await _kakaoStore.delete();

      if (!mounted) {
        return;
      }

      _kakaoKeyController.clear();

      setState(() {
        _kakaoConfigured = false;
        _maskedKakaoKey = null;
        _message = 'Kakao REST API Key 등록을 해제했습니다.';
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
          _kakaoSaving = false;
        });
      }
    }
  }

  Future<void> _saveTwilioCredentials() async {
    final existing = await _twilioStore.read();
    final enteredSid = _twilioSidController.text.trim();
    final enteredToken = _twilioTokenController.text.trim();
    final enteredFrom = _twilioFromController.text.trim();
    final enteredCallerId = _twilioCallerIdController.text.trim();

    final sid = enteredSid.isNotEmpty
        ? enteredSid
        : existing?.accountSid ?? '';
    final token = enteredToken.isNotEmpty
        ? enteredToken
        : existing?.authToken ?? '';
    final fromNumber = enteredFrom.isNotEmpty
        ? enteredFrom
        : existing?.fromNumber;
    final callerIdNumber = enteredCallerId.isNotEmpty
        ? enteredCallerId
        : existing?.callerIdNumber;

    if (sid.isEmpty || token.isEmpty) {
      _showMessage('Twilio Account SID와 Auth Token을 모두 입력해주세요.');
      return;
    }

    setState(() {
      _twilioSaving = true;
      _message = null;
    });

    try {
      await _twilioStore.write(
        accountSid: sid,
        authToken: token,
        fromNumber: fromNumber,
        callerIdNumber: callerIdNumber,
      );

      if (!mounted) {
        return;
      }

      _twilioSidController.clear();
      _twilioTokenController.clear();
      _twilioFromController.clear();
      _twilioCallerIdController.clear();

      setState(() {
        _twilioConfigured = true;
        _maskedTwilioSid = _maskKey(sid);
        _twilioFromNumber = fromNumber;
        _twilioCallerIdNumber = callerIdNumber;
        _voiceReady = _openAiConfigured;
        _message = 'Twilio 계정 정보가 이 기기에 안전하게 저장되었습니다.';
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
          _twilioSaving = false;
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
      final apiKey = await _apiKeyStore.read();

      if (apiKey == null) {
        throw const ArabaApiException(
          'OpenAI API Key를 먼저 저장해주세요.',
        );
      }

      final twilio = await _twilioStore.read();

      if (twilio == null) {
        throw const ArabaApiException(
          'Twilio Account SID와 Auth Token을 먼저 저장해주세요.',
        );
      }

      final result = await _api.startVoiceTestCall(
        phone,
        apiKey: apiKey,
        twilioAccountSid: twilio.accountSid,
        twilioAuthToken: twilio.authToken,
        twilioFromNumber: twilio.fromNumber,
        twilioCallerIdNumber: twilio.callerIdNumber,
        voiceGender: _voiceGender,
        voiceSpeed: _voiceSpeed,
      );

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

  Future<void> _startAdminTrainingCall() async {
    final phone = _phoneController.text.trim();

    if (phone.isEmpty) {
      _showMessage('훈련 전화를 받을 번호를 먼저 입력해주세요.');
      return;
    }

    setState(() {
      _voiceTesting = true;
      _message = null;
    });

    try {
      final apiKey = await _apiKeyStore.read();
      final twilio = await _twilioStore.read();

      if (apiKey == null) {
        throw const ArabaApiException(
          'OpenAI API Key를 먼저 저장해주세요.',
        );
      }

      if (twilio == null) {
        throw const ArabaApiException(
          'Twilio 계정 정보를 먼저 저장해주세요.',
        );
      }

      final result = await _api.startVoiceTestCall(
        phone,
        apiKey: apiKey,
        twilioAccountSid: twilio.accountSid,
        twilioAuthToken: twilio.authToken,
        twilioFromNumber: twilio.fromNumber,
        twilioCallerIdNumber: twilio.callerIdNumber,
        voiceGender: _voiceGender,
        voiceSpeed: _voiceSpeed,
        trainingMode: true,
        trainingCategory:
            _trainingCategoryController.text.trim(),
      );

      if (!mounted) return;

      setState(() {
        _message = result['message']?.toString() ??
            '관리자 실전 훈련 전화를 시작했습니다.';
      });
    } catch (error) {
      if (!mounted) return;

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

  Future<void> _saveVoicePreferences() async {
    await _voicePreferenceStore.write(
      gender: _voiceGender,
      speed: _voiceSpeed,
    );

    if (!mounted) return;

    setState(() {
      _message = '음성 성별과 속도 설정을 저장했습니다.';
    });
  }

  Future<void> _generateTrainingScenarios() async {
    setState(() {
      _trainingBusy = true;
      _message = null;
    });

    try {
      final result = await _api.generateTrainingScenarios(
        limit: 10,
      );
      final status = await _api.trainingStatus();

      if (!mounted) return;

      setState(() {
        _trainingStatus = status;
        _message =
            '새 훈련상황 ${result['created'] ?? 0}개를 만들었습니다.';
      });
    } catch (error) {
      if (!mounted) return;

      setState(() {
        _message = error.toString();
      });
    } finally {
      if (mounted) {
        setState(() {
          _trainingBusy = false;
        });
      }
    }
  }

  Future<void> _runAutoTraining() async {
    setState(() {
      _trainingBusy = true;
      _message = null;
    });

    try {
      final apiKey = await _apiKeyStore.read();

      if (apiKey == null) {
        throw const ArabaApiException(
          'OpenAI API Key를 먼저 저장해주세요.',
        );
      }

      final result = await _api.runAutoTraining(
        apiKey: apiKey,
        limit: 4,
      );
      final status = await _api.trainingStatus();

      if (!mounted) return;

      setState(() {
        _trainingStatus = status;
        _message =
            '자동 훈련 ${result['trained'] ?? 0}건을 완료하고 재발방지 규칙을 반영했습니다.';
      });
    } catch (error) {
      if (!mounted) return;

      setState(() {
        _message = error.toString();
      });
    } finally {
      if (mounted) {
        setState(() {
          _trainingBusy = false;
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
                  '관리자 API 설정',
                  style: TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.w900,
                    letterSpacing: -1,
                  ),
                ),
                const SizedBox(height: 8),
                const Text(
                  'ARABA 운영에 필요한 외부 API 키를 이 기기에서 관리합니다.',
                  style: TextStyle(color: Color(0xFF667085)),
                ),
                const SizedBox(height: 24),
                _StatusCard(
                  loading: _loading,
                  serverConnected: _serverConnected,
                  openAiConfigured: _openAiConfigured,
                  openAiConnected: _openAiConnected,
                  kakaoConfigured: _kakaoConfigured,
                  twilioConfigured: _twilioConfigured,
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
                      const Text(
                        'Kakao Local API',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        _maskedKakaoKey == null
                            ? '등록된 Kakao REST API Key가 없습니다.'
                            : '등록된 Key: $_maskedKakaoKey',
                        style: const TextStyle(
                          color: Color(0xFF667085),
                        ),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        '실제 업체 검색에 사용합니다. 키는 서버에 저장하지 않고 검색 요청 시에만 전달합니다.',
                        style: TextStyle(
                          color: Color(0xFF98A2B3),
                          fontSize: 12,
                          height: 1.4,
                        ),
                      ),
                      const SizedBox(height: 16),
                      TextField(
                        controller: _kakaoKeyController,
                        obscureText: true,
                        enableSuggestions: false,
                        autocorrect: false,
                        decoration: const InputDecoration(
                          labelText: 'Kakao REST API Key',
                          hintText: 'Kakao Developers의 REST API 키',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 14),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton(
                          onPressed: _kakaoSaving
                              ? null
                              : _saveKakaoKey,
                          child: Padding(
                            padding: const EdgeInsets.symmetric(
                              vertical: 13,
                            ),
                            child: _kakaoSaving
                                ? const SizedBox(
                                    width: 20,
                                    height: 20,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      color: Colors.white,
                                    ),
                                  )
                                : Text(
                                    _kakaoConfigured
                                        ? 'Kakao Key 교체'
                                        : 'Kakao Key 저장',
                                  ),
                          ),
                        ),
                      ),
                      if (_kakaoConfigured) ...[
                        const SizedBox(height: 10),
                        SizedBox(
                          width: double.infinity,
                          child: OutlinedButton.icon(
                            onPressed: _kakaoSaving
                                ? null
                                : _deleteKakaoKey,
                            icon: const Icon(Icons.delete_outline_rounded),
                            label: const Text('Kakao Key 등록 해제'),
                          ),
                        ),
                      ],
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
                      const Text(
                        'Twilio Voice',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        _maskedTwilioSid == null
                            ? '등록된 Twilio 계정 정보가 없습니다.'
                            : [
                                '등록된 SID: $_maskedTwilioSid',
                                if (_twilioFromNumber != null)
                                  'Trial 번호: $_twilioFromNumber',
                                if (_twilioCallerIdNumber != null)
                                  '사용자 발신번호: $_twilioCallerIdNumber',
                              ].join('\n'),
                        style: const TextStyle(
                          color: Color(0xFF667085),
                          height: 1.4,
                        ),
                      ),
                      const SizedBox(height: 16),
                      TextField(
                        controller: _twilioSidController,
                        enableSuggestions: false,
                        autocorrect: false,
                        decoration: const InputDecoration(
                          labelText: 'Account SID',
                          hintText: 'AC...',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: _twilioTokenController,
                        obscureText: true,
                        enableSuggestions: false,
                        autocorrect: false,
                        decoration: const InputDecoration(
                          labelText: 'Auth Token',
                          hintText: 'Twilio Console의 Auth Token',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: _twilioFromController,
                        keyboardType: TextInputType.phone,
                        decoration: const InputDecoration(
                          labelText: 'Twilio Trial 테스트 번호',
                          hintText: '+1... / Try out Voice의 From 번호',
                          helperText: '개발용 Trial 통화에서만 사용합니다.',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: _twilioCallerIdController,
                        keyboardType: TextInputType.phone,
                        decoration: const InputDecoration(
                          labelText: '실서비스 발신번호 (사용자 본인번호)',
                          hintText: '010-1234-5678',
                          helperText:
                              'Twilio에서 본인 소유가 인증된 번호만 사용합니다. '
                              '실제 업체 통화 시 이 번호를 발신번호로 요청합니다.',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 14),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton(
                          onPressed: _twilioSaving
                              ? null
                              : _saveTwilioCredentials,
                          child: Padding(
                            padding: const EdgeInsets.symmetric(
                              vertical: 13,
                            ),
                            child: _twilioSaving
                                ? const SizedBox(
                                    width: 20,
                                    height: 20,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      color: Colors.white,
                                    ),
                                  )
                                : const Text('Twilio 정보 저장'),
                          ),
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
                const SizedBox(height: 18),
                Container(
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(18),
                    border: Border.all(
                      color: const Color(0xFFEAECF0),
                    ),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'AI 음성 설정',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        'GPT-Live와 관리자 훈련 통화에 적용합니다.',
                        style: TextStyle(
                          color: Color(0xFF667085),
                          fontSize: 12,
                        ),
                      ),
                      const SizedBox(height: 14),
                      const Text(
                        '음성 성별',
                        style: TextStyle(
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 7),
                      SegmentedButton<String>(
                        segments: const [
                          ButtonSegment(
                            value: 'female',
                            label: Text('여자'),
                          ),
                          ButtonSegment(
                            value: 'male',
                            label: Text('남자'),
                          ),
                        ],
                        selected: {
                          _voiceGender,
                        },
                        onSelectionChanged: (values) {
                          setState(() {
                            _voiceGender = values.first;
                          });
                        },
                      ),
                      const SizedBox(height: 14),
                      const Text(
                        '음성 속도',
                        style: TextStyle(
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 7),
                      SegmentedButton<String>(
                        segments: const [
                          ButtonSegment(
                            value: 'slow',
                            label: Text('느리게'),
                          ),
                          ButtonSegment(
                            value: 'medium',
                            label: Text('중간'),
                          ),
                          ButtonSegment(
                            value: 'fast',
                            label: Text('빠르게'),
                          ),
                        ],
                        selected: {
                          _voiceSpeed,
                        },
                        onSelectionChanged: (values) {
                          setState(() {
                            _voiceSpeed = values.first;
                          });
                        },
                      ),
                      const SizedBox(height: 13),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton(
                          onPressed: _saveVoicePreferences,
                          child: const Text('음성 설정 저장'),
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
                    border: Border.all(
                      color: const Color(0xFFEAECF0),
                    ),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'AI 통화 훈련',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 7),
                      const Text(
                        '실제 조사 데이터의 업종과 다양한 실패상황을 조합해 훈련 시나리오를 만들고, 자동 통화 시뮬레이션에서 나온 실수를 재발방지 규칙으로 누적합니다.',
                        style: TextStyle(
                          color: Color(0xFF667085),
                          fontSize: 12,
                          height: 1.4,
                        ),
                      ),
                      const SizedBox(height: 13),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          _TrainingMetric(
                            label: '시나리오',
                            value: '${_trainingStatus['scenario_count'] ?? 0}',
                          ),
                          _TrainingMetric(
                            label: '학습규칙',
                            value: '${_trainingStatus['rule_count'] ?? 0}',
                          ),
                          _TrainingMetric(
                            label: '훈련횟수',
                            value: '${_trainingStatus['run_count'] ?? 0}',
                          ),
                        ],
                      ),
                      const SizedBox(height: 14),
                      SizedBox(
                        width: double.infinity,
                        child: OutlinedButton.icon(
                          onPressed: _trainingBusy
                              ? null
                              : _generateTrainingScenarios,
                          icon: const Icon(
                            Icons.auto_awesome_rounded,
                          ),
                          label: const Text(
                            '다양한 상황 10개 자동 생성',
                          ),
                        ),
                      ),
                      const SizedBox(height: 9),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton.icon(
                          onPressed: _trainingBusy
                              ? null
                              : _runAutoTraining,
                          icon: _trainingBusy
                              ? const SizedBox(
                                  width: 18,
                                  height: 18,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                              : const Icon(
                                  Icons.psychology_rounded,
                                ),
                          label: Text(
                            _trainingBusy
                                ? '훈련 중...'
                                : '자동 시뮬레이션 훈련 시작',
                          ),
                        ),
                      ),
                      const SizedBox(height: 14),
                      const Divider(),
                      const SizedBox(height: 10),
                      const Text(
                        '관리자 실전 통화 훈련',
                        style: TextStyle(
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        '관리자가 업체 담당자 역할로 응답합니다. 통화 중 “지침:” 또는 “교정:” 뒤에 개선점을 말하면 다음 대화부터 학습규칙으로 반영합니다.',
                        style: TextStyle(
                          color: Color(0xFF667085),
                          fontSize: 12,
                          height: 1.4,
                        ),
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _trainingCategoryController,
                        decoration: const InputDecoration(
                          labelText: '훈련 카테고리 (선택)',
                          hintText: '예: 예약, 미용실, 정비, 범용',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 9),
                      SizedBox(
                        width: double.infinity,
                        child: OutlinedButton.icon(
                          onPressed: _voiceTesting
                              ? null
                              : _startAdminTrainingCall,
                          icon: const Icon(
                            Icons.support_agent_rounded,
                          ),
                          label: const Text(
                            '내 휴대폰으로 실전 훈련 전화',
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

class _TrainingMetric extends StatelessWidget {
  final String label;
  final String value;

  const _TrainingMetric({
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: 10,
        vertical: 7,
      ),
      decoration: BoxDecoration(
        color: const Color(0xFFF2F4F7),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        '$label $value',
        style: const TextStyle(
          color: Color(0xFF344054),
          fontSize: 12,
          fontWeight: FontWeight.w800,
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
  final bool kakaoConfigured;
  final bool twilioConfigured;
  final bool voiceReady;

  const _StatusCard({
    required this.loading,
    required this.serverConnected,
    required this.openAiConfigured,
    required this.openAiConnected,
    required this.kakaoConfigured,
    required this.twilioConfigured,
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
            name: 'Kakao Local',
            value: kakaoConfigured ? 'CONFIGURED' : 'NOT SET',
            active: kakaoConfigured,
          ),
          const SizedBox(height: 10),
          _StatusRow(
            name: 'Twilio',
            value: twilioConfigured ? 'CONFIGURED' : 'NOT SET',
            active: twilioConfigured,
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
