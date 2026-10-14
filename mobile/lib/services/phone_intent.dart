class PhoneIntent {
  const PhoneIntent._();

  static bool hasCallIntent(String utterance) {
    final text = utterance.replaceAll(RegExp(r'\s+'), '');
    // Phone-number questions are not instructions to place a call.
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

  static String destinationQuery(String utterance) {
    final query = utterance
        .replaceAll(RegExp(
          r'전화(?:를|좀|한통)?(?:걸어주세요|걸어줘|걸어라|걸어|해주세요|해줘|해라|해|연결해주세요|연결해줘|연결해)|'
          r'(?:전화)?연결(?:해주세요|해줘|해|시켜줘)|'
          r'통화(?:시켜줘|연결해|해줘|걸어)',
        ), '')
        .replaceAll(RegExp(r'(?:에게|한테|에|로|으로)\s*$'), '')
        .replaceAll(RegExp(r'^[^0-9a-zA-Z가-힣]+|[^0-9a-zA-Z가-힣]+$'), '')
        .trim();
    if (query.isEmpty || RegExp(
      r'^(그곳|그가게|그업체|거기|그집|그식당|여기|방금찾은곳)$',
    ).hasMatch(query.replaceAll(RegExp(r'\s+'), ''))) {
      return '';
    }
    return query;
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
    return destinationQuery(utterance).isNotEmpty ? named : withPhone;
  }
}
