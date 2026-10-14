import 'package:flutter/services.dart';

class DevicePermissions {
  static const MethodChannel _channel = MethodChannel('araba/device_permissions');
  static const permissionNames = <String, String>{
    'microphone': '마이크 · GPT-Live 음성',
    'location': '위치 · 현재 위치 길찾기',
    'camera': '카메라 · 사진 촬영',
    'phone': '전화 · 업체에 바로 전화 걸기',
    'notifications': '알림 · 업데이트 및 진행상황',
  };

  static Future<bool> firstRunNeeded() async =>
      await _channel.invokeMethod<bool>('firstRunNeeded') ?? true;

  static Future<void> markFirstRunComplete() async {
    await _channel.invokeMethod<bool>('markFirstRunComplete');
  }

  static Future<Map<String, bool>> status() async {
    final raw = await _channel.invokeMapMethod<String, bool>('status');
    return raw ?? <String, bool>{};
  }

  static Future<Map<String, bool>> requestAll() async {
    final raw = await _channel.invokeMapMethod<String, bool>('requestAll');
    return raw ?? <String, bool>{};
  }

  static Future<void> openSettings() async {
    await _channel.invokeMethod<bool>('openSettings');
  }

  static Future<void> placeCall(String phone) async {
    final normalized = phone.replaceAll(RegExp(r'[^0-9+]'), '');
    if (!RegExp(r'^\+?[0-9]{7,15}$').hasMatch(normalized)) {
      throw PlatformException(
        code: 'INVALID_PHONE', message: '연결할 업체 전화번호를 확인해주세요.',
      );
    }
    await _channel.invokeMethod<bool>('placeCall', {'phone': normalized});
  }
}
