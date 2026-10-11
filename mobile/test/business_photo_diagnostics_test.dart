import 'package:araba/services/business_photo_diagnostics.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('reports unconfigured photo fallback with no invented image', () {
    final data = [
      {
        'image_url': null,
        'kakao_photo_status': 'no_image_in_page',
        'google_photo_status': 'not_configured',
      },
    ];
    final summary = describeMissingBusinessPhotos(data);
    expect(summary, contains('카카오 상세페이지 사진 미확인 1곳'));
    expect(summary, contains('Google Places 키 미설정 1곳'));
  });

  test('reports provider status without raw secrets', () {
    final summary = describeMissingBusinessPhotos([
      {
        'image_url': null,
        'google_photo_status': 'provider_http_error',
        'google_search_http_status': 403,
      },
    ]);
    expect(summary, contains('Google Places 요청 실패 1곳 (HTTP 403)'));
  });

  test('verified photo suppresses missing photo diagnosis', () {
    expect(describeMissingBusinessPhotos([
      {'image_url': 'https://img.example.com/verified.jpg'},
    ]), isEmpty);
  });

  test('missing provider diagnostics never claims confirmed failure type', () {
    final message = describeMissingBusinessPhotos([
      {'image_url': null}
    ]);
    expect(message, contains('추가 확인'));
    expect(message, isNot(contains('API 키 미설정')));
  });
}
