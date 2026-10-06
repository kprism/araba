import 'dart:async';
import 'dart:convert';

import 'package:araba/services/araba_api.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('server timeout preserves HTTP status, stage and exception', () async {
    await http.runWithClient(() async {
      try {
        await ArabaApi().createMission('타이어점', apiKey: 'test');
        fail('Expected failure');
      } on ArabaApiException catch (error) {
        expect(error.statusCode, 504);
        expect(error.stage, 'openai_request');
        expect(error.exceptionType, 'APITimeoutError');
        expect(error.diagnosticText, contains('request_id: test-request'));
      }
    }, () => MockClient((request) async => http.Response(jsonEncode({
      'ok': false,
      'message': '응답 대기시간 초과',
      'diagnostics': {
        'stage': 'openai_request',
        'exception_type': 'APITimeoutError',
        'request_id': 'test-request',
      },
    }), 504, headers: {'content-type': 'application/json; charset=utf-8'})));
  });

  test('local timeout differs from a server HTTP 504', () async {
    await http.runWithClient(() async {
      try {
        await ArabaApi().createMission('타이어점', apiKey: 'test');
        fail('Expected failure');
      } on ArabaApiException catch (error) {
        expect(error.statusCode, isNull);
        expect(error.stage, 'app_wait_timeout');
        expect(error.exceptionType, 'TimeoutException');
      }
    }, () => MockClient((request) async => throw TimeoutException('test')));
  });

  test('non-JSON proxy failure preserves HTTP status', () async {
    await http.runWithClient(() async {
      try {
        await ArabaApi().createMission('타이어점', apiKey: 'test');
        fail('Expected failure');
      } on ArabaApiException catch (error) {
        expect(error.statusCode, 502);
        expect(error.stage, 'decode_response');
      }
    }, () => MockClient((request) async => http.Response('<html>error</html>', 502)));
  });
}
