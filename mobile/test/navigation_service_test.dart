import 'package:flutter_test/flutter_test.dart';
import 'package:araba/services/navigation_service.dart';

void main() {
  group('navigation intent (all destinations, not specific facilities)', () {
    test('speech annotations never become a destination or origin', () {
      final utterance =
          '어, 여기서창원시 의창소방서까지 가는 길 좀 알려줘 [cough] [cough]';
      final result = NavigationRequest.tryParse(utterance);
      expect(result, isNotNull);
      expect(result!.currentLocation, isTrue);
      expect(result.origin, isEmpty);
      expect(result.destination, '창원시 의창소방서');
      expect(result.destination.contains('[cough]'), isFalse);
    });

    test('location-appropriate pronunciation works with spaced here', () {
      final result = NavigationRequest.tryParse(
        '여기서 창원시 의창소방서까지 길을 알려줘',
      );
      expect(result?.destination, '창원시 의창소방서');
      expect(result?.currentLocation, isTrue);
    });

    test('named origin -> named destination', () {
      final result = NavigationRequest.tryParse(
        '창원시청에서 부산역까지 가는 길 알려줘',
      );
      expect(result, isNotNull);
      expect(result!.origin, '창원시청');
      expect(result.destination, '부산역');
      expect(result.currentLocation, isFalse);
      final uri = NavigationLauncher.directionsUri(result);
      expect(uri.queryParameters['origin'], '창원시청');
      expect(uri.queryParameters['destination'], '부산역');
      expect(uri.queryParameters['travelmode'], 'driving');
    });

    test('here -> any destination uses real device coordinates', () {
      final result = NavigationRequest.tryParse(
        '지금 여기서 북면고등학교까지 길 안내해줘',
      );
      expect(result, isNotNull);
      expect(result!.currentLocation, isTrue);
      expect(result.destination, '북면고등학교');
      expect(
        () => NavigationLauncher.directionsUri(result),
        throwsArgumentError,
      );
      final uri = NavigationLauncher.directionsUri(
        result, latitude: 35.22, longitude: 128.68,
      );
      expect(uri.queryParameters['origin'], '35.22,128.68');
      expect(uri.queryParameters['destination'], '북면고등학교');
    });

    test('destination only defaults to current GPS location', () {
      final result = NavigationRequest.tryParse(
        '북면고등학교 까지 가는 길 알려줘',
      );
      expect(result?.currentLocation, isTrue);
      expect(result?.destination, '북면고등학교');
    });

    test('destination only with go-to wording', () {
      expect(
        NavigationRequest.tryParse('부산역으로 안내해줘')?.destination,
        '부산역',
      );
      expect(
        NavigationRequest.tryParse('북면고등학교 가는 길 알려줘')
            ?.destination,
        '북면고등학교',
      );
    });

    test('specific origin to transit destination', () {
      final result = NavigationRequest.tryParse(
        '서울역에서 인천공항까지 대중교통으로 가는 길 찾아줘',
      );
      expect(result?.origin, '서울역');
      expect(result?.destination, '인천공항');
      expect(result?.travelMode, 'transit');
    });

    test('walking and cycling transport preferences', () {
      expect(
        NavigationRequest.tryParse('창원시청에서 용지호수까지 도보 길찾기')
            ?.travelMode,
        'walking',
      );
      expect(
        NavigationRequest.tryParse('창원시청에서 용지호수까지 자전거 경로')
            ?.travelMode,
        'bicycling',
      );
    });

    test('via a waypoint preserved in map directions URI', () {
      final result = NavigationRequest.tryParse(
        '경남도청에서 창원시청을 거쳐 마산역까지 가는 길 알려줘',
      );
      expect(result?.origin, '경남도청');
      expect(result?.destination, '마산역');
      expect(result?.waypoints, ['창원시청']);
      final uri = NavigationLauncher.directionsUri(result!);
      expect(uri.queryParameters['waypoints'], '창원시청');
    });

    test('venue categories have no bearing on the route', () {
      for (final destination in ['치과', '식당', '학교', '주유소', '창원시 의창구 중동로 47']) {
        final request = NavigationRequest.tryParse(
          '현재 위치에서 $destination까지 내비게이션 켜줘',
        );
        expect(request?.destination, destination);
        expect(request?.currentLocation, isTrue);
      }
    });

    test('follow-up start here recognized without overwriting destination', () {
      final original = NavigationRequest.tryParse(
        '창원시청에서 부산역까지 경로 보여줘',
      )!;
      expect(NavigationRequest.isCurrentOriginFollowUp('지금 여기서 출발해'), isTrue);
      final updated = original.fromCurrentLocation();
      expect(updated.destination, original.destination);
      expect(updated.currentLocation, isTrue);
    });

    test('similar businesses and non-movement questions are not hijacked', () {
      expect(NavigationRequest.tryParse('창원시 중동 치과 5곳 찾아줘'), isNull);
      expect(NavigationRequest.tryParse('카페에서 케이크까지 판매하는지 확인해 줘'), isNull);
      expect(NavigationRequest.tryParse('버스 가격이 얼마야'), isNull);
    });

    test('do not confuse start and destination or invent GPS', () {
      final request = NavigationRequest.tryParse(
        '창원시청에서 부산역까지 길 알려줘',
      )!;
      expect(request.currentLocation, false);
      final uri = NavigationLauncher.directionsUri(request);
      expect(uri.queryParameters['origin'], '창원시청');
      expect(uri.queryParameters['destination'], '부산역');
    });
  });
}
