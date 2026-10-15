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
    for (final source in [b['google_places'], b['naver']]) {
      if (source is! Map) continue;
      for (final key in [
        'current_opening_hours','regular_opening_hours','opening_hours'
      ]) {
        final value = source[key];
        if (value is List) {
          found.addAll(value.whereType<String>());
        }
      }
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
    ).hasMatch(s))) return false;
    final closingTimes = <int>[];
    for (final line in lines) {
      if (line.contains('24시간')) {
        closingTimes.add(1440);
      }
      final matches = RegExp(
        r'(\d{1,2}):(\d{2})\s*[~\-–]\s*(\d{1,2}):(\d{2})'
      ).allMatches(line);
      for (final m in matches) {
        final start = int.parse(m.group(1)!) * 60 + int.parse(m.group(2)!);
        var end = int.parse(m.group(3)!) * 60 + int.parse(m.group(4)!);
        if (start > 1440 || end > 1440) continue;
        if (end <= start) end += 1440;
        closingTimes.add(end);
      }
    }
    if (closingTimes.isEmpty) return null;
    closingTimes.sort();
    return closingTimes.last >= atMinute;
  }

  static Map<String, dynamic>? missionFor(
    String utterance, List<Map<String,dynamic>> visible,
    Map<String,dynamic> context,
  ) {
    if (visible.isEmpty) return null;
    final compactText = compact(utterance);
    if (!RegExp(r'그중|이중|그안에서|그가운데|그곳중|이곳중|그3곳중')
        .hasMatch(compactText)) return null;
    if (RegExp(r'말고|대신|다른곳|더찾|추가로|범위넓').hasMatch(compactText)) {
      return null;
    }
    final clock = RegExp(
      r'(새벽|오전|낮|오후|저녁|밤)?(\d{1,2})시(까지|이후|넘어서|넘게|에도)'
    ).firstMatch(compactText);
    if (clock == null) return null;
    var hour = int.parse(clock.group(2)!);
    final timeOfDay = clock.group(1) ?? '';
    if (hour < 1 || hour > 24) return null;
    if (timeOfDay == '새벽' && hour <= 11) hour += 24;
    if ((timeOfDay == '오후' || timeOfDay == '저녁' ||
         timeOfDay == '밤' || timeOfDay.isEmpty) && hour <= 11) hour += 12;
    if (timeOfDay == '오전' && hour == 12) hour = 0;
    if (hour > 35) {
      return null;
    }
    return {
      'intent':'place_search','search_mode':'comparison',
      'response_mode':'research','ready_to_research':true,
      'category': context['category']?.toString() ?? '업체',
      'location': context['location']?.toString() ?? '',
      'user_goal':utterance, 'summary':utterance,
      'requested_count':visible.length,
      'attributes':{'reuse_recent_results':true,'strict_original_cohort':true},
      'criteria':[{
        'id':'local_today_closing','field':'closing_time',
        'operator':'gte','value':'${hour.toString().padLeft(2,'0')}:00',
        'day':days[koreanNow().weekday-1], 'required':true,
        'label':'오늘 ${hour}시까지 영업'
      }],
      'required_facts':['오늘 영업시간'], 'comparison':'criteria_filter'
    };
  }

  static List<Map<String,dynamic>> confirmed(
    List<Map<String,dynamic>> original,
    List<Map<String,dynamic>> returned,
    Map<String,dynamic> mission, {DateTime? nowKst}
  ) {
    String identity(Map<String,dynamic> b) =>
      '${b['id']?.toString() ?? ''}|${b['name']?.toString().trim().toLowerCase() ?? ''}|${b['address']?.toString().trim().toLowerCase() ?? ''}';
    final allowed = original.map(identity).toSet();
    final seen = <String>{};
    final raw = mission['criteria'];
    final criteria = raw is List ? raw.whereType<Map>() : <Map>[];
    final times = criteria.where((x) =>
      x['field'] == 'closing_time' && x['operator'] == 'gte');
    int? minute;
    if (times.isNotEmpty) {
      final match = RegExp(r'^(\d{1,2}):(\d{2})$')
          .firstMatch(times.first['value']?.toString() ?? '');
      if (match != null) {
        minute = int.parse(match.group(1)!) * 60 + int.parse(match.group(2)!);
      }
    }
    return returned.where((b) {
      final key = identity(b);
      if (!allowed.contains(key) || !seen.add(key)) return false;
      if (minute != null && openThrough(b, minute, nowKst: nowKst) != true) {
        return false;
      }
      return true;
    }).toList();
  }
}
