import 'package:flutter/foundation.dart';
import 'package:url_launcher/url_launcher.dart';

import 'araba_api.dart';
import 'device_location_service.dart';
import 'kakao_credential_store.dart';
import 'navigation_preference_store.dart';
import 'navigation_service.dart';

class NavigationProviderException implements Exception {
  const NavigationProviderException(this.message);
  final String message;
  @override
  String toString() => message;
}

class NavigationPoint {
  const NavigationPoint(this.name, this.latitude, this.longitude);
  final String name;
  final double latitude;
  final double longitude;

  static NavigationPoint? fromBusiness(Map<String, dynamic> business) {
    final lat = double.tryParse((business['latitude'] ?? business['y'])?.toString() ?? '');
    final lon = double.tryParse((business['longitude'] ?? business['x'])?.toString() ?? '');
    if (lat == null || lon == null || lat < 33 || lat > 39 || lon < 124 || lon > 132) {
      return null;
    }
    return NavigationPoint(business['name']?.toString() ?? '', lat, lon);
  }

  static NavigationPoint? fromCoordinate(String label) {
    final parts = label.split(',');
    if (parts.length != 2) return null;
    final lat = double.tryParse(parts.first.trim());
    final lon = double.tryParse(parts.last.trim());
    if (lat == null || lon == null || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
      return null;
    }
    return NavigationPoint(label, lat, lon);
  }

  String get kakaoSegment => '${name.replaceAll(',', ' ')},$latitude,$longitude';
}

class NavigationProviderLinks {
  static Uri create(
    NavigationMapProvider provider,
    NavigationRequest route, {
    required NavigationPoint origin,
    required NavigationPoint destination,
    List<NavigationPoint> via = const [],
  }) {
    if (provider == NavigationMapProvider.google) {
      return NavigationLauncher.directionsUri(
        route,
        latitude: route.currentLocation ? origin.latitude : null,
        longitude: route.currentLocation ? origin.longitude : null,
      );
    }
    if (via.length > 5) {
      throw const NavigationProviderException('경유지는 최대 5곳까지입니다.');
    }
    if (route.travelMode == 'transit' && via.isNotEmpty) {
      throw const NavigationProviderException(
        '대중교통 길찾기는 경유지를 함께 지정할 수 없어요.',
      );
    }
    if (provider == NavigationMapProvider.kakao) {
      final mode = switch (route.travelMode) {
        'walking' => 'walk',
        'transit' => 'traffic',
        'bicycling' => 'bicycle',
        _ => 'car',
      };
      final segments = [origin, ...via, destination]
          .map((point) => point.kakaoSegment).join('/');
      return Uri.https('map.kakao.com', '/link/by/$mode/$segments');
    }

    final params = <String, String>{
      if (!route.currentLocation) 'slat': origin.latitude.toString(),
      if (!route.currentLocation) 'slng': origin.longitude.toString(),
      if (!route.currentLocation) 'sname': origin.name,
      'dlat': destination.latitude.toString(),
      'dlng': destination.longitude.toString(),
      'dname': destination.name,
      'appname': 'kr.araba.araba',
    };
    for (var i = 0; i < via.length; i++) {
      params['v${i + 1}lat'] = via[i].latitude.toString();
      params['v${i + 1}lng'] = via[i].longitude.toString();
      params['v${i + 1}name'] = via[i].name;
    }
    if (route.travelMode == 'driving') {
      return Uri(scheme: 'nmap', host: 'navigation', queryParameters: params);
    }
    final kind = switch (route.travelMode) {
      'walking' => 'walk',
      'transit' => 'public',
      'bicycling' => 'bicycle',
      _ => 'car',
    };
    return Uri(scheme: 'nmap', host: 'route', path: '/$kind', queryParameters: params);
  }
}

class PreparedNavigation {
  const PreparedNavigation(this.uri, this.provider);
  final Uri uri;
  final NavigationMapProvider provider;
}

class NavigationProviderService {
  NavigationProviderService({
    ArabaApi? api,
    NavigationPreferenceStore? preferences,
    KakaoCredentialStore? kakaoKeyStore,
    DeviceLocationService? locationService,
  }) : _api = api ?? ArabaApi(),
       _preferences = preferences ?? NavigationPreferenceStore(),
       _kakaoStore = kakaoKeyStore ?? KakaoCredentialStore(),
       _location = locationService ?? const DeviceLocationService();

