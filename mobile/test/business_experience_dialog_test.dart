import 'package:araba/screens/home/business_experience_dialog.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  Future<void> openDetailAndExperience(
    WidgetTester tester,
    ValueChanged<String?> onSaved,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => FilledButton(
              onPressed: () => showModalBottomSheet<void>(
                context: context,
                isScrollControlled: true,
                builder: (sheetContext) => DraggableScrollableSheet(
                  expand: false,
                  builder: (detailContext, scrollController) => Material(
                    child: ListView(
                      controller: scrollController,
                      children: [
                        FilledButton(
                          onPressed: () async {
                            final text = await showDialog<String>(
                              context: detailContext,
                              builder: (_) => const BusinessExperienceDialog(
                                businessName: '순자네집밥',
                              ),
                            );
                            onSaved(text);
                          },
                          child: const Text('이용 경험 남기기'),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              child: const Text('업체 상세 열기'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('업체 상세 열기'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('이용 경험 남기기'));
    await tester.pumpAndSettle();
    expect(find.text('순자네집밥 이용 경험'), findsOneWidget);
    expect(find.byType(TextField), findsOneWidget);
  }

  testWidgets('keyboard input save does not leave inherited dependents', (tester) async {
    String? stored;
    await openDetailAndExperience(tester, (value) => stored = value);

    await tester.enterText(find.byType(TextField), '음식이 맛있고 주차는 확인 필요');
    await tester.pump();
    await tester.tap(find.text('경험 저장'));
    await tester.pumpAndSettle();

    expect(stored, '음식이 맛있고 주차는 확인 필요');
    expect(find.text('이용 경험 남기기'), findsOneWidget);
    expect(tester.takeException(), isNull);

    // Closing the still-open details bottom sheet must also be safe.
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets('cancelled experience does not save or break overlay lifecycle', (tester) async {
    String? stored = 'unchanged';
    await openDetailAndExperience(tester, (value) => stored = value);

    await tester.enterText(find.byType(TextField), '취소할 문장');
    await tester.tap(find.text('취소'));
    await tester.pumpAndSettle();

    expect(stored, isNull);
    expect(tester.takeException(), isNull);
  });
}
