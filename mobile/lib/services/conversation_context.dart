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
        text.contains('[대화 문맥') ||
        text.contains('[현재 요청]')) {
      return text;
    }

    final knownLocation =
        _known['location']?.toString().trim() ?? '';

    return [
      '[대화 문맥 - 참고용]',
      if (knownLocation.isNotEmpty)
        '[대화 문맥] 이미 확인된 지역: $knownLocation',
      jsonEncode(_known),
      '',
      '판단 규칙:',
      '1. 아래 [현재 요청]이 항상 최우선입니다.',
      '2. 현재 요청에서 사용자가 최종적으로 원하는 결과와 판단을 먼저 해석하세요.',
      '3. 지역·업종·상호명은 목적을 해결하기 위한 조건이며, 그 자체를 목적처럼 다루지 마세요.',
      '4. 대화 문맥은 현재 요청과 충돌하지 않는 정보만 재사용하고, 이미 확인된 정보는 다시 묻지 마세요.',
      '5. 현재 요청이 새로운 업종·주제·지역을 명시하면 이전 주제의 category, subject, target_business, constraints, attributes를 승계하지 마세요.',
      '6. "그곳", "그중", "아까", "거기"처럼 명백한 후속표현일 때만 이전 특정 대상을 이어가세요.',
      '',
      '[현재 요청]',
      text,
    ].join('\n');
  }

  void rememberMission(
    Map<String, dynamic> mission,
  ) {
    final previousCategory =
        _known['category']?.toString().trim() ?? '';
    final nextCategory =
        mission['category']?.toString().trim() ?? '';

    if (previousCategory.isNotEmpty &&
        nextCategory.isNotEmpty &&
        previousCategory != nextCategory) {
      for (final key in [
        'subcategories',
        'subject',
        'target_business',
        'attributes',
        'constraints',
        'criteria',
        'task_state',
        'comparison',
        'user_goal',
        'decision_needed',
        'expected_answer',
        'search_mode',
        'intent',
      ]) {
        _known.remove(key);
      }
    }
    final searchMode =
        mission['search_mode']?.toString().trim() ?? '';

    if (searchMode == 'category_discovery' ||
        searchMode == 'area_discovery' ||
        searchMode == 'comparison') {
      _known.remove('target_business');

      final currentAttributes = _known['attributes'];
      if (currentAttributes is Map) {
        final cleaned =
            Map<String, dynamic>.from(currentAttributes);
        cleaned.remove('selected_business_name');
        cleaned.remove('selected_business_address');
        cleaned.remove('selected_business_phone');
        cleaned.remove('selected_business_opening_hours');

        if (cleaned.isEmpty) {
          _known.remove('attributes');
        } else {
          _known['attributes'] = cleaned;
        }
      }
    }

    if (searchMode == 'exact_place') {
      final newTarget =
          mission['target_business']?.toString().trim() ?? '';
      final oldTarget =
          _known['target_business']?.toString().trim() ?? '';

      if (newTarget.isNotEmpty &&
          oldTarget.isNotEmpty &&
          newTarget != oldTarget) {
        final currentAttributes = _known['attributes'];
        if (currentAttributes is Map) {
          final cleaned =
              Map<String, dynamic>.from(currentAttributes);
          cleaned.remove('selected_business_name');
          cleaned.remove('selected_business_address');
          cleaned.remove('selected_business_phone');
          cleaned.remove('selected_business_opening_hours');

          if (cleaned.isEmpty) {
            _known.remove('attributes');
          } else {
            _known['attributes'] = cleaned;
          }
        }
      }
    }

    for (final key in [
      'category',
      'subcategories',
      'intent',
      'search_mode',
      'location',
      'subject',
      'target_business',
      'comparison',
      'criteria',
      'task_state',
      'user_goal',
      'decision_needed',
      'expected_answer',
      'location_context',
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

  void rememberBusinessResults(
    Map<String, dynamic> mission,
    List<Map<String, dynamic>> businesses,
  ) {
    if (businesses.isEmpty) return;

    final category =
        mission['category']?.toString().trim() ?? '';
    final location =
        mission['location']?.toString().trim() ?? '';

    final summarized = <Map<String, dynamic>>[];

    for (var index = 0;
        index < businesses.length && index < 10;
        index++) {
      final business = businesses[index];
      final naverValue = business['naver'];
      final naver = naverValue is Map
          ? Map<String, dynamic>.from(naverValue)
          : <String, dynamic>{};
      final rawHours = naver['opening_hours'];
      final hours = rawHours is List
          ? rawHours
              .map((item) => item.toString().trim())
              .where((item) => item.isNotEmpty)
              .take(4)
              .toList()
          : <String>[];
      final rawPrices = naver['prices'];
      final prices = rawPrices is List
          ? rawPrices
              .whereType<Map>()
              .take(3)
              .map(
                (item) => {
                  'name': item['name']?.toString().trim() ?? '',
                  'price': item['price']?.toString().trim() ?? '',
                  'currency': item['currency']?.toString().trim() ?? '',
                },
              )
              .toList()
          : <Map<String, dynamic>>[];

      summarized.add({
        'rank': index + 1,
        'name':
            business['name']?.toString().trim() ?? '',
        'address':
            business['address']?.toString().trim() ?? '',
        'phone':
            business['phone']?.toString().trim() ?? '',
        if (hours.isNotEmpty)
          'opening_hours': hours,
        if (naver.containsKey('parking_available'))
          'parking_available':
              naver['parking_available'],
        if (prices.isNotEmpty)
          'prices': prices,
      });
    }

    final resultSet = <String, dynamic>{
      'category': category,
      'location': location,
      'results': summarized,
    };

    _known['recent_place_results'] = summarized;

    final existingValue = _known['recent_place_searches'];
    final history = existingValue is List
        ? existingValue
            .whereType<Map>()
            .map(
              (item) =>
                  Map<String, dynamic>.from(item),
            )
            .toList()
        : <Map<String, dynamic>>[];

    history.removeWhere((item) {
      return item['category'] == category &&
          item['location'] == location;
    });
    history.insert(0, resultSet);

    if (history.length > 3) {
      history.removeRange(3, history.length);
    }

    _known['recent_place_searches'] = history;
  }

  void rememberBusiness(
    Map<String, dynamic> business,
  ) {
    final name =
        business['name']?.toString().trim() ?? '';
    if (name.isNotEmpty) {
      _known['target_business'] = name;
      _known['subject'] = name;
    }

    final address =
        business['address']?.toString().trim() ?? '';
    final phone =
        business['phone']?.toString().trim() ?? '';

    final current = _known['attributes'];
    final merged = current is Map
        ? Map<String, dynamic>.from(current)
        : <String, dynamic>{};

    if (name.isNotEmpty) {
      merged['selected_business_name'] = name;
    }
    if (address.isNotEmpty) {
      merged['selected_business_address'] = address;
    }
    if (phone.isNotEmpty) {
      merged['selected_business_phone'] = phone;
    }

    final naver = business['naver'];
    if (naver is Map) {
      final hours = naver['opening_hours'];
      if (hours is List && hours.isNotEmpty) {
        merged['selected_business_opening_hours'] =
            List<String>.from(
          hours.map((item) => item.toString()),
        );
      }

      if (naver.containsKey('parking_available')) {
        merged['selected_business_parking_available'] =
            naver['parking_available'];
      }
    }

    if (merged.isNotEmpty) {
      _known['attributes'] = merged;
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
