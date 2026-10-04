import 'dart:async';

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import 'araba_api.dart';

class NotificationService {
  NotificationService._();

  static final NotificationService instance = NotificationService._();

  static const String updateTopic = 'araba-dev-updates';
  static const String latestApkUrl =
      'https://github.com/kprism/araba/releases/download/'
      'dev-latest/araba-dev.apk';

  final FirebaseMessaging _messaging = FirebaseMessaging.instance;
  final ArabaApi _api = ArabaApi();

  static const MethodChannel _notificationChannel =
      MethodChannel('araba/notifications');

  StreamSubscription<RemoteMessage>? _openedSubscription;
  StreamSubscription<RemoteMessage>? _foregroundSubscription;
  StreamSubscription<String>? _tokenRefreshSubscription;

  Future<void> initialize() async {
    await _messaging.requestPermission(
      alert: true,
      badge: true,
      sound: true,
    );

    await _registerForUpdates();

    await _tokenRefreshSubscription?.cancel();
    _tokenRefreshSubscription = _messaging.onTokenRefresh.listen(
      (token) {
        unawaited(_registerToken(token));
      },
    );

    await _openedSubscription?.cancel();
    _openedSubscription =
        FirebaseMessaging.onMessageOpenedApp.listen(_openFromMessage);

    await _foregroundSubscription?.cancel();
    _foregroundSubscription =
        FirebaseMessaging.onMessage.listen(_showForegroundNotification);

    final initialMessage = await _messaging.getInitialMessage();
    if (initialMessage != null) {
      await _openFromMessage(initialMessage);
    }
  }

  Future<void> _registerForUpdates() async {
    for (var attempt = 0; attempt < 3; attempt++) {
      try {
        final token = await _messaging.getToken();

        if (token == null || token.trim().isEmpty) {
          throw const ArabaApiException(
            'FCM 토큰을 발급받지 못했습니다.',
          );
        }

        await _messaging.subscribeToTopic(updateTopic);
        await _registerToken(token);
        return;
      } catch (_) {
        if (attempt == 2) {
          return;
        }

        await Future<void>.delayed(
          Duration(seconds: attempt + 1),
        );
      }
    }
  }

  Future<void> _registerToken(String token) async {
    try {
      await _api.registerNotificationToken(token);
    } catch (_) {
      // 다음 앱 실행 또는 FCM token refresh 때 다시 등록한다.
    }
  }

  Future<void> _showForegroundNotification(
    RemoteMessage message,
  ) async {
    final notification = message.notification;

    await _notificationChannel.invokeMethod<void>(
      'showUpdateNotification',
      {
        'title': notification?.title ?? 'ARABA 새 버전 준비됨',
        'body': notification?.body ??
            '알림을 눌러 최신 개발 버전으로 업데이트하세요.',
        'url': message.data['url'] ?? latestApkUrl,
      },
    );
  }

  Future<void> _openFromMessage(RemoteMessage message) async {
    final messageUrl = message.data['url']?.trim();
    final uri = Uri.tryParse(
      messageUrl != null && messageUrl.isNotEmpty
          ? messageUrl
          : latestApkUrl,
    );

    if (uri == null) {
      return;
    }

    await launchUrl(
      uri,
      mode: LaunchMode.externalApplication,
    );
  }

  Future<void> dispose() async {
    await _openedSubscription?.cancel();
    await _foregroundSubscription?.cancel();
    await _tokenRefreshSubscription?.cancel();
    _openedSubscription = null;
    _foregroundSubscription = null;
    _tokenRefreshSubscription = null;
  }
}
