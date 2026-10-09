import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:araba/app/araba_app.dart';

void main() {
  testWidgets('ARABA conversational home renders correctly', (tester) async {
    await tester.pumpWidget(const ArabaApp());
    await tester.pumpAndSettle();

    expect(find.text('ARABA'), findsOneWidget);
    expect(find.textContaining('무엇을 알아볼까요?'), findsOneWidget);
    expect(find.text('알아볼 내용을 입력하세요'), findsOneWidget);
    expect(find.text('보내기'), findsOneWidget);
    expect(find.text('홈'), findsOneWidget);
    expect(find.text('작업'), findsOneWidget);
    expect(find.text('알림'), findsOneWidget);
    expect(find.text('MY'), findsOneWidget);
  });

  testWidgets('Empty chat message shows validation message', (tester) async {
    await tester.pumpWidget(const ArabaApp());
    await tester.pumpAndSettle();

    final button = find.widgetWithText(FilledButton, '보내기');
    expect(button, findsOneWidget);

    await tester.tap(button);
    await tester.pump();

    expect(find.text('알아볼 내용을 입력해주세요.'), findsOneWidget);
  });

  testWidgets('MY tab opens administrator API settings', (tester) async {
    await tester.pumpWidget(const ArabaApp());
    await tester.pump();

    await tester.tap(find.text('MY').last);
    await tester.pump();

    expect(find.text('관리자 API 설정'), findsOneWidget);
    expect(find.text('검색 상점 DB'), findsOneWidget);

    await tester.scrollUntilVisible(
      find.text('OpenAI API'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('OpenAI API'), findsOneWidget);

    await tester.scrollUntilVisible(
      find.text('Kakao Local API'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('Kakao Local API'), findsOneWidget);
  });
}
