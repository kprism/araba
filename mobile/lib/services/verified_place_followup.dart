/// Strict follow-up scope and opening-hour verifier.
/// Never extend an existing cohort based on a model response.
class VerifiedPlaceFollowup {
  static const days = [
    '월요일','화요일','수요일','목요일','금요일','토요일','일요일'
  ];
  static DateTime koreanNow() =>
      DateTime.now().toUtc().add(const Duration(hours: 9));

  static String compact(String s) => s.replaceAll(RegExp(r'\s+'), '');
  static const spokenHours = <String,int>{
    '스물세':23,'스물두':22,'스물한':21,'스무':20,
    '열아홉':19,'열여덟':18,'열일곱':17,'열여섯':16,
    '열다섯':15,'열네':14,'열세':13,'열두':12,'열한':11,
    '열':10,'아홉':9,'여덟':8,'일곱':7,'여섯':6,
    '다섯':5,'네':4,'세':3,'두':2,'한':1,
  };
  static String normalizeSpokenHours(String text) {
    final clockWords = spokenHours.keys.join('|');
    return text.replaceAllMapped(
      RegExp('($clockWords)시'),
      (match) => '${spokenHours[match.group(1)]}시',
    );
  }
  static final _clockToken = RegExp(
    r'(?<![0-9A-Za-z])(?:(오전|오후|am|pm)\s*)?'
    r'(\d{1,2})(?::(\d{2})|시(?:\s*(\d{1,2})분)?)'
    r'\s*(오전|오후|am|pm)?(?!\d)',
    caseSensitive: false,
  );
  static const _englishDays = [
    ['monday', 'mon', 'mo'], ['tuesday', 'tue', 'tu'],
    ['wednesday', 'wed', 'we'], ['thursday', 'thu', 'th'],
    ['friday', 'fri', 'fr'], ['saturday', 'sat', 'sa'],
    ['sunday', 'sun', 'su'],
  ];
  static const _shortDays = ['월', '화', '수', '목', '금', '토', '일'];

  static bool applies(String line, int weekday) {
    final t = compact(line);
    final lower = line.toLowerCase();
    if (t.contains('매일') || lower.contains('daily')) return true;
    if (t.contains(days[weekday - 1])) return true;
    if (weekday <= 5 && t.contains('평일')) return true;
    if (weekday >= 6 && t.contains('주말')) return true;
    final letter = _shortDays[weekday - 1];
    if (RegExp('(?<![월화수목금토일])$letter(?![월화수목금토일])')
        .hasMatch(t)) {
      return true;
    }
    for (final alias in _englishDays[weekday - 1]) {
      if (RegExp('\\b$alias\\b', caseSensitive: false).hasMatch(line)) {
        return true;
      }
    }
    final ranges = RegExp(
      r'([월화수목금토일])(?:요일)?[~\-–]([월화수목금토일])'
    ).allMatches(t);
    for (final m in ranges) {
      final start = _shortDays.indexOf(m.group(1)!) + 1;
      final end = _shortDays.indexOf(m.group(2)!) + 1;
      if (start <= end && weekday >= start && weekday <= end) return true;
      if (start > end && (weekday >= start || weekday <= end)) return true;
    }
    final englishRange = RegExp(
      r'\b(mo|tu|we|th|fr|sa|su|mon|tue|wed|thu|fri|sat|sun)'
      r'\s*[~\-–]\s*'
      r'(mo|tu|we|th|fr|sa|su|mon|tue|wed|thu|fri|sat|sun)\b',
      caseSensitive: false,
    ).firstMatch(lower);
    if (englishRange != null) {
      int dayFor(String value) => _englishDays.indexWhere(
        (aliases) => aliases.contains(value.toLowerCase()),
      ) + 1;
      final first = dayFor(englishRange.group(1)!);
      final last = dayFor(englishRange.group(2)!);
      if (first <= last && weekday >= first && weekday <= last) return true;
      if (first > last && (weekday >= first || weekday <= last)) return true;
    }
    return false;
  }

