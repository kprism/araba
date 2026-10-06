import 'dart:async';
import 'dart:convert';

import 'package:flutter_webrtc/flutter_webrtc.dart';

import 'araba_api.dart';
import 'conversation_context.dart';

typedef LiveStatusCallback = void Function(String status);
typedef LiveTranscriptCallback = void Function({
  required bool isUser,
  required String delta,
});
typedef LiveMissionCallback = void Function(
  Map<String, dynamic> mission,
  String requestContext,
);

class LiveVoiceService {
  final ArabaApi api;
  final String apiKey;
  final ConversationContext conversationContext;
  final String voiceGender;
  final String voiceSpeed;
  final LiveStatusCallback onStatus;
  final LiveTranscriptCallback onTranscript;
  final LiveMissionCallback onMission;
  final void Function(String message) onError;
  final void Function(String message)? onDiagnostic;

  RTCPeerConnection? _peerConnection;
  MediaStream? _localStream;
  RTCDataChannel? _events;

  String _userTranscript = '';
  String? _pendingRequestContext;
  bool _started = false;
  bool _closing = false;
  Timer? _disconnectTimer;
  Timer? _missionFallbackTimer;
  RTCPeerConnectionState? _connectionState;
  int _clientEventSequence = 0;
  bool _missionInFlight = false;

  LiveVoiceService({
    required this.api,
    required this.apiKey,
    required this.conversationContext,
    this.voiceGender = 'female',
    this.voiceSpeed = 'medium',
    required this.onStatus,
    required this.onTranscript,
    required this.onMission,
    required this.onError,
    this.onDiagnostic,
  });

  bool get isStarted => _started;

  Future<void> start() async {
    if (_started) return;

    onStatus('연결 중');

    try {
      final peerConnection = await createPeerConnection(
        <String, dynamic>{},
      );
      _peerConnection = peerConnection;

      final stream = await navigator.mediaDevices.getUserMedia(
        <String, dynamic>{
          'audio': true,
          'video': false,
        },
      );
      _localStream = stream;

      for (final track in stream.getAudioTracks()) {
        await peerConnection.addTrack(track, stream);
      }

      await Helper.setSpeakerphoneOnButPreferBluetooth();

      final events = await peerConnection.createDataChannel(
        'oai-events',
        RTCDataChannelInit(),
      );
      _events = events;

      events.onMessage = _handleMessage;
      events.onDataChannelState = (state) {
        if (state == RTCDataChannelState.RTCDataChannelOpen) {
          onStatus('대화 준비 중');
        }
      };

      peerConnection.onConnectionState = (state) {
        _connectionState = state;

        if (
            state ==
                RTCPeerConnectionState
                    .RTCPeerConnectionStateConnected) {
          _disconnectTimer?.cancel();
          _disconnectTimer = null;
          if (_started) {
            onStatus('듣고 있어요');
          }
          return;
        }

        if (
            state ==
                RTCPeerConnectionState
                    .RTCPeerConnectionStateDisconnected) {
          _disconnectTimer?.cancel();
          _disconnectTimer = Timer(
            const Duration(seconds: 3),
            () {
              if (!_closing &&
                  _connectionState ==
                      RTCPeerConnectionState
                          .RTCPeerConnectionStateDisconnected) {
                _started = false;
                onStatus('재연결 필요');
                onError(
                  '실시간 음성 연결이 잠시 끊겼어요.',
                );
              }
            },
          );
          return;
        }

        if (
            state ==
                RTCPeerConnectionState
                    .RTCPeerConnectionStateFailed) {
          _disconnectTimer?.cancel();
          _disconnectTimer = null;
          if (!_closing) {
            _started = false;
            onStatus('재연결 필요');
            onError(
              '실시간 음성 연결이 끊겼어요.',
            );
          }
        }
      };

      final offer = await peerConnection.createOffer(
        <String, dynamic>{
          'offerToReceiveAudio': true,
        },
      );
      await peerConnection.setLocalDescription(offer);

      // SDP는 마지막 CRLF까지 WebRTC 원문 그대로 OpenAI에 전달해야 한다.
      // trim()을 사용하면 SDP 파서가 EOF로 실패할 수 있다.
      final offerSdp = offer.sdp ?? '';

      if (offerSdp.trim().isEmpty) {
        throw const ArabaApiException(
          '실시간 음성 연결 정보를 만들지 못했어요.',
        );
      }

      final requiredSdpParts = <String>[
        'v=0',
        'm=audio',
        'a=ice-ufrag:',
        'a=ice-pwd:',
      ];

      if (requiredSdpParts.any(
        (part) => !offerSdp.contains(part),
      )) {
        throw const ArabaApiException(
          '실시간 음성 연결 정보가 완전하지 않아요. 다시 시도해주세요.',
        );
      }

      final session = await api.createLiveSession(
        offerSdp,
        apiKey: apiKey,
        voiceGender: voiceGender,
        voiceSpeed: voiceSpeed,
      );
      final answerSdp = session['sdp']?.toString() ?? '';

      if (answerSdp.trim().isEmpty) {
        throw const ArabaApiException(
          'GPT-Live 연결 응답이 올바르지 않아요.',
        );
      }

      await peerConnection.setRemoteDescription(
        RTCSessionDescription(
          answerSdp,
          'answer',
        ),
      );
    } catch (error) {
      await stop(force: true);
      if (error is ArabaApiException) {
        onError(error.message);
      } else {
        onError('실시간 음성 대화를 시작하지 못했어요.');
      }
      rethrow;
    }
  }