  final ArabaApi _api;
  final NavigationPreferenceStore _preferences;
  final KakaoCredentialStore _kakaoStore;
  final DeviceLocationService _location;

  Future<NavigationPoint> _resolve(String name) async {
    final coordinates = NavigationPoint.fromCoordinate(name);
    if (coordinates != null) return coordinates;

    final key = await _kakaoStore.read();
    final response = await _api.resolveNavigationPlace(name, kakaoRestApiKey: key);
    final state = response['status']?.toString() ?? '';
    if (state != 'resolved') {
      if (state == 'missing_key') {
        throw const NavigationProviderException(
          '장소 좌표 확인에 필요한 Kakao REST API 키가 없습니다. MY의 카카오 API 설정을 확인해 주세요.',
        );
      }
      if (state == 'ambiguous') {
        final candidates = response['candidates'];
        final candidatesText = candidates is List
            ? candidates.whereType<Map>().take(3)
                .map((item) => "${item['name']} (${item['address']})").join(' / ')
            : '';
        throw NavigationProviderException(
          '$name과(와) 비슷한 장소가 여러 곳입니다. 정확한 주소를 알려주세요.'
          "${candidatesText.isEmpty ? '' : '\n후보: $candidatesText'}",
        );
      }
      if (state == 'not_found') {
        throw NavigationProviderException(
          '$name의 정확한 위치를 확인하지 못했어요. 도로명주소를 알려주세요.',
        );
      }
      throw const NavigationProviderException(
        '지도 좌표를 확인하지 못했어요. 연결 상태와 Kakao API 설정을 확인해 주세요.',
      );
    }
    final value = response['place'];
    if (value is! Map) {
      throw const NavigationProviderException('장소 좌표 응답이 올바르지 않습니다.');
    }
    final lat = double.tryParse(value['latitude']?.toString() ?? '');
    final lon = double.tryParse(value['longitude']?.toString() ?? '');
    if (lat == null || lon == null || lat < 33 || lat > 39 || lon < 124 || lon > 132) {
      throw const NavigationProviderException('장소 좌표가 올바르지 않습니다.');
    }
    return NavigationPoint(value['name']?.toString() ?? name, lat, lon);
  }

  Future<PreparedNavigation> prepare(
    NavigationRequest request, {
    Map<String, dynamic>? destinationBusiness,
  }) async {
    final provider = await _preferences.read();
    final location = request.currentLocation ? await _location.currentContext() : null;
    if (request.currentLocation && location == null) {
      throw const NavigationProviderException(
        '현재 위치를 확인할 수 없습니다. 휴대전화 위치 설정과 ARABA 권한을 확인해 주세요.',
      );
    }
    final origin = request.currentLocation
        ? NavigationPoint(
            '현재 위치',
            (location!['latitude'] as num).toDouble(),
            (location['longitude'] as num).toDouble(),
          )
        : (provider == NavigationMapProvider.google
            ? const NavigationPoint('', 0, 0)
            : await _resolve(request.origin));

    if (provider == NavigationMapProvider.google) {
      return PreparedNavigation(
        NavigationLauncher.directionsUri(
          request,
          latitude: request.currentLocation ? origin.latitude : null,
          longitude: request.currentLocation ? origin.longitude : null,
        ), provider,
      );
    }

    final destination = destinationBusiness == null
        ? null : NavigationPoint.fromBusiness(destinationBusiness);
    final destinationPoint = destination ?? await _resolve(request.destination);
    final via = <NavigationPoint>[];
    for (final name in request.waypoints) {
      via.add(await _resolve(name));
    }
    return PreparedNavigation(
      NavigationProviderLinks.create(
        provider, request,
        origin: origin, destination: destinationPoint, via: via,
      ), provider,
    );
  }

  Future<bool> open(PreparedNavigation navigation) async {
    try {
      return await launchUrl(navigation.uri, mode: LaunchMode.externalApplication);
    } catch (error) {
      debugPrint('Navigation app launch failed: ${error.runtimeType}');
      return false;
    }
  }
}