  static List<(int,int)> _ranges(String line) {
    final lower = compact(line).toLowerCase();
    if (line.contains('24시간') || lower.contains('24hours') ||
        lower.contains('open24hours')) {
      return [(0, 1440)];
    }
    final tokens = <(int,String)>[];
    for (final match in _clockToken.allMatches(line)) {
      var hour = int.parse(match.group(2)!);
      final minute = int.parse(match.group(3) ?? match.group(4) ?? '0');
      final period = (match.group(1) ?? match.group(5) ?? '').toLowerCase();
      if (hour > 24 || minute >= 60 ||
          (period.isNotEmpty && (hour < 1 || hour > 12))) {
        continue;
      }
      if ((period == 'pm' || period == '오후') && hour < 12) {
        hour += 12;
      } else if ((period == 'am' || period == '오전') && hour == 12) {
        hour = 0;
      }
      if (hour == 24 && minute != 0) continue;
      tokens.add((hour * 60 + minute, period));
    }
    final ranges = <(int,int)>[];
    for (var index = 0; index + 1 < tokens.length; index += 2) {
      final (opening, openPeriod) = tokens[index];
      var (closing, closePeriod) = tokens[index + 1];
      if ((openPeriod == 'pm' || openPeriod == '오후') &&
          closePeriod.isEmpty && closing < 720) {
        closing += 720;
      }
      if (closing <= opening) closing += 1440;
      ranges.add((opening, closing));
    }
    return ranges;
  }

  /// Normalized identity-checked weekday/start/end windows. Kept separate
  /// so "21시" is compared numerically with 21:00 rather than by text.
  static List<Map<String,dynamic>> normalizedHours(Map<String,dynamic> b) {
    final google = b['google_places'];
    final checkedGoogle = google is Map && google['matched'] == true;
    final naver = b['naver'];
    final checkedNaver = naver is Map &&
        naver['matched'] == true && naver['page_checked'] == true;
    final web = b['openai_web'];
    final checkedWeb = web is Map &&
        web['matched'] == true && web['identity_confirmed'] == true &&
        web['opening_hours_found'] == true &&
        web['sources'] is List &&
        (web['sources'] as List).any((url) =>
          url is String && (url.startsWith('https://') ||
              url.startsWith('http://')));
    final output = <Map<String,dynamic>>[];
    void include(List<Map<String,dynamic>> rows) {
      final selectedDays = output.map((r) => r['weekday']).toSet();
      output.addAll(rows.where((r) =>
          !selectedDays.contains(r['weekday'])));
    }
    final fromServer = b['structured_opening_hours'];
    if (fromServer is List) {
      final checked = fromServer.whereType<Map>().where((r) {
        final source = r['source']?.toString() ?? '';
        return (source.startsWith('google_places') && checkedGoogle) ||
            (source == 'naver_verified_page' && checkedNaver) ||
            (source == 'openai_web_verified' && checkedWeb);
      }).map((r) => Map<String,dynamic>.from(r)).toList();
      include(checked);
    }

    List<Map<String,dynamic>> parseLines(List lines, String source) {
      final output = <Map<String,dynamic>>[];
      for (final value in lines.whereType<String>()) {
        final closed = RegExp(
          r'휴무|휴점|정기휴무|closed|영업안함|운영안함',
          caseSensitive: false,
        ).hasMatch(value);
        for (var weekday = 1; weekday <= 7; weekday++) {
          if (!applies(value, weekday)) continue;
          if (closed) {
            output.add({
              'weekday': days[weekday - 1],
              'closed': true, 'source': source,
            });
          } else {
            for (final (start, end) in _ranges(value)) {
              output.add({
                'weekday': days[weekday - 1],
                'start_minute': start, 'end_minute': end,
                'start_time':
                    '${(start ~/ 60).toString().padLeft(2, '0')}:${(start % 60).toString().padLeft(2, '0')}',
                'end_time':
                    '${(end ~/ 60).toString().padLeft(2, '0')}:${(end % 60).toString().padLeft(2, '0')}',
                'source': source,
              });
            }
          }
        }
      }
      return output;
    }

    if (checkedGoogle) {
      for (final key in ['current_opening_hours','regular_opening_hours']) {
        final lines = google[key];
        if (lines is List) {
          final records = parseLines(lines, 'google_places');
          include(records);
        }
      }
    }
    if (checkedNaver) {
      final lines = naver['opening_hours'];
      if (lines is List) include(parseLines(lines, 'naver_verified_page'));
    }
    if (checkedWeb) {
      final lines = web['opening_hours'];
      if (lines is List) {
        include(parseLines(lines, 'openai_web_verified'));
      }
    }

    // Fresh ARABA Graph weekly facts remain usable even when an upstream
    // provider returns no hours on this particular enrichment attempt.
    final weekly = b['weekly_opening_hours'];
    final fresh = b['araba_fresh_facts'];
    if (b['araba_cache_hit'] == true && fresh is List &&
        fresh.contains('weekly_opening_hours') && weekly is List) {
      for (final rawDay in weekly.whereType<Map>()) {
        final source = rawDay['source']?.toString() ?? '';
        if (!const {
          'google_places_current', 'google_places_regular',
          'naver_verified_page', 'openai_web_verified',
        }.contains(source)) {
          continue;
        }
        final weekday = rawDay['weekday']?.toString() ?? '';
        if (!days.contains(weekday)) {
          continue;
        }
        if (rawDay['status'] == 'closed') {
          include([{'weekday':weekday,'closed':true,'source':source}]);
          continue;
        }
        if (rawDay['status'] != 'open') {
          continue;
        }
        final sessions = rawDay['sessions'];
        if (sessions is! List) {
          continue;
        }
        final rows = <Map<String,dynamic>>[];
        for (final item in sessions.whereType<Map>()) {
          final start = item['start_time']?.toString() ?? '';
          final end = item['end_time']?.toString() ?? '';
          final clock = RegExp(r'^(\d{1,2}):(\d{2})$');
          final a = clock.firstMatch(start);
          final z = clock.firstMatch(end);
          if (a == null || z == null) {
            continue;
          }
          final begin = int.parse(a.group(1)!) * 60 + int.parse(a.group(2)!);
          final finish = int.parse(z.group(1)!) * 60 + int.parse(z.group(2)!);
          if (begin < 0 || begin >= 1440 ||
              finish <= begin || finish > 10080) {
            continue;
          }
          rows.add({
            'weekday':weekday,'start_minute':begin,'end_minute':finish,
            'start_time':start,'end_time':end,'source':source,
          });
        }
        include(rows);
      }
    }
    return output;
  }

