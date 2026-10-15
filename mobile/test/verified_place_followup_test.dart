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

  test('typed and spoken generic conditions are parsed before GPT Core', () {
    final original = [clinic('1', '치과A', '경남 창원시')];
    for (final speech in [
      '그중 주차 가능한 곳 알려줘',
      '그 중 가장 가까운 곳은?',
      '그중에서 가장 저렴한 곳 알려줘',
    ]) {
      final result = VerifiedPlaceFollowup.missionFor(
        speech, original, {'category': '치과', 'location': '창원'},
      );
      expect(result, isNotNull, reason: speech);
      expect(result!['search_mode'], 'comparison');
      expect((result['criteria'] as List), hasLength(1));
    }
    final compound = VerifiedPlaceFollowup.missionFor(
      '그중 오늘 밤 9시까지 진료하면서 주차 가능한 곳',
      original, {'category': '치과', 'location': '창원'},
    )!;
    expect((compound['criteria'] as List), hasLength(2));
  });

  test('Korean evening nine and 21:00 are the same numeric time', () {
    final original = [clinic('1','야간치과','경남 창원시')];
    for (final utterance in [
      '그중 오늘 밤 9시까지 하는 곳 알려줘',
      '이중에서 오늘 오후 9시까지 진료하는 곳',
      '그중 21시까지 하는 곳',
    ]) {
      final parsed = VerifiedPlaceFollowup.missionFor(
        utterance, original, {'category':'치과','location':'창원'},
      )!;
      expect((parsed['criteria'] as List).first['value'], '21:00',
          reason: utterance);
    }
  });

  test('verified English Thursday PM schedule qualifies at 21', () {
    final clinicGoogle = clinic('g1', '창원야간치과', '창원시');
    clinicGoogle['google_places'] = {
      'matched': true,
      'current_opening_hours': [
        'Thursday: 9:00 AM – 9:30 PM',
        'Friday: 9:00 AM – 5:00 PM',
      ],
    };
    final rows = VerifiedPlaceFollowup.normalizedHours(clinicGoogle);
    final thursdayHours = rows.where((r) => r['weekday'] == '목요일').first;
    expect(thursdayHours['start_time'], '09:00');
    expect(thursdayHours['end_time'], '21:30');
    expect(VerifiedPlaceFollowup.openThrough(
      clinicGoogle, 1260, nowKst: thursday), true);
    expect(VerifiedPlaceFollowup.openThrough(
      clinicGoogle, 1320, nowKst: thursday), false);
  });

  test('Korean PM to PM and server structured hours are normalized', () {
    final clinicKorean = clinic('k1','한글야간치과','창원시',
        hours: ['목요일 오전 9:00~오후 9:00']);
    expect(VerifiedPlaceFollowup.openThrough(
      clinicKorean, 1260, nowKst: thursday), true);
    clinicKorean['structured_opening_hours'] = [{
      'weekday': '목요일', 'start_time': '09:00', 'end_time': '21:30',
      'start_minute': 540, 'end_minute': 1290,
      'source': 'naver_verified_page',
    }];
    expect(VerifiedPlaceFollowup.openThrough(
      clinicKorean, 1290, nowKst: thursday), true);
  });

  test('unmatched provider and late opening are never recommended', () {
    final doctor = clinic('p1','증거없는치과','창원시');
    doctor['google_places'] = {
      'matched': false,
      'current_opening_hours': ['Thursday: 9:00 AM – 11:00 PM'],
    };
    expect(VerifiedPlaceFollowup.openThrough(
      doctor, 1260, nowKst: thursday), isNull);

    final opensLate = clinic('p2','늦게여는치과','창원시',
        hours: ['목요일 21:30-23:00']);
    expect(VerifiedPlaceFollowup.openThrough(
      opensLate, 1260, nowKst: thursday), false);
  });

  test('structured normalized weekday schedule handles English weekly range', () {
    final doctor = clinic('range','매일치과','창원시',
      hours: ['Mo-Fr 09:00-21:30']);
    expect(VerifiedPlaceFollowup.openThrough(
      doctor, 1260, nowKst: thursday), true);
  });

  test('month and Thursday grouped hours qualify at 19', () {
    final b = clinic('mon-thu','목요일야간치과','창원시',
      hours: ['월·목 09:00-19:00']);
    expect(VerifiedPlaceFollowup.openThrough(
      b, 19 * 60, nowKst: thursday), true);
    expect(VerifiedPlaceFollowup.openThrough(
      b, 19 * 60 + 30, nowKst: thursday), false);
    final c = clinic('mon-thu-dot','목요일19시치과','창원시',
      hours: ['월.목 09:00-19:00']);
    expect(VerifiedPlaceFollowup.openThrough(
      c, 19 * 60, nowKst: thursday), true);
  });

  test('explicit Thursday seven is stored as Thursday nineteen', () {
    final candidates = [clinic('1','목요일19시치과','창원시',
        hours: ['월·목 09:00-19:00'])];
    final request = VerifiedPlaceFollowup.missionFor(
      '그중 목요일 7시까지 진료하는 곳은?',
      candidates,
      {'location':'창원시','category':'치과'},
    )!;
    final criteria = (request['criteria'] as List).single;
    expect(criteria['day'], '목요일');
    expect(criteria['value'], '19:00');
    expect(VerifiedPlaceFollowup.confirmed(
      candidates,candidates,request,nowKst: thursday,
    ).length, 1);
  });

  test('unverified businesses nested in matching are evaluated in scope', () {
    final a = clinic('a','치과A','경남 창원시',hours:['목요일 09:00-18:00']);
    final b = clinic('b','치과B','경남 창원시',hours:['월·목 09:00-19:00']);
    final c = clinic('c','서울치과','서울특별시');
    final response = <String,dynamic>{
      'businesses': [a],
      'matching': {
        'unverified_businesses':[b,c],
        'excluded_businesses':[],
      },
    };
    final returned = VerifiedPlaceFollowup.enrichedCandidates(response);
    expect(returned.length, 3);
    final mission = VerifiedPlaceFollowup.missionFor(
      '그중 목요일 7시까지 하는 곳?',
      [a,b], {'location':'창원시','category':'치과'},
    )!;
    final safe = VerifiedPlaceFollowup.confirmed(
      [a,b], returned, mission, nowKst: thursday,
    );
    expect(safe.map((item)=>item['name']).toList(), ['치과B']);
  });

  test('voice Korean 아홉 시 and 숫자 9시 both become 21:00', () {
    final original = [
      clinic('1','카페A','창원',hours:['목요일 09:00-21:30']),
    ];
    for (final speech in [
      '어, 이중에 오늘 밤 아홉 시까지 하는 카페를 찾아줘',
      '그중 오늘 밤 9시까지 영업하는 카페만 알려줘',
      '그중 목요일 오후 아홉 시까지 여는 곳',
      '그중 목요일 21시까지 영업하는 곳',
    ]) {
      final mission = VerifiedPlaceFollowup.missionFor(
        speech, original, {'category':'카페','location':'창원'},
      );
      expect(mission, isNotNull, reason: speech);
      expect((mission!['criteria'] as List).first['value'],'21:00',
        reason: speech);
    }
    final halfHour = VerifiedPlaceFollowup.missionFor(
      '그중 오늘 밤 아홉 시 반까지 영업하는 곳',
      original, {'category':'카페'},
    );
    expect((halfHour!['criteria'] as List).first['value'],'21:30');
  });

  test('two identity verified web cafe hours qualify without Naver match', () {
    Map<String,dynamic> webCafe(String id, String name, String time) => {
      'id':id, 'name':name, 'address':'경남 창원시 성산구',
      'naver':{'matched':false, 'page_checked':false,
        'opening_hours':['목요일 09:00-$time'],
        'opening_hours_source':'openai_web'},
      'openai_web':{
        'matched':true,'identity_confirmed':true,
        'opening_hours_found':true,
        'sources':['https://example.com/verified/$id'],
        'opening_hours':['목요일 09:00-$time'],
      },
    };
    final original = [
      webCafe('c1','카페A','22:00'),
      webCafe('c2','카페B','21:30'),
      clinic('c3','카페C','경남 창원시 성산구'),
    ];
    final mission = VerifiedPlaceFollowup.missionFor(
      '어 이중에 오늘 밤 아홉 시까지 하는 카페를 찾아줘',
      original, {'category':'카페','location':'창원시'},
    )!;
    final selected = VerifiedPlaceFollowup.confirmed(
      original, [
        ...original,
        webCafe('outsider','서울카페','23:00'),
      ], mission, nowKst: thursday,
    );
    expect(selected.map((e)=>e['name']).toList(), ['카페A','카페B']);
    expect(VerifiedPlaceFollowup.openThrough(
      original[2], 1260, nowKst: thursday), isNull);
  });

  test('model web hours without independent sources never qualify', () {
    final cafe = clinic('bad','추측카페','경남 창원시',hours:[]);
    cafe['openai_web']={
      'matched':true,'identity_confirmed':true,
      'opening_hours_found':true,'sources':[],
      'opening_hours':['목요일 09:00-23:00'],
    };
    expect(VerifiedPlaceFollowup.openThrough(
      cafe, 1260, nowKst: thursday), isNull);
  });

  test('fresh ARABA weekly fact can answer without provider response', () {
    final cafe = clinic('graph','기록카페','경남 창원시',hours:[]);
    cafe['araba_cache_hit']=true;
    cafe['araba_fresh_facts']=['weekly_opening_hours'];
    cafe['weekly_opening_hours']=[{
      'weekday':'목요일','status':'open',
      'source':'openai_web_verified',
      'sessions':[{
        'start_time':'09:00','end_time':'22:00',
        'source':'openai_web_verified',
      }],
    }];
    (cafe['naver'] as Map)['matched']=false;
    (cafe['naver'] as Map)['page_checked']=false;
    expect(VerifiedPlaceFollowup.openThrough(
      cafe, 1260, nowKst: thursday), true);
    cafe['araba_fresh_facts']=[];
    expect(VerifiedPlaceFollowup.openThrough(
      cafe, 1260, nowKst: thursday), isNull);
  });
}
