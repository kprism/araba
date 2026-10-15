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

  test('location correction rule is carried into contextual requests', () {
    final context = ConversationContext();

    context.rememberMission({
      'location': '창원시청',
      'category': '치과',
    });

    final enriched = context.enrichRequest(
      '거기 아니고 상남동에서 찾아줘',
    );

    expect(
      enriched,
      contains('거기 아니고'),
    );
    expect(
      enriched,
      contains('정정'),
    );
    expect(
      enriched,
      contains('[현재 요청]'),
    );
  });

  test('clarification rule asks all essential user-only details together', () {
    final context = ConversationContext();

    context.rememberMission({
      'category': '치과',
      'user_goal': '치과 예약',
    });

    final enriched = context.enrichRequest(
      '예약해줘',
    );

    expect(
      enriched,
      contains('한 번의 질문에 모두 묶어서'),
    );
    expect(
      enriched,
      isNot(contains('가장 중요한 것 하나만')),
    );
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

  test('place result sets are remembered with rank and detail facts', () {
  final context = ConversationContext();

  context.rememberBusinessResults(
    {
      'category': '치과',
      'location': '창원시 의창구 중동',
    },
    [
      {
        'name': '첫치과',
        'address': '창원시 의창구 중동 1',
        'phone': '055-111-1111',
        'naver': {
          'opening_hours': ['월 09:00-18:00'],
          'parking_available': true,
          'prices': [
            {
              'name': '검사',
              'price': '90,000원',
              'currency': 'KRW',
            },
          ],
        },
      },
      {
        'name': '둘치과',
        'address': '창원시 의창구 중동 2',
        'phone': '055-222-2222',
      },
    ],
  );

  final snapshot = context.snapshot;
  final results =
      snapshot['recent_place_results'] as List;
  final history =
      snapshot['recent_place_searches'] as List;

  expect(results.length, 2);
  expect(
    (results.first as Map)['rank'],
    1,
  );
  expect(
    (results.first as Map)['name'],
    '첫치과',
  );
  expect(
    (results.first as Map)['parking_available'],
    isTrue,
  );
  expect(
    ((results.first as Map)['prices'] as List).first,
    containsPair('price', '90,000원'),
  );
  expect(history.length, 1);
});

test('task state and structured criteria are kept in conversation context', () {
  final context = ConversationContext();

  context.rememberMission({
    'category': '치과',
    'location': '창원시',
    'criteria': [
      {
        'id': 'c1',
        'field': 'parking_available',
        'operator': 'eq',
        'value': true,
        'required': true,
      },
    ],
    'task_state': {
      'version': 'task-state-v1',
      'stage': 'research_ready',
      'candidate_scope': 'new_search',
    },
  });

  final snapshot = context.snapshot;

  expect(
    (snapshot['criteria'] as List).length,
    1,
  );
  expect(
    (snapshot['task_state'] as Map)['stage'],
    'research_ready',
  );
});

test('place search history keeps recent categories for later follow-up', () {
  final context = ConversationContext();

  context.rememberBusinessResults(
    {
      'category': '치과',
      'location': '중동',
    },
    [
      {'name': '치과A'},
    ],
  );
  context.rememberBusinessResults(
    {
      'category': '미용실',
      'location': '중동',
    },
    [
      {'name': '미용실A'},
    ],
  );

  final history =
      context.snapshot['recent_place_searches']
          as List;

  expect(history.length, 2);
  expect(
    (history.first as Map)['category'],
    '미용실',
  );
  expect(
    (history[1] as Map)['category'],
    '치과',
  );
});

test('STT correction of an explicitly named clinic skips GPT Core', () {
  final context = ConversationContext();
  final mission = context.explicitNameCorrectionMission(
    '하이스트용치과 하이스트가 아니고 카이스트',
  )!;
  expect(mission['target_business'], '카이스트용치과');
  expect(mission['search_terms'], ['카이스트용치과']);
  expect(mission['category'], '치과');
  expect(mission['search_mode'], 'exact_place');
  expect(mission['requested_count'], 1);
});

test('short spoken correction reuses prior exact place and location', () {
  final context = ConversationContext();
  context.rememberMission({
    'intent': 'place_search',
    'search_mode': 'exact_place',
    'location': '창원시 의창구 중동',
    'category': '치과',
    'target_business': '하이스트용치과',
  });
  final mission = context.explicitNameCorrectionMission(
    '하이스트가 아니고 카이스트',
  )!;
  expect(mission['target_business'], '카이스트용치과');
  expect(mission['location'], '창원시 의창구 중동');
  context.rememberMission(mission);
  expect(context.snapshot['target_business'], '카이스트용치과');
});

test('ambiguous topic and location corrections do not guess a name', () {
  final context = ConversationContext();
  for (final utterance in [
    '치과 말고 피부과',
    '하이스트가 아니고 카이스트',
    '창원시 아니고 부산시',
    '그중 오늘 밤 9시까지 하는 곳',
    '우산 하나 만들어줘',
  ]) {
    expect(
      context.explicitNameCorrectionMission(utterance),
      isNull, reason: utterance,
    );
  }
});

test('unrelated stale exact target is not used for new name', () {
  final context = ConversationContext();
  context.rememberMission({
    'category': '치과',
    'target_business': '다른치과',
    'search_mode': 'exact_place',
  });
  expect(
    context.explicitNameCorrectionMission(
      '하이스트가 아니고 카이스트',
    ), isNull,
  );
});
}
