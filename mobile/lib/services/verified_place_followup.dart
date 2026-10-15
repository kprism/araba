/// Strict follow-up scope and opening-hour verifier.
/// Never extend an existing cohort based on a model response.
class VerifiedPlaceFollowup {
  static const days = [
    '월요일','화요일','수요일','목요일','금요일','토요일','일요일'
  ];
  static DateTime koreanNow() =>
      DateTime.now().toUtc().add(const Duration(hours: 9));

  static String compact(String s) => s.replaceAll(RegExp(r'\s+'), '');
  static List<String> hours(Map<String, dynamic> b) {
    final found = <String>[];
    final google = b['google_places'];
    if (google is Map && google['matched'] == true) {
      for (final key in ['current_opening_hours', 'regular_opening_hours']) {
        final value = google[key];
        if (value is List) found.addAll(value.whereType<String>());
      }
    }
    final naver = b['naver'];
    // Search-result snippets or unmatched pages are not hours evidence.
    if (naver is Map &&
        naver['matched'] == true &&
        naver['page_checked'] == true) {
      final value = naver['opening_hours'];
      if (value is List) found.addAll(value.whereType<String>());
    }
    return found;
  }

  static bool applies(String line, int weekday) {
    final t = compact(line);
    if (t.contains('매일') || t.toLowerCase().contains('daily')) return true;
    if (t.contains(days[weekday - 1])) return true;
    if (weekday <= 5 && t.contains('평일')) return true;
    if (weekday >= 6 && t.contains('주말')) return true;
    const short = ['월','화','수','목','금','토','일'];
    final letter = short[weekday - 1];
    if (RegExp('(?<![월화수목금토일])$letter(?![월화수목금토일])')
        .hasMatch(t)) {
      return true;
    }
    final ranges = RegExp(
        r'([월화수목금토일])(?:요일)?[~\-–]([월화수목금토일])').allMatches(t);
    for (final m in ranges) {
      final start = short.indexOf(m.group(1)!) + 1;
      final end = short.indexOf(m.group(2)!) + 1;
      if (start <= end && weekday >= start && weekday <= end) return true;
      if (start > end && (weekday >= start || weekday <= end)) {
        return true;
      }
    }
    return false;
  }

  static bool? openThrough(
    Map<String, dynamic> b, int atMinute, {DateTime? nowKst}
  ) {
    final weekday = (nowKst ?? koreanNow()).weekday;
    final lines = hours(b).where((s) => applies(s, weekday)).toList();
    if (lines.isEmpty) return null;
    if (lines.any((s) => RegExp(
      r'휴무|휴점|정기휴무|closed|영업안함|운영안함', caseSensitive: false
    ).hasMatch(s))) {
      return false;
    }
    var coversRequestedTime = false;
    var foundWindow = false;
    for (final line in lines) {
      if (line.contains('24시간')) {
        foundWindow = true;
        coversRequestedTime = true;
      }
      final matches = RegExp(
        r'(\d{1,2}):(\d{2})\s*[~\-–]\s*(\d{1,2}):(\d{2})'
      ).allMatches(line);
      for (final m in matches) {
        final start = int.parse(m.group(1)!) * 60 + int.parse(m.group(2)!);
        var end = int.parse(m.group(3)!) * 60 + int.parse(m.group(4)!);
        if (start > 1440 || end > 1440) continue;
        if (end <= start) end += 1440;
        if (start > end || start > atMinute) {
          // A business that opens after the requested time is not open then.
          foundWindow = true;
          continue;
        }
        foundWindow = true;
        if (end >= atMinute) coversRequestedTime = true;
      }
    }
    if (!foundWindow) return null;
    return coversRequestedTime;
  }

  /// Whether a new utterance explicitly refers to the existing results.
  /// A fresh-search request is allowed only when the user clearly asks for it.
  static bool referencesCohort(String utterance) {
    final text = compact(utterance);
    final refers = RegExp(
      r'그중|이중|그가운데|이가운데|여기서|그곳중|이곳중|'
      r'아까찾은|방금찾은|이전에찾은|찾은.*곳중|찾은.*업체중|'
      r'위의[0-9]*곳|그[0-9]+곳중'
    ).hasMatch(text);
    final fresh = RegExp(
      r'말고|대신|다른곳|다른업체|더찾|추가로찾|범위넓|새로찾|'
      r'새로운곳|후보추가|다른데도'
    ).hasMatch(text);
    return refers && !fresh;
  }

  /// A Core model must not turn an explicit "그중" into a new search.
  /// Preserve its criteria, but override place scope and execution mode.
  static Map<String, dynamic>? scopeMission(
    String utterance,
    List<Map<String, dynamic>> original,
    Map<String, dynamic> context,
    Map<String, dynamic> parsed,
  ) {
    if (original.isEmpty || !referencesCohort(utterance)) return null;
    final rawAttributes = parsed['attributes'];
    final attributes = rawAttributes is Map
        ? Map<String, dynamic>.from(rawAttributes)
        : <String, dynamic>{};
    attributes['reuse_recent_results'] = true;
    attributes['strict_original_cohort'] = true;
    return {
      ...parsed,
      'intent': 'place_search',
      'search_mode': 'comparison',
      'response_mode': 'research',
      'ready_to_research': true,
      'requested_count': original.length,
      'location': context['location'] ?? parsed['location'] ?? '',
      'category': context['category'] ?? parsed['category'] ?? '업체',
      'user_goal': utterance,
      'summary': utterance,
      'attributes': attributes,
    };
  }

