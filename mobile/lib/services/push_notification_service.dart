import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

class PushNotificationService {
  static const String _apiKey = String.fromEnvironment(
    'ARABA_FIREBASE_API_KEY',
  );
  static const String _appId = String.fromEnvironment(
    'ARABA_FIREBASE_APP_ID',
  );
  static const String _messagingSenderId = String.fromEnvironment(
    'ARABA_FIREBASE_MESSAGING_SENDER_ID',
  );
  static const String _projectId = String.fromEnvironment(
    'ARABA_FIREBASE_PROJECT_ID',
  );

  static bool get configured =>
      _apiKey.isNotEmpty &&
      _appId.isNotEmpty &&
      _messagingSenderId.isNotEmpty &&
      _projectId.isNotEmpty;

  static Future<void> initialize() async {
    if (!configured) {
      return;
    }

    await Firebase.initializeApp(
      options: const FirebaseOptions(
        apiKey: _apiKey,
        appId: _appId,
        messagingSenderId: _messagingSenderId,
        projectId: _projectId,
      ),
    );

    final messaging = FirebaseMessaging.instance;

    await messaging.requestPermission(
      alert: true,
      badge: true,
      sound: true,
    );

    await messaging.subscribeToTopic(
      'araba-dev-updates',
    );
  }
}
