import 'package:flutter_test/flutter_test.dart';

import 'package:araba/services/live_utterance_buffer.dart';

void main() {
  test('completed speech segments remain one utterance until consumed', () {
    final buffer = LiveUtteranceBuffer();

    buffer.appendDelta('그거');
    buffer.complete('그거');

    buffer.appendDelta(' 음');
    buffer.complete('음');

    buffer.appendDelta(' 이거는 찾아줘');
    buffer.complete('이거는 찾아줘');

    expect(
      buffer.text,
      '그거 음 이거는 찾아줘',
    );

    buffer.consume('그거 음 이거는 찾아줘');

    expect(buffer.isEmpty, isTrue);
  });

  test('speech arriving during mission processing remains for next turn', () {
    final buffer = LiveUtteranceBuffer();

    buffer.complete('창원 중동 치과 찾아줘');
    final captured = buffer.text;

    buffer.complete('주차되는 곳만');

    buffer.consume(captured);

    expect(
      buffer.text,
      '주차되는 곳만',
    );
  });

  test('fallback processing can consume active uncompleted speech', () {
    final buffer = LiveUtteranceBuffer();

    buffer.appendDelta('상남동에서 찾아줘');

    expect(
      buffer.text,
      '상남동에서 찾아줘',
    );

    buffer.consume('상남동에서 찾아줘');

    expect(buffer.isEmpty, isTrue);
  });
}
