import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:araba/app/araba_app.dart';

void main() {
  testWidgets('ARABA home screen renders correctly', (tester) async {
    await tester.pumpWidget(const ArabaApp());
    await tester.pumpAndSettle();

    expect(find.text('ARABA'), findsOneWidget);

    expect(find.text('무엇을 알아볼까요?'), findsOneWidget);

    expect(find.text('홈'), findsOneWidget);

    expect(find.text('작업'), findsOneWidget);

    expect(find.text('알림'), findsOneWidget);

    expect(find.text('MY'), findsOneWidget);
  });

  testWidgets('Empty mission shows validation message', (tester) async {
    await tester.pumpWidget(const ArabaApp());
    await tester.pumpAndSettle();

    final button = find.widgetWithText(FilledButton, '알아봐');

    expect(button, findsOneWidget);

    await tester.tap(button);
    await tester.pump();

    expect(find.text('알아볼 내용을 입력해주세요.'), findsOneWidget);
  });

  testWidgets('MY tab opens developer settings', (tester) async {
    await tester.pumpWidget(const ArabaApp());
    await tester.pump();

    await tester.tap(find.text('MY').last);

    await tester.pump();

    expect(find.text('개발 설정'), findsOneWidget);

    expect(find.text('OpenAI API'), findsOneWidget);
  });
}
