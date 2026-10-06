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
  String _lastMissionTranscript = '';
  DateTime? _lastMissionStartedAt;

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
          onTranscript(isUser: false, delta: delta);
        }
        break;
      case 'session.delegation.created':
        final delegation = event['delegation'];
        if (delegation is Map) {
          final delegationId =
              delegation['id']?.toString().trim() ?? '';
          if (delegationId.isNotEmpty) {
            _missionFallbackTimer?.cancel();
            _missionFallbackTimer = null;
            unawaited(_handleDelegation(delegationId));
          }
        }
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
      const Duration(seconds: 2),
      () {
        _missionFallbackTimer = null;
        unawaited(_handleTranscriptFallback());
      },
    );
  }

  bool _isRecentMissionTurn() {
    final startedAt = _lastMissionStartedAt;
    if (startedAt == null ||
        _lastMissionTranscript.isEmpty) {
      return false;
    }

    return DateTime.now().difference(startedAt) <
        const Duration(seconds: 12);
  }

  Future<void> _handleTranscriptFallback() async {
    if (_missionInFlight) {
      if (_userTranscript.trim().isNotEmpty) {
        _scheduleMissionFallback();
      }
      return;
    }

    final latestUserText = _userTranscript.trim();
    if (latestUserText.isEmpty) return;

    _userTranscript = '';

    await _processMission(
      latestUserText: latestUserText,
    );
  }

  Future<void> _handleDelegation(String delegationId) async {
    final latestUserText = _userTranscript.trim();

    if (latestUserText.isEmpty) {
      if (_missionInFlight || _isRecentMissionTurn()) {
        _sendEvent({
          'type': 'session.commentary.append',
          'delegation_id': delegationId,
          'content': 'ARABA 조사 엔진에서 이미 요청을 처리하고 있습니다.',
        });
        return;
      }

      _sendEvent({
        'type': 'session.commentary.append',
        'delegation_id': delegationId,
        'content': '사용자 요청을 정확히 듣지 못했습니다. 짧게 다시 물어봐 주세요.',
      });
      return;
    }

    if (_missionInFlight) {
      _sendEvent({
        'type': 'session.commentary.append',
        'delegation_id': delegationId,
        'content': 'ARABA 조사 엔진에서 이미 요청을 처리하고 있습니다.',
      });
      return;
    }

    _userTranscript = '';

    await _processMission(
      latestUserText: latestUserText,
      delegationId: delegationId,
    );
  }

  Future<void> _processMission({
    required String latestUserText,
    String? delegationId,
  }) async {
    _missionInFlight = true;
    _lastMissionTranscript = latestUserText;
    _lastMissionStartedAt = DateTime.now();

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

      if (delegationId != null) {
        _sendEvent({
          'type': 'session.thinking.append',
          'event_id': _nextClientEventId('mission_thinking'),
          'delegation_id': delegationId,
          'content': 'ARABA 조사 엔진이 요청을 구조화하고 있습니다.',
        });
      }

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
      onMission(mission, requestText);

      final summary =
          mission['summary']?.toString().trim() ?? '';
      final ready =
          mission['ready_to_research'] == true;
      final questions =
          mission['clarification_questions'];

      if (!ready &&
          questions is List &&
          questions.isNotEmpty) {
        final first = questions.first;
        if (first is Map) {
          final question =
              first['question']?.toString().trim() ?? '';
          final options = first['options'];
          final optionText = options is List
              ? options
                  .map((item) => item.toString())
                  .join(', ')
              : '';

          _pendingRequestContext = requestText;

          if (delegationId != null) {
            _sendEvent({
              'type': 'session.commentary.append',
              'delegation_id': delegationId,
              'content': [
                if (summary.isNotEmpty) summary,
                if (question.isNotEmpty) question,
                if (optionText.isNotEmpty)
                  '선택 가능: $optionText',
              ].join(' '),
            });
          }
          return;
        }
      }

      _pendingRequestContext = null;

      if (delegationId != null) {
        _sendEvent({
          'type': 'session.commentary.append',
          'event_id':
              _nextClientEventId('mission_ready'),
          'delegation_id': delegationId,
          'content': summary.isEmpty
              ? '조건 정리가 끝났습니다. 바로 알아볼게요.'
              : '$summary. 조건 정리가 끝났습니다. 바로 알아볼게요.',
        });
      }
    } catch (error) {
      final message = error is ArabaApiException
          ? error.message
          : 'ARABA 조사 엔진 처리 중 오류가 발생했습니다.';

      if (delegationId != null) {
        _sendEvent({
          'type': 'session.commentary.append',
          'delegation_id': delegationId,
          'content': '조사 엔진을 호출했지만 오류가 발생했습니다. $message',
        });
      } else {
        onError(message);
      }
    } finally {
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
