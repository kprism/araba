import 'package:flutter_test/flutter_test.dart';
import 'package:araba/services/navigation_dialog_service.dart';
import 'package:araba/services/navigation_service.dart';
import 'package:araba/services/navigation_preference_store.dart';
import 'package:araba/services/navigation_provider_service.dart';

void main() {
  group('required transport confirmation', () {
    test('unqualified route asks exactly once before opening map', () {
      final dialog = NavigationDialogState();
      final first = dialog.interpret(
        '여기서 창원중동 유니시티3단지아파트까지 가는 길 알려줘',
      );
      expect(first, isNotNull);
      expect(first!.route, isNull);
      expect(first.question, contains('자동차'));
      expect(first.question, contains('대중교통'));
      expect(first.question, contains('도보'));
      expect(dialog.waitingForTravelMode, isTrue);
      expect(dialog.lastRoute?.destination, '창원중동 유니시티3단지아파트');

      final selected = dialog.interpret('자동차');
      expect(selected?.route?.travelMode, 'driving');
      expect(selected?.route?.travelModeExplicit, isTrue);
      expect(selected?.route?.currentLocation, isTrue);
      expect(dialog.waitingForTravelMode, isFalse);
    });

    test('public transit answer keeps origin and destination', () {
      final dialog = NavigationDialogState();
      dialog.interpret('창원시청에서 부산역까지 길 알려줘');
      final answer = dialog.interpret('대중교통으로 갈게');
      expect(answer?.route?.origin, '창원시청');
      expect(answer?.route?.destination, '부산역');
      expect(answer?.route?.travelMode, 'transit');
      expect(answer?.route?.travelModeExplicit, isTrue);
    });

    test('walking answer carries the exact destination', () {
      final dialog = NavigationDialogState();
      dialog.interpret('여기서 한마음아파트까지 길 안내해줘');
      final answer = dialog.interpret('걸어서');
      expect(answer?.route?.travelMode, 'walking');
      expect(answer?.route?.destination, '한마음아파트');
    });

    test('car already expressed in first message skips question', () {
      for (final command in [
        '창원시청에서 부산역까지 자동차로 가는 길 알려줘',
        '창원시청에서 부산역까지 자가용으로 안내해 줘',
        '창원시청에서 부산역까지 차로 가는 길 알려줘',
      ]) {
        final dialog = NavigationDialogState();
        final answer = dialog.interpret(command);
        expect(answer?.route?.travelMode, 'driving', reason: command);
        expect(dialog.waitingForTravelMode, isFalse);
      }
    });

    test('public transit already expressed skips question', () {
      final dialog = NavigationDialogState();
      final answer = dialog.interpret(
        '창원시청에서 부산역까지 대중교통으로 가는 길 알려줘',
      );
      expect(answer?.route?.travelMode, 'transit');
      expect(answer?.question, isNull);
    });

    test('explicit walking already expressed skips question', () {
      final dialog = NavigationDialogState();
      final answer = dialog.interpret(
        '창원시청에서 용지호수까지 걸어서 가는 길 알려줘',
      );
      expect(answer?.route?.travelMode, 'walking');
      expect(answer?.question, isNull);
    });

    test('transport mention in place name does not select a route mode', () {
      final dialog = NavigationDialogState();
      final answer = dialog.interpret('버스정류장까지 길 알려줘');
      expect(answer?.route, isNull);
      expect(dialog.waitingForTravelMode, isTrue);
    });

    test('speech correction prioritizes final transportation preference', () {
      final dialog = NavigationDialogState();
      final choice = dialog.interpret(
        '창원시청에서 부산역까지 대중교통 말고 자동차로 안내해줘',
      );
      expect(choice?.route?.travelMode, 'driving');
    });

    test('new unrelated search exits mode prompt', () {
      final dialog = NavigationDialogState();
      dialog.interpret('여기서 부산역까지 길 알려줘');
      expect(dialog.waitingForTravelMode, isTrue);
      expect(dialog.interpret('중동에 치과 다섯 곳 찾아줘'), isNull);
      expect(dialog.waitingForTravelMode, isFalse);
    });

    test('incomplete destination prompts before asking travel mode', () {
      final dialog = NavigationDialogState();
      final first = dialog.interpret('길 좀 알려줘');
      expect(first?.route, isNull);
      expect(dialog.waitingForDestination, isTrue);
      expect(dialog.waitingForTravelMode, isFalse);
      final second = dialog.interpret('창원시청');
      expect(second?.route, isNull);
      expect(dialog.waitingForTravelMode, isTrue);
      final third = dialog.interpret('대중교통');
      expect(third?.route?.destination, '창원시청');
      expect(third?.route?.travelMode, 'transit');
    });

    test('no unsupported fallback between requested travel modes', () {
      const route = NavigationRequest(
        origin: '창원시청',
        destination: '부산역',
        travelMode: 'driving',
        travelModeExplicit: true,
      );
      final google = NavigationLauncher.directionsUri(route);
      expect(google.queryParameters['travelmode'], 'driving');
      final kakao = NavigationProviderLinks.create(
        NavigationMapProvider.kakao,
        route,
        origin: const NavigationPoint('시청', 35.228, 128.681),
        destination: const NavigationPoint('부산역', 35.115, 129.041),
      );
      expect(kakao.queryParameters['by'], 'car');
      final naver = NavigationProviderLinks.create(
        NavigationMapProvider.naver,
        route,
        origin: const NavigationPoint('시청', 35.228, 128.681),
        destination: const NavigationPoint('부산역', 35.115, 129.041),
      );
      expect(naver.host, 'navigation');
    });

    test('Naver transit and walking from here contain real origin GPS', () {
      for (final mode in ['transit', 'walking']) {
        final url = NavigationProviderLinks.create(
          NavigationMapProvider.naver,
          NavigationRequest(
            origin: '',
            destination: '부산역',
            travelMode: mode,
            travelModeExplicit: true,
            currentLocation: true,
          ),
          origin: const NavigationPoint('현재 위치', 35.228, 128.681),
          destination: const NavigationPoint('부산역', 35.115, 129.041),
        );
        expect(url.queryParameters['slat'], '35.228');
        expect(url.queryParameters['slng'], '128.681');
        expect(url.path, mode == 'transit' ? '/public' : '/walk');
      }
    });

    test('mode stays selected when origin or destination is corrected', () {
      final dialog = NavigationDialogState();
      dialog.interpret('창원시청에서 부산역까지 길 알려줘');
      dialog.interpret('대중교통');
      final correction = dialog.interpret('목적지는 마산역이야');
      expect(correction?.route?.travelMode, 'transit');
      expect(correction?.route?.destination, '마산역');
      expect(dialog.waitingForTravelMode, isFalse);
    });
  });
}
