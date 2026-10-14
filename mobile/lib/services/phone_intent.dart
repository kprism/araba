class PhoneIntent {
  const PhoneIntent._();

  static bool hasCallIntent(String utterance) {
    final text = utterance.replaceAll(RegExp(r'\s+'), '');
    // Asking for a phone number is informational, not permission to dial.
    if (RegExp(r'전화번호|연락처|번호알려|통화가능|전화할수').hasMatch(text) &&
        !RegExp(r'전화(?:걸|해|줘|주세요|연결)|연결해|통화(?:시켜|해줘|걸어)').hasMatch(text)) {
      return false;
    }
    return RegExp(
      r'전화(?:를|좀|한통)?(?:걸어|걸어줘|걸어주세요|걸어라|해|해줘|해주세요|해라|연결해|연결해줘|연결해주세요)|'
      r'(?:전화)?연결(?:해|해줘|해주세요|시켜줘)|'
      r'통화(?:시켜|연결해|해줘|걸어)',
    ).hasMatch(text);
  }

  static List<Map<String, dynamic>> matchingBusinesses(
    String utterance,
    List<Map<String, dynamic>> businesses,
  ) {
    final needle = utterance.replaceAll(RegExp(r'[^0-9a-zA-Z가-힣]'), '').toLowerCase();
    final withPhone = businesses.where((item) =>
        (item['phone']?.toString().replaceAll(RegExp(r'[^0-9+]'), '') ?? '').length >= 7
    ).toList();
    final named = withPhone.where((item) {
      final businessName = item['name']?.toString()
          .replaceAll(RegExp(r'[^0-9a-zA-Z가-힣]'), '').toLowerCase() ?? '';
      return businessName.length >= 2 && needle.contains(businessName);
    }).toList();
    return named.isNotEmpty ? named : withPhone;
  }
}
