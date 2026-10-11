import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// The preferred navigation application is a device-local MY setting.
enum NavigationMapProvider {
  google('google', 'Google 지도'),
  kakao('kakao', '카카오맵'),
  naver('naver', '네이버지도');

  const NavigationMapProvider(this.id, this.label);
  final String id;
  final String label;

  static NavigationMapProvider fromId(String? id) {
    for (final provider in values) {
      if (provider.id == id) return provider;
    }
    return NavigationMapProvider.google;
  }
}

class NavigationPreferenceStore {
  static const _storageKey = 'navigation_default_map_provider';
  final FlutterSecureStorage _storage;

  NavigationPreferenceStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  Future<NavigationMapProvider> read() async {
    final value = await _storage.read(key: _storageKey);
    return NavigationMapProvider.fromId(value);
  }

  Future<void> write(NavigationMapProvider provider) async {
    await _storage.write(key: _storageKey, value: provider.id);
  }
}
