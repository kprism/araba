import 'package:araba/services/place_result_scope.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('three places requested never becomes nine cards', () {
    final input = List.generate(9, (index) => {
      'id': '${index + 1}',
      'name': '치과${index + 1}',
      'address': '경남 창원시 의창구 중동',
    });
    final picked = PlaceResultScope.firstResults(
      {'requested_count': 3}, input,
    );
    expect(picked.length, 3);
    expect(picked.last['id'], '3');
    expect(input.length, 9);
  });

  test('followup cannot substitute out of region providers or new businesses', () {
    final original = [
      {'id': '1', 'name': '창원치과1', 'address': '경남 창원시 1'},
      {'id': '2', 'name': '창원치과2', 'address': '경남 창원시 2'},
      {'id': '3', 'name': '창원치과3', 'address': '경남 창원시 3'},
    ];
    final result = PlaceResultScope.followup(original, [
      {'id': '2', 'name': '창원치과2', 'address': '경남 창원시 2',
        'naver': {'opening_hours': ['목요일 09:00-21:00']}},
      {'id': '4', 'name': '서울치과', 'address': '서울 강남구'},
      {'id': '1', 'name': '서울치과2', 'address': '서울 강남구'},
      {'id': '2', 'name': '창원치과2', 'address': '경남 창원시 2'},
    ]);
    expect(result.length, 1);
    expect(result.single['name'], '창원치과2');
    expect(result.single['address'], contains('창원시'));
  });

  test('unknown business facts cannot introduce an unverified new provider', () {
    expect(PlaceResultScope.followup([
      {'id': 'a', 'name': '창원치과', 'address': '경남 창원시'},
    ], [
      {'id': 'b', 'name': '서울치과', 'address': '서울시'},
    ]), isEmpty);
  });
}
