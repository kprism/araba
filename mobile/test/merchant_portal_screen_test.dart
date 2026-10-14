import 'package:araba/screens/merchant/merchant_portal_screen.dart';
import 'package:araba/services/merchant_account_api.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeMerchantAccount extends MerchantAccountApi {
  FakeMerchantAccount({this.loggedIn = true});
  final bool loggedIn;
  @override
  Future<String?> token() async => loggedIn ? 'test-token' : null;
  @override
  Future<Map<String, dynamic>> me() async => {
    'ok': true,
    'user': {'username': 'testowner'},
    'claims': [],
  };
  @override
  Future<Map<String, dynamic>> searchExistingBusinesses(String query) async => {
    'ok': true,
    'businesses': [
      {
        'id': 12, 'name': '순자네집밥',
        'address': '경남 창원시 의창구 북면', 'category': '음식점',
      },
    ],
  };
  @override
  Future<Map<String, dynamic>> usernameAvailable(String username) async => {
    'ok': true, 'available': true,
  };
}

void main() {
  testWidgets('merchant searches the already-indexed ARABA business DB', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: MerchantPortalScreen(
        merchantApi: FakeMerchantAccount(),
      )),
    ));
    await tester.pumpAndSettle();

    expect(find.text('ARABA 기존 업체 DB 검색'), findsOneWidget);
    await tester.enterText(
      find.widgetWithText(TextField, '상호명 또는 지역'), '순자네',
    );
    await tester.tap(find.text('업체 검색'));
    await tester.pumpAndSettle();
    expect(find.text('순자네집밥'), findsOneWidget);

    await tester.ensureVisible(find.text('순자네집밥'));
    await tester.tap(find.text('순자네집밥'));
    await tester.pumpAndSettle();
    expect(find.textContaining('관리권한 신청:'), findsOneWidget);
    expect(find.textContaining('승인 전에는 공개 업체 DB를 수정할 수 없습니다'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('new merchant requires username-availability check', (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: MerchantPortalScreen(
        merchantApi: FakeMerchantAccount(loggedIn: false),
      )),
    ));
    await tester.pumpAndSettle();

    await tester.tap(find.text('회원가입'));
    await tester.pumpAndSettle();
    expect(find.text('아이디 중복 확인'), findsOneWidget);
    expect(find.text('비밀번호 재입력'), findsOneWidget);
    expect(find.text('이용약관 동의'), findsOneWidget);
    expect(find.text('개인정보 처리방침 동의'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
