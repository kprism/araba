import 'dart:async';

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

class NotificationService {
  NotificationService._();

  static final NotificationService instance = NotificationService._();

  static const String updateTopic = 'araba-dev-updates';
  static const String latestApkUrl =
      'https://github.com/kprism/araba/releases/download/'
      'dev-latest/araba-dev.apk';

  final FirebaseMessaging _messaging = FirebaseMessaging.instance;
  static const MethodChannel _notificationChannel =
      MethodChannel('araba/notifications');

  StreamSubscription<RemoteMessage>? _openedSubscription;
  StreamSubscription<RemoteMessage>? _foregroundSubscription;

  Future<void> initialize() async {
    await _messaging.requestPermission(
      alert: true,
      badge: true,
      sound: true,
    );

    await _messaging.subscribeToTopic(updateTopic);

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
    _openedSubscription = null;
    _foregroundSubscription = null;
  }
}