  static bool? openThrough(
    Map<String, dynamic> b, int atMinute, {DateTime? nowKst, String? weekday}
  ) {
    final date = nowKst ?? koreanNow();
    final today = weekday ?? days[date.weekday - 1];
    final rows = normalizedHours(b)
        .where((row) => row['weekday'] == today).toList();
    if (rows.isEmpty) return null;
    if (rows.any((row) => row['closed'] == true)) return false;
    for (final row in rows) {
      final start = row['start_minute'];
      final end = row['end_minute'];
      if (start is num && end is num &&
          start <= atMinute && atMinute <= end) {
        return true;
      }
    }
    return false;
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
    final compactText = normalizeSpokenHours(compact(utterance));
    if (!referencesCohort(utterance)) return null;
    final criteria = <Map<String,dynamic>>[];
    final neededFacts = <String>[];
    final clock = RegExp(
      r'(새벽|오전|낮|오후|저녁|밤)?(\d{1,2})시(?:(\d{1,2})분|반)?(까지|이후|넘어서|넘게|에도)'
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
      final minute = clock.group(3) != null
          ? int.tryParse(clock.group(3)!) ?? 0
          : compactText.contains('${clock.group(2)}시반') ? 30 : 0;
      if (minute < 0 || minute >= 60) return null;
      final explicitDay = RegExp(r'[월화수목금토일]요일').firstMatch(
        compactText,
      )?.group(0);
      final targetDay = explicitDay ?? days[koreanNow().weekday-1];
      criteria.add({
        'id':'local_today_closing','field':'closing_time',
        'operator':'gte','value':'${hour.toString().padLeft(2, '0')}:${minute.toString().padLeft(2, '0')}',
        'day':targetDay, 'required':true,
        'label':'$targetDay $hour시까지 영업',
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

  /// The /research/enrich response nests unverified and excluded businesses
  /// inside matching, rather than as top-level fields. The UI must inspect
  /// these enriched candidates before saying no business qualifies.
  static List<Map<String,dynamic>> enrichedCandidates(
    Map<String,dynamic> result,
  ) {
    final matching = result['matching'];
    final matrix = matching is Map ? matching : <String,dynamic>{};
    final output = <Map<String,dynamic>>[];
    for (final raw in [
      result['businesses'],
      matrix['matched_businesses'],
      matrix['unverified_businesses'],
      matrix['excluded_businesses'],
      result['unverified_businesses'],
      result['excluded_businesses'],
    ]) {
      if (raw is! List) continue;
      output.addAll(raw.whereType<Map>().map(
        (item) => Map<String,dynamic>.from(item),
      ));
    }
    return output;
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
            openThrough(b, atMinute, nowKst: nowKst,
              weekday: criterion['day']?.toString()) != true) {
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
        if (field == 'parking_available' && !checkedNaver) {
          return false;
        }
        if (field == 'price' && !checkedNaver &&
            b['verified_total_price'] == null) {
          return false;
        }
        return facts.whereType<Map>().any((fact) =>
            fact['field'] == criterion['field'] &&
            fact['operator'] == criterion['operator'] &&
            fact['state'] == 'match' &&
            (fact['source']?.toString().trim().isNotEmpty ?? false));
      });
    }).toList();
  }
}
