import 'dart:convert';

class ConversationContext {
  final Map<String, dynamic> _known = {};

  String? get location =>
      _known['location']?.toString();

  Map<String, dynamic> get snapshot =>
      Map<String, dynamic>.from(_known);

  String enrichRequest(String requestText) {
    final text = requestText.trim();

    if (_known.isEmpty ||
        text.contains('[대화 문맥]')) {
      return text;
    }

    final knownLocation =
        _known['location']?.toString().trim() ?? '';

    return [
      '[대화 문맥]',
      if (knownLocation.isNotEmpty)
        '[대화 문맥] 이미 확인된 지역: $knownLocation',
      jsonEncode(_known),
      '이미 확인된 정보는 사용자가 바꾸지 않는 한 유지하고 다시 묻지 마세요.',
      '후속 명령이면 현재 주제와 대상을 유지하세요.',
      '',
      '[현재 요청]',
      text,
    ].join('\n');
  }

  void rememberMission(
    Map<String, dynamic> mission,
  ) {
    for (final key in [
      'category',
      'subcategories',
      'intent',
      'location',
      'subject',
      'target_business',
      'comparison',
    ]) {
      final value = mission[key];

      if (_isUseful(value)) {
        _known[key] = value;
      }
    }

    final attributes = mission['attributes'];

    if (attributes is Map) {
      final current = _known['attributes'];
      final merged = current is Map
          ? Map<String, dynamic>.from(current)
          : <String, dynamic>{};

      for (final entry in attributes.entries) {
        if (_isUseful(entry.value)) {
          merged[
            entry.key.toString()
          ] = entry.value;
        }
      }

      if (merged.isNotEmpty) {
        _known['attributes'] = merged;
      }
    }

    final constraints = mission['constraints'];

    if (constraints is List) {
      final existing =
          (_known['constraints'] is List)
          ? List<String>.from(
              (_known['constraints'] as List)
                  .map((item) => item.toString()),
            )
          : <String>[];

      for (final item in constraints) {
        final text = item.toString().trim();

        if (text.isNotEmpty &&
            !existing.contains(text)) {
          existing.add(text);
        }
      }

      if (existing.isNotEmpty) {
        _known['constraints'] = existing;
      }
    }
  }

  void rememberAttributes(
    Map<String, dynamic> attributes,
  ) {
    final current = _known['attributes'];
    final merged = current is Map
        ? Map<String, dynamic>.from(current)
        : <String, dynamic>{};

    for (final entry in attributes.entries) {
      if (_isUseful(entry.value)) {
        merged[
          entry.key.toString()
        ] = entry.value;
      }
    }

    if (merged.isNotEmpty) {
      _known['attributes'] = merged;
    }
  }

  bool _isUseful(dynamic value) {
    if (value == null) {
      return false;
    }

    if (value is String) {
      final normalized = value.trim().toLowerCase();

      return normalized.isNotEmpty &&
          normalized != 'null' &&
          normalized != '미정' &&
          normalized != '없음';
    }

    if (value is List) {
      return value.isNotEmpty;
    }

    if (value is Map) {
      return value.isNotEmpty;
    }

    return true;
  }

  void clear() {
    _known.clear();
  }
}
