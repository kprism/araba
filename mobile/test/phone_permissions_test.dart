import 'package:araba/services/device_permissions.dart';
import 'package:araba/services/phone_intent.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('araba/device_permissions');

  setUp(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      if (call.method == 'status' || call.method == 'requestAll') {
        return {'microphone': true, 'location': true, 'phone': true,
          'camera': false, 'notifications': true};
      }
      if (call.method == 'firstRunNeeded') return true;
      if (call.method == 'placeCall') return true;
      if (call.method == 'markFirstRunComplete') return true;
      if (call.method == 'openSettings') return true;
      return null;
    });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  test('call intent variants trigger actual phone action', () {
    for (final message in [
      '순자네집밥 전화해줘', '전화해라', '전화 걸어줘', '전화 연결해',
      '통화시켜줘', '연결해줘',
    ]) {
      expect(PhoneIntent.hasCallIntent(message), isTrue, reason: message);
    }
    for (final question in [
      '전화번호 알려줘', '전화번호는?', '연락처 확인해줘', '통화 가능한가?',
    ]) {
      expect(PhoneIntent.hasCallIntent(question), isFalse, reason: question);
    }
  });

  test('unverified phone is not a candidate and named business ranks alone', () {
    final result = PhoneIntent.matchingBusinesses('순자네집밥 전화해줘', [
      {'name': '다른집밥', 'phone': '055-222-1000'},
      {'name': '순자네집밥', 'phone': '055-111-1000'},
      {'name': '번호없는업체', 'phone': ''},
    ]);
    expect(result.length, 1);
    expect(result.single['name'], '순자네집밥');
  });

  test('first-run permissions and future permission status are separate', () async {
    expect(await DevicePermissions.firstRunNeeded(), isTrue);
    final status = await DevicePermissions.requestAll();
    expect(status['phone'], isTrue);
    expect(status['camera'], isFalse);
    await DevicePermissions.markFirstRunComplete();
  });

  test('direct calling uses only validated phone numbers', () async {
    await DevicePermissions.placeCall('055-123-4567');
    await expectLater(
      DevicePermissions.placeCall('잘못된번호'),
      throwsA(isA<PlatformException>()),
    );
  });
}
