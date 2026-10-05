import 'package:flutter_test/flutter_test.dart';

import 'package:araba/services/conversation_context.dart';

void main() {
  test('known location is carried into the next request', () {
    final context = ConversationContext();

    context.rememberMission({
      'location': '창원시',
    });

    final enriched = context.enrichRequest(
      '오늘 타이어 두 개 교체 가능한 곳 찾아줘',
    );

    expect(
      enriched,
      contains('[대화 문맥] 이미 확인된 지역: 창원시'),
    );
    expect(
      enriched,
      contains('다시 묻지 마세요'),
    );
  });

  test('latest mission location replaces the old location', () {
    final context = ConversationContext();

    context.rememberMission({
      'location': '창원시',
    });
    context.rememberMission({
      'location': '부산시',
    });

    expect(context.location, '부산시');
  });

  test('already enriched request is not duplicated', () {
    final context = ConversationContext();

    context.rememberMission({
      'location': '창원시',
    });

    final once = context.enrichRequest('타이어 찾아줘');
    final twice = context.enrichRequest(once);

    expect(twice, once);
  });
}