  void _handleMessage(RTCDataChannelMessage message) {
    if (message.isBinary) return;

    Map<String, dynamic> event;

    try {
      event = jsonDecode(message.text) as Map<String, dynamic>;
    } catch (_) {
      return;
    }

    final type = event['type']?.toString() ?? '';

    switch (type) {
      case 'session.started':
        _started = true;
        onStatus('듣고 있어요');
        break;
      case 'session.input_transcript.delta':
        final delta = event['delta']?.toString() ?? '';
        if (delta.isNotEmpty) {
          _userTranscript += delta;
          onTranscript(isUser: true, delta: delta);
          _scheduleMissionFallback();
        }
        break;
      case 'session.output_transcript.delta':
        final delta = event['delta']?.toString() ?? '';
        if (delta.isNotEmpty) {
          // Live의 짧은 맞장구는 사용자 발화 종료 신호가 아니다.
          // 여기서 Core를 호출하면 "창원시청"과 "주변에..." 같은
          // 한 요청이 두 Mission으로 잘리는 문제가 생긴다.
          if (_userTranscript.isNotEmpty &&
              !_userTranscript.endsWith(' ')) {
            _userTranscript += ' ';
          }
          onTranscript(isUser: false, delta: delta);
        }
        break;
      case 'session.delegation.created':
        // 구버전 서버가 delegation 이벤트를 보내더라도
        // 판단 경로로 사용하지 않는다. 모든 실질 판단은
        // 확정된 사용자 발화를 GPT Core로 보내 처리한다.
        break;
      case 'session.closed':
        _started = false;
        onStatus('종료됨');
        unawaited(_cleanup());
        break;
      case 'error':
        final error = event['error'];
        final detail = error is Map
            ? error['message']?.toString()
            : null;
        onError(detail ?? 'GPT-Live에서 오류가 발생했어요.');
        break;
    }
  }

  void _scheduleMissionFallback() {
    _missionFallbackTimer?.cancel();

    if (!_started || _closing) return;

    _missionFallbackTimer = Timer(
      const Duration(seconds: 3),
      () {
        _missionFallbackTimer = null;
        unawaited(_dispatchTranscriptToCore());
      },
    );
  }

  Future<void> _dispatchTranscriptToCore() async {
    if (_missionInFlight) {
      if (_userTranscript.trim().isNotEmpty) {
        _scheduleMissionFallback();
      }
      return;
    }

    final latestUserText = _userTranscript.trim();
    if (latestUserText.isEmpty) return;

    await _processMission(
      latestUserText: latestUserText,
    );
  }

  void _consumeProcessedTranscript(String processedText) {
    final current = _userTranscript;
    final processed = processedText.trim();

    if (processed.isEmpty || current.isEmpty) {
      return;
    }

    if (current.trim() == processed) {
      _userTranscript = '';
      return;
    }

    final index = current.indexOf(processedText);
    if (index == 0) {
      _userTranscript = current.substring(processedText.length);
    }
  }

