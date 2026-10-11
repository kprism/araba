/// Human-readable evidence gaps for a search that returned no displayable photos.
/// Uses provider diagnostics already collected during enrichment; no extra calls.
String describeMissingBusinessPhotos(List<Map<String, dynamic>> businesses) {
  if (businesses.isEmpty) return '사진 확인 대상 업체가 없습니다.';
  if (businesses.any((item) =>
      (item['image_url']?.toString().trim() ?? '').isNotEmpty)) {
    return '';
  }

  int count(String field, String value) => businesses.where((item) =>
      item[field]?.toString() == value).length;

  final details = <String>[];
  final kakaoNoPhoto = count('kakao_photo_status', 'no_image_in_page');
  final kakaoFail = [
    'page_fetch_failed', 'page_unavailable', 'page_error',
  ].fold<int>(0, (sum, status) => sum + count('kakao_photo_status', status));
  final kakaoUnverified = count('kakao_photo_status', 'identity_not_confirmed');
  final googleMissing = count('google_photo_status', 'not_configured');
  final googleHttp = count('google_photo_status', 'provider_http_error');
  final googleNoMatch = count('google_photo_status', 'business_identity_unmatched');
  final googleNoPhoto = count('google_photo_status', 'no_photo_in_place');
  final googleMediaError = count('google_photo_status', 'photo_media_unavailable');
  final googleUnavailable = count('google_photo_status', 'provider_unreachable');

  if (kakaoNoPhoto > 0) details.add('카카오 상세페이지 사진 미확인 $kakaoNoPhoto곳');
  if (kakaoFail > 0) details.add('카카오 페이지 접속 실패 $kakaoFail곳');
  if (kakaoUnverified > 0) details.add('카카오 사진 업체 일치 미확인 $kakaoUnverified곳');
  if (googleMissing > 0) details.add('Google Places 키 미설정 $googleMissing곳');
  if (googleHttp > 0) {
    final codes = businesses
        .where((b) => b['google_photo_status'] == 'provider_http_error')
        .map((b) => b['google_search_http_status']?.toString() ?? '')
        .where((s) => s.isNotEmpty)
        .toSet()
        .join('/');
    details.add('Google Places 요청 실패 $googleHttp곳${codes.isNotEmpty ? ' (HTTP $codes)' : ''}');
  }
  if (googleNoMatch > 0) details.add('Google 동일 업체 검증 실패 $googleNoMatch곳');
  if (googleNoPhoto > 0) details.add('Google 사진 없음 $googleNoPhoto곳');
  if (googleMediaError > 0) details.add('Google 사진 링크 확보 실패 $googleMediaError곳');
  if (googleUnavailable > 0) details.add('Google 연결 실패 $googleUnavailable곳');

  if (details.isEmpty) return '사진을 확보하지 못했습니다. 연결 설정과 사진 출처를 추가 확인해야 합니다.';
  return details.take(5).join(' · ');
}
