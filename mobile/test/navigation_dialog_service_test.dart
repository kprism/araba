import 'package:flutter_test/flutter_test.dart';
import 'package:araba/services/navigation_dialog_service.dart';
import 'package:araba/services/navigation_service.dart';

void main() {
  group('multi-turn navigation task state', () {
    test('incomplete first instruction preserves navigation intent', () {
      final dialog = NavigationDialogState();
      final initial = dialog.interpret('길 좀 알려줘');
      expect(initial, isNotNull);
      expect(initial!.route, isNull);
      expect(dialog.waitingForDestination, isTrue);
      final followUp = dialog.interpret('북면고등학교');
      expect(followUp?.route, isNull);
      expect(dialog.waitingForTravelMode, isTrue);
      expect(dialog.lastRoute?.destination, '북면고등학교');
      expect(dialog.lastRoute?.currentLocation, isTrue);
      final byCar = dialog.interpret('자동차');
      expect(byCar?.route?.destination, '북면고등학교');
      expect(byCar?.route?.travelMode, 'driving');
    });

    test('cough tags in corrected navigation speech cannot replace endpoint', () {
      final dialog = NavigationDialogState();
      final first = dialog.interpret(
        '어, 여기서창원시 의창소방서까지 자동차로 가는 길 알려줘 [cough]',
      );
      expect(first?.route?.destination, '창원시 의창소방서');
      final followUp = dialog.interpret(
        '아니, 창원시 의창소방서로 안내해줘 [cough] [cough]',
      );
      expect(followUp?.route?.destination, '창원시 의창소방서');
      expect(followUp?.route?.currentLocation, isTrue);
    });

    test('destination correction is still navigation, not shop discovery', () {
      final dialog = NavigationDialogState();
      final original = dialog.interpret(
        '지금 여기서 복면고등학교까지 자동차로 가는 길 알려줘',
      );
      expect(original?.route?.destination, '복면고등학교');
      final corrected = dialog.interpret('아니, 북면고등학교로 가줘');
      expect(corrected?.route?.destination, '북면고등학교');
      expect(corrected?.route?.currentLocation, isTrue);
    });

    test('last correction wins when speech includes two place names', () {
      final dialog = NavigationDialogState();
      dialog.interpret('지금 여기서 북면고등학교까지 자동차로 길 알려줘');
      final corrected = dialog.interpret(
        '북면고등학교 아니고 북면초등학교야',
      );
      expect(corrected?.route?.destination, '북면초등학교');
    });

    test('explicit destination label corrects earlier route', () {
      final dialog = NavigationDialogState();
      dialog.interpret('창원시청에서 부산역까지 자동차로 길 알려줘');
      final corrected = dialog.interpret('목적지는 북면고등학교야');
      expect(corrected?.route?.origin, '창원시청');
      expect(corrected?.route?.destination, '북면고등학교');
      expect(corrected?.route?.currentLocation, isFalse);
    });

    test('current location follow-up carries corrected destination', () {
      final dialog = NavigationDialogState();
      dialog.interpret('창원시청에서 부산역까지 자동차로 길 알려줘');
      dialog.interpret('아니, 북면고등학교로 가줘');
      final origin = dialog.interpret('지금 여기서 출발해');
      expect(origin?.route?.currentLocation, isTrue);
      expect(origin?.route?.destination, '북면고등학교');
    });

    test('incomplete route, then origin, then destination', () {
      final dialog = NavigationDialogState();
      dialog.interpret('네비게이션 켜줘');
      final origin = dialog.interpret('출발지는 창원시청');
      expect(origin?.route, isNull);
      expect(dialog.waitingForDestination, isTrue);
      final destination = dialog.interpret('도착지는 부산역이야');
      expect(destination?.route, isNull);
      expect(dialog.waitingForTravelMode, isTrue);
      final transit = dialog.interpret('대중교통');
      expect(transit?.route?.origin, '창원시청');
      expect(transit?.route?.destination, '부산역');
      expect(transit?.route?.currentLocation, isFalse);
      expect(transit?.route?.travelMode, 'transit');
    });

    test('failed provider keeps route corrections in navigation flow', () {
      final dialog = NavigationDialogState();
      dialog.interpret('지금 여기서 마산역까지 자동차로 내비 켜줘');
      dialog.awaitCorrection();
      final correction = dialog.interpret('북면고등학교');
      expect(correction?.route?.destination, '북면고등학교');
      expect(correction?.route?.currentLocation, isTrue);
    });

    test('a new unrelated shop search escapes pending navigation', () {
      final dialog = NavigationDialogState();
      dialog.interpret('길 알려줘');
      expect(dialog.interpret('창원시 중동 치과 5곳 찾아줘'), isNull);
      expect(dialog.waitingForDestination, isFalse);
      expect(dialog.interpret('카페에서 케이크를 팔아?'), isNull);
    });

    test('restaurant booking after a failed navigation is not a destination', () {
      final dialog = NavigationDialogState();
      dialog.interpret('지금 여기서 창원시청까지 자동차로 길 알려줘');
      dialog.awaitCorrection();
      expect(
        dialog.interpret(
          '이번 주 토요일 저녁 6시에 성인 4명이 식사할 수 있는 창원 상남동 '
          '소고기 식당을 찾아서 예약 가능한지 확인해줘',
        ),
        isNull,
      );
      expect(dialog.waitingForDestination, isFalse);
      expect(dialog.interpret('창원시청에서 부산역까지 자동차로 길 안내해줘')
          ?.route?.destination, '부산역');
    });

    test('destination corrected during candidates never becomes merchant search', () {
      final dialog = NavigationDialogState();
      final first = dialog.interpret(
        '어 여기서- 창원 대산 고등학교 가는 길 알려줘',
      );
      expect(first?.route, isNull);
      expect(dialog.lastRoute?.destination, '창원 대산 고등학교');
      final byCar = dialog.interpret('자동차');
      expect(byCar?.route?.travelMode, 'driving');

      // The backend provided off-region candidates. HomeScreen calls
      // awaitCorrection() instead of letting the next utterance fall to AI.
      dialog.awaitCorrection();
      final corrected = dialog.interpret('대산고등학교로 갈 거야');
      expect(corrected?.route?.destination, '대산고등학교');
      expect(corrected?.route?.travelMode, 'driving');
      expect(corrected?.route?.currentLocation, isTrue);
    });

    test('new route can replace old route while previous destination is unresolved', () {
      final dialog = NavigationDialogState();
      dialog.interpret('창원시청에서 부산역까지 자동차로 길 알려줘');
      dialog.awaitCorrection();
      final next = dialog.interpret('경남도청에서 마산역까지 대중교통으로 길 알려줘');
      expect(next?.route?.origin, '경남도청');
      expect(next?.route?.destination, '마산역');
      expect(next?.route?.travelMode, 'transit');
    });

    test('ordinary request after an old route never hijacked', () {
      final dialog = NavigationDialogState();
      dialog.interpret('창원시청에서 부산역까지 자동차로 길 알려줘');
      expect(dialog.interpret('창원시청 식당 추천해줘'), isNull);
      expect(dialog.interpret('이건 얼마야?'), isNull);
    });

    test('a one-turn route and movement mode work across all place types', () {
      for (final destination in [
        '북면고등학교',
        '창원시청',
        '중동치과',
        '부산역',
        '인천공항',
      ]) {
        final dialog = NavigationDialogState();
        final result = dialog.interpret(
          '현재 위치에서 $destination까지 자동차로 길 알려줘',
        );
        expect(result?.route?.destination, destination);
        expect(result?.route?.currentLocation, isTrue);
      }
    });

    test('no invented destination after vague intent', () {
      final dialog = NavigationDialogState();
      expect(dialog.interpret('길 알려줘')?.route, isNull);
      expect(dialog.interpret('어디로 가야 하지?')?.route, isNull);
    });

    test('distance-time or generic travel question is not venue search', () {
      expect(NavigationRequest.hasNavigationIntent('창원시청까지 얼마나 걸려?'),
          isTrue);
      expect(NavigationRequest.tryParse('창원시청까지 얼마나 걸려?')
          ?.destination, '창원시청');
    });
  });
}
