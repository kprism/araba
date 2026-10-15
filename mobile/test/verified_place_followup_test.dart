import 'package:araba/services/verified_place_followup.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  final thursday = DateTime(2026, 10, 15, 20, 30);

  Map<String,dynamic> clinic(String id, String name, String address,
      {List<String>? hours}) => {
    'id': id, 'name': name, 'address': address,
    'naver': {
      'matched': true,
      'page_checked': true,
      'opening_hours': hours ?? <String>[],
    },
  };

  test('spoken or typed followup keeps only previous three businesses', () {
    final original = [
      clinic('11','창원치과A','경남 창원시 의창구',hours:['목요일 09:00-21:30']),
      clinic('12','창원치과B','경남 창원시 성산구'),
      clinic('13','창원치과C','경남 창원시 의창구',hours:['목요일 09:00-18:00']),
    ];
    final mission = VerifiedPlaceFollowup.missionFor(
      '그중에서 오늘 밤 9시까지 진료하는 곳 알려줘',
      original,
      {'category':'치과','location':'현재 위치'},
    );
    expect(mission, isNotNull);
    expect(mission!['requested_count'], 3);
    expect(mission['search_mode'], 'comparison');
    expect((mission['criteria'] as List).single['value'], '21:00');

    final returned = [
      original.first,
      clinic('999', '서울야간치과', '서울 강남구',
          hours:['매일 09:00-23:00']),
      original[1],
      original[2],
      clinic('11', '서울동명이치과', '서울 송파구',
          hours:['매일 09:00-23:00']),
    ];
    final selected = VerifiedPlaceFollowup.confirmed(
      original, returned, mission, nowKst: thursday,
    );
    expect(selected.map((e)=>e['name']).toList(), ['창원치과A']);
  });

  test('missing hours and wrong weekday are not confirmed', () {
    final original = [
      clinic('1','업체A','창원 A', hours:['금요일 09:00-23:00']),
      clinic('2','업체B','창원 B'),
      clinic('3','업체C','창원 C',hours:['목요일 휴무']),
    ];
    final mission = VerifiedPlaceFollowup.missionFor(
      '이 중 오늘 밤 9시까지 하는 곳은?',
      original, {'category':'치과'},
    )!;
    final selected = VerifiedPlaceFollowup.confirmed(
      original, original, mission, nowKst: thursday,
    );
    expect(selected, isEmpty);
    expect(VerifiedPlaceFollowup.openThrough(
      original[0], 21*60, nowKst: thursday), isNull);
    expect(VerifiedPlaceFollowup.openThrough(
      original[1], 21*60, nowKst: thursday), isNull);
    expect(VerifiedPlaceFollowup.openThrough(
      original[2], 21*60, nowKst: thursday), false);
  });

  test('daily hours confirm while today at 18h disproves', () {
    final daily = clinic('a','매일치과','창원시',hours:['매일 09:00-22:00']);
    final early = clinic('b','조기종료치과','창원시',
        hours:['목요일 09:00-18:00','금요일 09:00-22:00']);
    expect(VerifiedPlaceFollowup.openThrough(
      daily, 21*60, nowKst: thursday), true);
    expect(VerifiedPlaceFollowup.openThrough(
      early, 21*60, nowKst: thursday), false);
  });

  test('unmatched provider hours cannot confirm a dental clinic', () {
    final business = clinic('21','창원치과','경남 창원시',
        hours:['목요일 09:00-23:00']);
    (business['naver'] as Map<String,dynamic>)['matched'] = false;
    expect(VerifiedPlaceFollowup.openThrough(
      business, 21 * 60, nowKst: thursday), isNull);
    (business['naver'] as Map<String,dynamic>)['matched'] = true;
    (business['naver'] as Map<String,dynamic>)['page_checked'] = false;
    expect(VerifiedPlaceFollowup.openThrough(
      business, 21 * 60, nowKst: thursday), isNull);
    business['google_places'] = {
      'matched': false,
      'current_opening_hours': ['목요일 08:00-23:00'],
    };
    expect(VerifiedPlaceFollowup.openThrough(
      business, 21 * 60, nowKst: thursday), isNull);

    final mission = VerifiedPlaceFollowup.missionFor(
      '이중에서 오늘 밤 9시까지 하는 곳 알려줘',
      [business], {'category':'치과','location':'창원'},
    )!;
    expect(VerifiedPlaceFollowup.confirmed(
      [business], [business], mission, nowKst: thursday), isEmpty);
  });

  test('without closing-time proof nothing may be confirmed', () {
    final original = [
      clinic('1','창원 A','경남 창원시'),
      clinic('2','창원 B','경남 창원시'),
    ];
    final mission = VerifiedPlaceFollowup.missionFor(
      '그중 오늘 밤 9시까지 영업하는 곳',
      original, {'category':'치과'},
    )!;
    final malformed = Map<String,dynamic>.from(mission);
    malformed['criteria'] = <Map<String,dynamic>>[];
    expect(VerifiedPlaceFollowup.confirmed(
      original, original, malformed, nowKst: thursday), isEmpty);
  });

  test('colloquial prior set references remain scoped, new searches do not', () {
    final original = [clinic('1','창원 A','경남 창원시')];
    for (final utterance in [
      '방금 찾은 곳 중 오늘 밤 9시까지 하는 치과',
      '아까 찾은 곳 중 오늘 저녁 9시까지 하는 데',
      '그중 오늘 밤 9시 이후까지 하는 업체',
    ]) {
      expect(VerifiedPlaceFollowup.missionFor(
        utterance, original, {'location':'창원'}), isNotNull,
        reason: utterance);
    }
  });

  test('request for different or more places is not intercepted', () {
    final original = [clinic('1','치과A','창원')];
    for (final speech in [
      '서울에서 다른 치과 찾아줘',
      '그중 말고 다른 업체 더 찾아줘',
      '진료 받을 만한 곳을 새로 찾아줘',
    ]) {
      expect(VerifiedPlaceFollowup.missionFor(
        speech, original, {'category':'치과'}), isNull);
    }
    expect(VerifiedPlaceFollowup.missionFor(
      '그중에서 오늘 밤 9시까지 하는 데 알려줘',
      [], {'category':'치과'}), isNull);
  });

  test('generic scoped followups override Core invented nationwide search', () {
    final original = [clinic('1','창원치과','경남 창원시')];
    final parsed = {
      'intent': 'place_search',
      'search_mode': 'category_discovery',
      'response_mode': 'answer',
      'location': '서울특별시',
      'category': '치과',
      'requested_count': 9,
      'criteria': [
        {'id': 'p', 'field': 'parking_available',
         'operator': 'eq', 'value': true, 'required': true},
      ],
    };
    final scoped = VerifiedPlaceFollowup.scopeMission(
      '그 중에서 주차 가능한 곳만 알려줘', original,
      {'location': '창원시', 'category': '치과'}, parsed,
    )!;
    expect(scoped['search_mode'], 'comparison');
    expect(scoped['response_mode'], 'research');
    expect(scoped['location'], '창원시');
    expect(scoped['requested_count'], 1);
    expect((scoped['attributes'] as Map)['reuse_recent_results'], true);
    expect(VerifiedPlaceFollowup.scopeMission(
      '그중 말고 다른 곳도 더 찾아줘', original,
      {'location': '창원시'}, parsed), isNull);
  });

  test('parking followup needs matched provider and structured evidence', () {
    final original = [
      clinic('1', '창원치과A', '경남 창원시'),
      clinic('2', '창원치과B', '경남 창원시'),
    ];
    (original[0]['naver'] as Map<String,dynamic>)
        ['parking_available'] = true;
    (original[1]['naver'] as Map<String,dynamic>)
        ['parking_available'] = true;
    (original[1]['naver'] as Map<String,dynamic>)
        ['page_checked'] = false;
    final mission = {
      'criteria': [
        {'id': 'park', 'field': 'parking_available',
         'operator': 'eq', 'value': true, 'required': true},
      ],
    };
    final matching = {
      'matrix': [
        {'business_id': '1', 'business_name': '창원치과A',
         'status': 'matched',
         'criteria': [
           {'id': 'park', 'field': 'parking_available',
            'operator': 'eq', 'state': 'match',
            'source': 'naver_or_openai_web'},
         ]},
        {'business_id': '2', 'business_name': '창원치과B',
         'status': 'matched',
         'criteria': [
           {'id': 'park', 'field': 'parking_available',
            'operator': 'eq', 'state': 'match',
            'source': 'naver_or_openai_web'},
         ]},
      ],
    };
    final returned = [
      ...original,
      clinic('3', '서울치과', '서울 강남구'),
    ];
    expect(VerifiedPlaceFollowup.confirmed(
      original, returned, mission), isEmpty);
    final selected = VerifiedPlaceFollowup.confirmed(
      original, returned, mission, matching: matching);
    expect(selected.map((b) => b['name']).toList(), ['창원치과A']);
  });

  test('business opening only after 9pm is not open at 9pm', () {
    final clinicAfter = clinic('7', '야간치과', '경남 창원시',
      hours: ['목요일 21:30-23:00']);
    expect(VerifiedPlaceFollowup.openThrough(
      clinicAfter, 21 * 60, nowKst: thursday), false);
    final clinicSplit = clinic('8', '분할영업치과', '경남 창원시',
      hours: ['목요일 09:00-12:00', '목요일 18:00-22:00']);
    expect(VerifiedPlaceFollowup.openThrough(
      clinicSplit, 21 * 60, nowKst: thursday), true);
  });
}