  Future<void> _processMission({
    required String latestUserText,
  }) async {
    _missionInFlight = true;
    String? preparedRequestText;
    final missionStopwatch = Stopwatch()..start();

    try {
      final rawRequestText = _pendingRequestContext == null
          ? latestUserText
          : [
              _pendingRequestContext!,
              '',
              '사용자 추가 답변:',
              latestUserText,
            ].join('\n');
      final requestText = conversationContext.enrichRequest(
        rawRequestText,
      );
      preparedRequestText = requestText;

      final result = await api.createMission(
        requestText,
        apiKey: apiKey,
      );

      final mission = result['mission'];
      if (mission is! Map<String, dynamic>) {
        throw const ArabaApiException(
          '조사 엔진 응답 형식이 올바르지 않아요.',
        );
      }

      conversationContext.rememberMission(mission);
      _consumeProcessedTranscript(latestUserText);
      onMission(mission, requestText);

      final ready =
          mission['ready_to_research'] == true;
      final questions =
          mission['clarification_questions'];

      if (!ready &&
          questions is List &&
          questions.isNotEmpty &&
          questions.first is Map) {
        _pendingRequestContext = requestText;
        return;
      }

      _pendingRequestContext = null;
    } catch (error) {
      // 실패해도 사용자가 방금 말한 맥락을 버리지 않는다.
      // 다음 발화가 이어지면 직전 요청과 합쳐 Core가 다시 판단한다.
      if (preparedRequestText != null) {
        _pendingRequestContext = preparedRequestText;
      }
      _consumeProcessedTranscript(latestUserText);

      final elapsedSeconds =
          missionStopwatch.elapsedMilliseconds / 1000;
      final detail = error is ArabaApiException
          ? error.diagnosticText
          : '단계: app_mission_processing\n예외: ${error.runtimeType}';

      onDiagnostic?.call(
        'GPT Core 요청 실패 · 앱 경과 ${elapsedSeconds.toStringAsFixed(1)}초\n'
        '$detail',
      );
      speakCommentary(
        '요청 처리에 실패했고 오류 진단을 채팅에 기록했습니다. '
        '자동 재시도는 하지 않았습니다. 방금 말씀하신 내용은 유지하고 있습니다.',
      );
      onStatus('Core 진단: ${elapsedSeconds.toStringAsFixed(1)}초');
    } finally {
      missionStopwatch.stop();
      _missionInFlight = false;

      if (_userTranscript.trim().isNotEmpty) {
        _scheduleMissionFallback();
      }
    }
  }

  Future<void> resumeAudio() async {
    for (final track
        in _localStream?.getAudioTracks() ??
            <MediaStreamTrack>[]) {
      track.enabled = true;
    }

    try {
      await Helper.setSpeakerphoneOnButPreferBluetooth();
    } catch (_) {}
  }

  void resetPendingMissionContext() {
    _pendingRequestContext = null;
  }

  void speakCommentary(String content) {
    final text = content.trim();
    if (!_started || text.isEmpty) return;

    _sendEvent({
      'type': 'session.commentary.append',
      'event_id': _nextClientEventId('progress'),
      'delegation_id': null,
      'content': text,
    });
  }

  String _nextClientEventId(String prefix) {
    _clientEventSequence += 1;
    return 'araba_${prefix}_$_clientEventSequence';
  }

  void _sendEvent(Map<String, dynamic> event) {
    final events = _events;
    if (events == null) return;

    events.send(
      RTCDataChannelMessage(
        jsonEncode(event),
      ),
    );
  }

  Future<void> stop({bool force = false}) async {
    if (_closing) return;
    _closing = true;

    try {
      if (!force && _events != null && _started) {
        _sendEvent({
          'type': 'session.close',
        });
        await Future<void>.delayed(
          const Duration(milliseconds: 350),
        );
      }
    } finally {
      await _cleanup();
      _closing = false;
    }
  }

  Future<void> _cleanup() async {
    _started = false;
    _disconnectTimer?.cancel();
    _disconnectTimer = null;
    _missionFallbackTimer?.cancel();
    _missionFallbackTimer = null;
    _missionInFlight = false;
    _connectionState = null;

    try {
      await _events?.close();
    } catch (_) {}
    _events = null;

    try {
      for (final track in _localStream?.getTracks() ?? <MediaStreamTrack>[]) {
        await track.stop();
      }
      await _localStream?.dispose();
    } catch (_) {}
    _localStream = null;

    try {
      await _peerConnection?.close();
      await _peerConnection?.dispose();
    } catch (_) {}
    _peerConnection = null;

    try {
      await Helper.clearAndroidCommunicationDevice();
    } catch (_) {}
  }
}
