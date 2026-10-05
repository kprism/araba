class ConversationContext {
  String? _location;

  String? get location => _location;

  String enrichRequest(String requestText) {
    final text = requestText.trim();
    final knownLocation = _location?.trim() ?? '';

    if (knownLocation.isEmpty ||
        text.contains('[대화 문맥] 이미 확인된 지역:')) {
      return text;
    }

    return [
      '[대화 문맥] 이미 확인된 지역: $knownLocation',
      '사용자가 새 지역을 말하지 않았다면 이 지역을 유지하고 다시 묻지 마세요.',
      '',
      '[현재 요청]',
      text,
    ].join('\n');
  }

  void rememberMission(Map<String, dynamic> mission) {
    final rawLocation = mission['location'];
    final resolved = rawLocation?.toString().trim() ?? '';

    if (resolved.isEmpty ||
        resolved.toLowerCase() == 'null') {
      return;
    }

    _location = resolved;
  }

  void clear() {
    _location = null;
  }
}
