import 'package:flutter_test/flutter_test.dart';

import 'package:araba/services/navigation_preference_store.dart';
import 'package:araba/services/navigation_provider_service.dart';
import 'package:araba/services/navigation_service.dart';
import 'package:araba/services/araba_api.dart';
import 'package:araba/services/kakao_credential_store.dart';

class FakeNavigationPrefs extends NavigationPreferenceStore {
  FakeNavigationPrefs(this.selected);
  final NavigationMapProvider selected;
  @override
  Future<NavigationMapProvider> read() async => selected;
}

class FakeKakaoKey extends KakaoCredentialStore {
  @override
  Future<String?> read() async => 'test-kakao-key';
}

class FakeGeocoderApi extends ArabaApi {
  FakeGeocoderApi(this.places);
  final Map<String, Map<String, dynamic>> places;
  @override
  Future<Map<String, dynamic>> resolveNavigationPlace(
    String query, {String? kakaoRestApiKey}
  ) async => places[query] ??
      {'status': 'not_found', 'candidates': []};
}

Map<String, dynamic> place(String name, double lat, double lng) => {
  'status': 'resolved',
  'place': {
    'name': name,
    'latitude': lat,
    'longitude': lng,
  },
};

void main() {
  const start = NavigationPoint('창원시청', 35.228, 128.681);
  const end = NavigationPoint('부산역', 35.115, 129.041);
  const via = NavigationPoint('마산역', 35.237, 128.579);
  const route = NavigationRequest(
    origin: '창원시청',
    destination: '부산역',
  );

  test('MY settings recognize all supported maps and retain default Google', () {
    expect(NavigationMapProvider.values.length, 3);
    expect(NavigationMapProvider.fromId(null), NavigationMapProvider.google);
    expect(NavigationMapProvider.fromId('unknown'), NavigationMapProvider.google);
    expect(NavigationMapProvider.fromId('kakao'), NavigationMapProvider.kakao);
    expect(NavigationMapProvider.fromId('naver'), NavigationMapProvider.naver);
  });

  test('Kakao official direction link includes origin and destination', () {
    final url = NavigationProviderLinks.create(
      NavigationMapProvider.kakao, route,
      origin: start, destination: end,
    );
    expect(url.scheme, 'kakaomap');
    expect(url.host, 'route');
    expect(url.queryParameters['sp'], '35.228,128.681');
    expect(url.queryParameters['ep'], '35.115,129.041');
    expect(url.queryParameters['by'], 'car');
  });

  test('Kakao routes preserve waypoints and transport mode', () {
    final url = NavigationProviderLinks.create(
      NavigationMapProvider.kakao,
      const NavigationRequest(
        origin: '창원시청', destination: '부산역',
        travelMode: 'walking', waypoints: ['마산역'],
      ),
      origin: start, destination: end, via: [via],
    );
    expect(url.queryParameters['by'], 'foot');
    expect(url.queryParameters['vp'], '35.237,128.579');
    expect(
      () => NavigationProviderLinks.create(
        NavigationMapProvider.kakao,
        const NavigationRequest(
          origin: '창원시청', destination: '부산역',
          travelMode: 'transit', waypoints: ['마산역'],
        ),
        origin: start, destination: end, via: [via],
      ),
      throwsA(isA<NavigationProviderException>()),
    );
  });

  test('Naver navigation deep link sets exact coordinates and appname', () {
    final url = NavigationProviderLinks.create(
      NavigationMapProvider.naver, route,
      origin: start, destination: end, via: [via],
    );
    expect(url.scheme, 'nmap');
    expect(url.host, 'navigation');
    expect(url.queryParameters['appname'], 'kr.araba.araba');
    expect(url.queryParameters['slat'], '35.228');
    expect(url.queryParameters['slng'], '128.681');
    expect(url.queryParameters['dlat'], '35.115');
    expect(url.queryParameters['dlng'], '129.041');
    expect(url.queryParameters['v1name'], '마산역');
  });

  test('Naver current location sets destination without overriding origin', () {
    final url = NavigationProviderLinks.create(
      NavigationMapProvider.naver,
      const NavigationRequest(
        origin: '', destination: '부산역', currentLocation: true,
      ),
      origin: start, destination: end,
    );
    expect(url.queryParameters.containsKey('slat'), isFalse);
    expect(url.queryParameters['dname'], '부산역');
  });

  test('Naver transit and walking use dedicated route actions', () {
    for (final mode in ['walking', 'transit', 'bicycling']) {
      final url = NavigationProviderLinks.create(
        NavigationMapProvider.naver,
        NavigationRequest(origin: '창원시청', destination: '부산역',
            travelMode: mode),
        origin: start, destination: end,
      );
      expect(url.host, 'route');
      expect(url.path, mode == 'walking' ? '/walk' :
          mode == 'transit' ? '/public' : '/bicycle');
    }
  });


  group('Google Maps domestic driving coverage fallback', () {
    test('Korean car route switches to Naver without changing MY setting', () async {
      final service = NavigationProviderService(
        preferences: FakeNavigationPrefs(NavigationMapProvider.google),
        kakaoKeyStore: FakeKakaoKey(),
        api: FakeGeocoderApi({}),
      );
      final prepared = await service.prepare(
        const NavigationRequest(
          origin: '',
          destination: '양덕1동 행정복지센터',
          currentLocation: true,
          travelMode: 'driving',
          travelModeExplicit: true,
        ),
        destinationBusiness: {
          'name': '양덕1동 행정복지센터',
          'latitude': 35.22,
          'longitude': 128.59,
        },
      );
      expect(prepared.provider, NavigationMapProvider.naver);
      expect(prepared.uri.scheme, 'nmap');
      expect(prepared.uri.host, 'navigation');
      expect(prepared.uri.queryParameters['dname'], '양덕1동 행정복지센터');
      expect(prepared.notice, contains('네이버지도로 자동 전환'));
    });

    test('Korean walking also switches to a supported map', () {
      final choice = NavigationCoveragePolicy.choose(
        preferred: NavigationMapProvider.google,
        route: const NavigationRequest(
          origin: '창원시청',
          destination: '의창소방서',
          travelMode: 'walking',
          travelModeExplicit: true,
        ),
      );
      expect(choice.provider, NavigationMapProvider.naver);
      expect(choice.notice, contains('도보'));
    });

    test('Google Korean transit remains Google', () {
      final choice = NavigationCoveragePolicy.choose(
        preferred: NavigationMapProvider.google,
        route: const NavigationRequest(
          origin: '창원시청',
          destination: '마산역',
          travelMode: 'transit',
          travelModeExplicit: true,
        ),
      );
      expect(choice.provider, NavigationMapProvider.google);
      expect(choice.notice, isNull);
    });

    test('explicitly overseas destinations keep Google driving', () {
      for (final destination in ['Tokyo Station', '도쿄역', '런던 시청']) {
        final choice = NavigationCoveragePolicy.choose(
          preferred: NavigationMapProvider.google,
          route: NavigationRequest(
            origin: 'Tokyo Station',
            destination: destination,
            travelMode: 'driving',
          ),
        );
        expect(choice.provider, NavigationMapProvider.google,
            reason: destination);
        expect(choice.notice, isNull);
      }
    });

    test('known overseas coordinates override Korean-script location names', () {
      final choice = NavigationCoveragePolicy.choose(
        preferred: NavigationMapProvider.google,
        route: const NavigationRequest(
          origin: '여기',
          destination: '한글 상호명',
          travelMode: 'driving',
        ),
        destinationBusiness: {
          'latitude': 35.68,
          'longitude': 139.77,
        },
      );
      expect(choice.provider, NavigationMapProvider.google);
    });

    test('MY Naver and Kakao remain untouched for Korean driving', () {
      for (final provider in [
        NavigationMapProvider.naver,
        NavigationMapProvider.kakao,
      ]) {
        final choice = NavigationCoveragePolicy.choose(
          preferred: provider,
          route: const NavigationRequest(
            origin: '창원시청',
            destination: '마산역',
            travelMode: 'driving',
          ),
        );
        expect(choice.provider, provider);
        expect(choice.notice, isNull);
      }
    });

    test('Google Korean non-driving transit still uses transit URL', () async {
      final service = NavigationProviderService(
        preferences: FakeNavigationPrefs(NavigationMapProvider.google),
        kakaoKeyStore: FakeKakaoKey(),
        api: FakeGeocoderApi({}),
      );
      final prepared = await service.prepare(
        const NavigationRequest(
          origin: '창원시청',
          destination: '부산역',
          travelMode: 'transit',
          travelModeExplicit: true,
        ),
      );
      expect(prepared.provider, NavigationMapProvider.google);
      expect(prepared.uri.queryParameters['travelmode'], 'transit');
    });
  });

  test('MY selection controls real route preparation', () async {
    final fake = FakeGeocoderApi({
      '창원시청': place('창원시청', 35.228, 128.681),
      '부산역': place('부산역', 35.115, 129.041),
    });
    for (final provider in [
      NavigationMapProvider.naver, NavigationMapProvider.kakao,
    ]) {
      final service = NavigationProviderService(
        api: fake,
        preferences: FakeNavigationPrefs(provider),
        kakaoKeyStore: FakeKakaoKey(),
      );
      final prepared = await service.prepare(route);
      expect(prepared.provider, provider);
      expect(prepared.uri.host, provider == NavigationMapProvider.naver
          ? 'navigation' : 'route');
      expect(prepared.uri.scheme, provider == NavigationMapProvider.naver
          ? 'nmap' : 'kakaomap');
    }
  });

  test('ambiguous map place is never silently auto-selected', () async {
    final service = NavigationProviderService(
      api: FakeGeocoderApi({
        '창원시청': {'status': 'ambiguous', 'candidates': []},
      }),
      preferences: FakeNavigationPrefs(NavigationMapProvider.naver),
      kakaoKeyStore: FakeKakaoKey(),
    );
    expect(
      () => service.prepare(route),
      throwsA(isA<NavigationProviderException>()),
    );
  });

  test('verified business coordinates bypass name guessing', () {
    final point = NavigationPoint.fromBusiness({
      'name': '상점', 'y': '35.228', 'x': '128.681',
    });
    expect(point?.latitude, 35.228);
    expect(point?.longitude, 128.681);
    expect(NavigationPoint.fromBusiness({'name': '정보없는 상점'}), isNull);
  });
}