  static Map<String, dynamic>? missionFor(
    String utterance, List<Map<String,dynamic>> visible,
    Map<String,dynamic> context,
  ) {
    if (visible.isEmpty) return null;
    final compactText = compact(utterance);
    if (!referencesCohort(utterance)) return null;
    final criteria = <Map<String,dynamic>>[];
    final neededFacts = <String>[];
    final clock = RegExp(
      r'(새벽|오전|낮|오후|저녁|밤)?(\d{1,2})시(까지|이후|넘어서|넘게|에도)'
    ).firstMatch(compactText);
    if (clock != null) {
      var hour = int.parse(clock.group(2)!);
      final timeOfDay = clock.group(1) ?? '';
      if (hour < 1 || hour > 24) return null;
      if (timeOfDay == '새벽' && hour <= 11) hour += 24;
      if ((timeOfDay == '오후' || timeOfDay == '저녁' ||
           timeOfDay == '밤' || timeOfDay.isEmpty) && hour <= 11) {
        hour += 12;
      }
      if (timeOfDay == '오전' && hour == 12) hour = 0;
      if (hour > 35) return null;
      criteria.add({
        'id':'local_today_closing','field':'closing_time',
        'operator':'gte','value':'${hour.toString().padLeft(2,'0')}:00',
        'day':days[koreanNow().weekday-1], 'required':true,
        'label':'오늘 $hour시까지 영업'
      });
      neededFacts.add('오늘 영업시간');
    }
    if (RegExp(r'주차.*(가능|되는|되고|있는|있고|있나)').hasMatch(compactText)) {
      criteria.add({
        'id':'local_parking', 'field':'parking_available',
        'operator':'eq', 'value':true, 'required':true,
        'label':'주차 가능'
      });
      neededFacts.add('주차 가능 여부');
    }
    if (RegExp(r'가장가까|제일가까|가까운').hasMatch(compactText)) {
      criteria.add({
        'id':'local_nearest', 'field':'distance_m',
        'operator':'min', 'value':null, 'required':true,
        'label':'가장 가까운 곳'
      });
      neededFacts.add('거리');
    }
    if (RegExp(r'가장저렴|제일저렴|가장싼|제일싼').hasMatch(compactText)) {
      criteria.add({
        'id':'local_lowest_price', 'field':'price',
        'operator':'min', 'value':null, 'required':true,
        'label':'가장 저렴한 곳'
      });
      neededFacts.add('가격');
    }
    if (criteria.isEmpty) return null;
    return {
      'intent':'place_search','search_mode':'comparison',
      'response_mode':'research','ready_to_research':true,
      'category': context['category']?.toString() ?? '업체',
      'location': context['location']?.toString() ?? '',
      'user_goal':utterance, 'summary':utterance,
      'requested_count':visible.length,
      'attributes':{'reuse_recent_results':true,'strict_original_cohort':true},
      'criteria':criteria,
      'required_facts':neededFacts, 'comparison':'criteria_filter'
    };
  }

  static List<Map<String,dynamic>> confirmed(
    List<Map<String,dynamic>> original,
    List<Map<String,dynamic>> returned,
    Map<String,dynamic> mission, {
    DateTime? nowKst,
    Map<String,dynamic>? matching,
  }) {
    String identity(Map<String,dynamic> b) =>
      '${b['id']?.toString() ?? ''}|${b['name']?.toString().trim().toLowerCase() ?? ''}|${b['address']?.toString().trim().toLowerCase() ?? ''}';
    final allowed = original.map(identity).toSet();
    final seen = <String>{};
    final raw = mission['criteria'];
    final criteria = raw is List ? raw.whereType<Map>().toList() : <Map>[];
    final required = criteria.where((c) => c['required'] != false).toList();
    if (required.isEmpty) return [];

    final closing = required.where((c) =>
        c['field'] == 'closing_time' && c['operator'] == 'gte').toList();
    final other = required.where((c) =>
        !(c['field'] == 'closing_time' && c['operator'] == 'gte')).toList();
    final rawMatrix = matching?['matrix'];
    final matrix = rawMatrix is List
        ? rawMatrix.whereType<Map>().toList() : <Map>[];

    int? threshold(Map c) {
      final match = RegExp(r'^(\d{1,2}):(\d{2})$')
          .firstMatch(c['value']?.toString() ?? '');
      if (match == null) return null;
      return int.parse(match.group(1)!) * 60 + int.parse(match.group(2)!);
    }

    return returned.where((b) {
      final key = identity(b);
      if (!allowed.contains(key) || !seen.add(key)) return false;
      for (final criterion in closing) {
        final atMinute = threshold(criterion);
        if (atMinute == null ||
            openThrough(b, atMinute, nowKst: nowKst) != true) {
          return false;
        }
      }
      if (other.isEmpty) return true;
      // Non-time conditions need the structured backend evidence matrix;
      // a model summary or a mere presence in the results is not proof.
      final rows = matrix.where((row) =>
          row['business_id']?.toString() == b['id']?.toString() &&
          row['business_name']?.toString().trim() ==
              b['name']?.toString().trim() &&
          row['status'] == 'matched').toList();
      if (rows.isEmpty) return false;
      final facts = rows.first['criteria'];
      if (facts is! List) return false;

      final naver = b['naver'];
      final checkedNaver = naver is Map &&
          naver['matched'] == true && naver['page_checked'] == true;
      return other.every((criterion) {
        final field = criterion['field']?.toString() ?? '';
        if (field == 'parking_available' && !checkedNaver) return false;
        if (field == 'price' && !checkedNaver &&
            b['verified_total_price'] == null) return false;
        return facts.whereType<Map>().any((fact) =>
            fact['field'] == criterion['field'] &&
            fact['operator'] == criterion['operator'] &&
            fact['state'] == 'match' &&
            (fact['source']?.toString().trim().isNotEmpty ?? false));
      });
    }).toList();
  }
}
