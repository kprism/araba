import 'dart:async';

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:url_launcher/url_launcher.dart';

class NotificationService {
  NotificationService._();

  static final NotificationService instance = NotificationService._();

  static const String updateTopic = 'araba-dev-updates';
  static const String latestApkUrl =
      'https://github.com/kprism/araba/releases/download/'
      'dev-latest/araba-dev.apk';

  final FirebaseMessaging _messaging = FirebaseMessaging.instance;
  StreamSubscription<RemoteMessage>? _openedSubscription;

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

    final initialMessage = await _messaging.getInitialMessage();
    if (initialMessage != null) {
      await _openFromMessage(initialMessage);
    }
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
    _openedSubscription = null;
  }
}
