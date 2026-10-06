import 'package:flutter_test/flutter_test.dart';

import 'package:araba/services/conversation_context.dart';

void main() {
  test('conversation context is placed before the current request', () {
    final context = ConversationContext();

    context.rememberMission({
      'location': '창원시',
      'category': '자동차',
      'subject': '타이어 교체',
      'target_business': '예전타이어점',
    });

    final enriched = context.enrichRequest(
      '창원에서 임플란트 가능한 치과 몇 군데 알아봐.',
    );

    final contextIndex = enriched.indexOf('[대화 문맥 - 참고용]');
    final currentIndex = enriched.indexOf('[현재 요청]');

    expect(contextIndex, greaterThanOrEqualTo(0));
    expect(currentIndex, greaterThan(contextIndex));
    expect(
      enriched.substring(currentIndex),
      contains('창원에서 임플란트 가능한 치과'),
    );
  });

  test('new category clears stale topic-specific memory', () {
    final context = ConversationContext();

    context.rememberMission({
      'location': '창원시',
      'category': '자동차',
      'subject': '타이어 교체',
      'target_business': '예전타이어점',
      'constraints': ['오늘 교체'],
      'attributes': {'규격': '275/40R20'},
    });

    context.rememberMission({
      'location': '창원시',
      'category': '의료',
      'subject': '임플란트 가능한 치과',
      'search_mode': 'category_discovery',
      'constraints': ['임플란트 가능'],
    });

    final snapshot = context.snapshot;

    expect(snapshot['category'], '의료');
    expect(snapshot['subject'], '임플란트 가능한 치과');
    expect(snapshot.containsKey('target_business'), isFalse);
    expect(snapshot.containsKey('attributes'), isFalse);
    expect(snapshot['constraints'], ['임플란트 가능']);
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
