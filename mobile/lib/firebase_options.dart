import 'package:firebase_core/firebase_core.dart' show FirebaseOptions;
import 'package:flutter/foundation.dart'
    show TargetPlatform, defaultTargetPlatform, kIsWeb;

class DefaultFirebaseOptions {
  static FirebaseOptions get currentPlatform {
    if (kIsWeb) {
      throw UnsupportedError(
        'Firebase options are not configured for web yet.',
      );
    }

    switch (defaultTargetPlatform) {
      case TargetPlatform.android:
        return android;
      default:
        throw UnsupportedError(
          'Firebase options are not configured for this platform yet.',
        );
    }
  }

  static const FirebaseOptions android = FirebaseOptions(
    apiKey: 'AIzaSyCXt3d_t8Ed_6EdigbcoBNJnr4-2qODAp8',
    appId: '1:908580697493:android:24a7c27df3d23423a4329c',
    messagingSenderId: '908580697493',
    projectId: 'araba-dev',
    storageBucket: 'araba-dev.firebasestorage.app',
  );
}
