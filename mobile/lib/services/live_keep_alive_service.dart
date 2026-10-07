import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

class LiveKeepAliveService {
  static const MethodChannel _channel = MethodChannel(
    'araba/live_keep_alive',
  );

  static Future<void> start() async {
    if (defaultTargetPlatform != TargetPlatform.android) {
      return;
    }

    try {
      await _channel.invokeMethod<void>('start');
    } on MissingPluginException {
      // Non-Android test environments do not expose the native channel.
    }
  }

  static Future<void> stop() async {
    if (defaultTargetPlatform != TargetPlatform.android) {
      return;
    }

    try {
      await _channel.invokeMethod<void>('stop');
    } on MissingPluginException {
      // Non-Android test environments do not expose the native channel.
    }
  }
}
