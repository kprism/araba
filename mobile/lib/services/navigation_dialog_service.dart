import 'navigation_service.dart';

/// A navigation task survives incomplete speech recognition, clarifications,
/// and corrections. Unrelated requests must remain available to the normal AI.
class NavigationDialogDecision {
  const NavigationDialogDecision({this.route, this.question});
  final NavigationRequest? route;
  final String? question;
}

class NavigationDialogState {
  NavigationRequest? _last;
  bool _awaitingDestination = false;
  bool _awaitingMode = false;
  bool _currentOrigin = true;
  String _origin = '';

  NavigationRequest? get lastRoute => _last;
  bool get waitingForDestination => _awaitingDestination;
  bool get waitingForTravelMode => _awaitingMode;

  NavigationDialogDecision _readyOrAskMode(NavigationRequest route) {
    _last = route;
    _origin = route.origin;
    _currentOrigin = route.currentLocation;
    _awaitingDestination = false;
    if (route.travelModeExplicit) {
      _awaitingMode = false;
      return NavigationDialogDecision(route: route);
    }
    _awaitingMode = true;
    return const NavigationDialogDecision(
      question: '어떤 방법으로 이동하시나요? 자동차, 대중교통, 도보 중 선택해 주세요.',
    );
  }

  static String? _modeReply(String text) {
    final cleaned = NavigationRequest.normalizeUtterance(text);
    // The latest choice wins after '아니라 / 말고'.
    final active = cleaned.split(RegExp(r'아니라|말고')).last.trim();
    final compact = active.replaceAll(RegExp(r'\s+'), '');
    if (RegExp(
      r'^(?:자동차|차|자가용|승용차|운전|차로|자동차로)'
      r'(?:로|으로|타고|갈게|가자|해줘|안내해줘|갈래|갈거야)?[.!]?$',
    ).hasMatch(compact)) {
      return 'driving';
    }
    if (RegExp(
      r'^(?:대중교통|버스|지하철|전철)'
      r'(?:으로|로|타고|갈게|가자|해줘|안내해줘|갈래|갈거야)?[.!]?$',
    ).hasMatch(compact)) {
      return 'transit';
    }
    if (RegExp(
      r'^(?:도보|걸어서|걷기|걸어)'
      r'(?:로|갈게|가자|해줘|안내해줘|갈래|갈거야)?[.!]?$',
    ).hasMatch(compact)) {
      return 'walking';
    }
    return NavigationRequest.explicitTravelMode(active);
  }


  void awaitCorrection() {
    // Keep the attempted route when a map provider cannot resolve a place.
    _awaitingDestination = true;
    _awaitingMode = false;
  }

  void reset() {
    _awaitingDestination = false;
    _awaitingMode = false;
    _last = null;
    _origin = '';
    _currentOrigin = true;
  }

  static bool _currentOriginReply(String text) {
    final compact = text.replaceAll(RegExp(r'\s+'), '');
    return NavigationRequest.isCurrentOriginFollowUp(text) ||
        RegExp(r'^(?:출발지는?|출발지는)(?:지금)?(?:여기|현재위치|내위치)(?:야|입니다|로|에서)?[.!]?$')
            .hasMatch(compact);
  }

  static String? _explicitOriginReply(String text) {
    final match = RegExp(
      r'^(?:출발지(?:는|가)?|출발은)\s*[:：]?\s*(.+?)(?:야|입니다|으로|로)?[.!]?$',
    ).firstMatch(text);
    return match?.group(1)?.trim();
  }

  static bool _isUnrelatedNewRequest(String text) {
    // Do not convert a new shop search or everyday conversation into a route.
    return RegExp(
      r'찾아(?:줘|서|주세요)|검색|추천|예약|식사|가격|영업시간|판매|몇\s*곳|'
      r'사진|전화번호|주차|기사|뉴스|날씨|알아봐',
    ).hasMatch(text) &&
        !NavigationRequest.hasNavigationIntent(text);
  }

  static String? _destinationReply(
    String text, {
    required bool awaiting,
  }) {
    final compact = text.trim();
    if (compact.isEmpty) return null;

    var clean = compact
        // The last explicit correction wins, not the misheard earlier place.
        .replaceFirst(RegExp(r'^.*(?:아니고|아니라|말고)\s*'), '')
        .replaceFirst(RegExp(r'^(?:아니[,.! ]*|아니야[,.! ]*|잠깐[,.! ]*|정정할게[,.! ]*|그거\s*말고\s*)'), '')
        .replaceFirst(RegExp(r'^(?:목적지|도착지)(?:는|가|를|는요)?\s*[:：]?\s*'), '')
        .replaceFirst(RegExp(r'^(?:그곳\s*말고\s*|거기\s*말고\s*)'), '')
        .replaceAll(RegExp(r'(?:으로|로)\s*(?:가(?:줘|자|는\s*길|려고|겠어|겠습니다)?|갈\s*거(?:야|예요|에요|다)|갈래|안내해줘|길\s*알려줘|변경해줘)?[.!]?
        .replaceAll(RegExp(r'(?:까지)\s*(?:가줘|안내해줘|가자)?[.!]?$'), '')
        .replaceAll(RegExp(r'(?:갈\s*거(?:야|예요|에요|다)|가려고|가겠어|갈래)[.!]?
        .replaceAll(RegExp(r'[\s,.!?]+$'), '')
        .trim();

    final explicit = RegExp(r'목적지|도착지|정정|아니|말고|변경|(?:로|으로)\s*(?:가줘|가자|안내)|까지')
        .hasMatch(compact);
    if (!awaiting && !explicit) return null;
    if (clean.isEmpty || clean.length > 90) return null;
    if (RegExp(r'길\s*(?:알려|안내)|내비|네비|어디|어떻게|왜|무엇|뭐').hasMatch(clean)) {
      return null;
    }
    if (RegExp(r'^(?:여기|현재위치|내위치|지금여기)$').hasMatch(clean)) {
      return null;
    }
    return clean;
  }

  NavigationDialogDecision? interpret(String utterance) {
    // Keep the speaker's correction signal before speech cleanup removes
    // filler words such as '아니, ...'.
    final correctionSpoken = RegExp(
      r'^(?:아니|잠깐|정정|목적지|도착지|그곳|거기)',
    ).hasMatch(utterance.trim());
    final text = NavigationRequest.normalizeUtterance(utterance);
    if (text.isEmpty) return null;

    // A correction such as "아니, 창원시청으로 안내해줘" looks like a
    // complete navigation command to the generic parser. It must instead
    // replace only the destination, retaining the previously selected mode.
    final correctingDestination = _last != null &&
        (correctionSpoken ||
            RegExp(r'^(?:아니|잠깐|정정|목적지|도착지|그곳|거기)')
                .hasMatch(text)) &&
        !RegExp(r'(?:에서|부터)\s+.+(?:까지)').hasMatch(text) &&
        NavigationRequest.explicitTravelMode(text) == null;
    if (correctingDestination) {
      final corrected = _destinationReply(text, awaiting: true);
      if (corrected != null) {
        return _readyOrAskMode(_last!.toDestination(corrected));
      }
    }

    final full = NavigationRequest.tryParse(text);
    if (full != null) {
      return _readyOrAskMode(full);
    }

    // An answer to our transport question continues the same route rather
    // than falling through to unrelated business search.
    if (_awaitingMode && _last != null) {
      if (_isUnrelatedNewRequest(text)) {
        _awaitingMode = false;
        return null;
      }
      final selected = _modeReply(text);
      if (selected != null) {
        return _readyOrAskMode(_last!.withTravelMode(selected));
      }
      if (!NavigationRequest.hasNavigationIntent(text) &&
          !RegExp(r'목적지|출발지|아니고|말고|여기서').hasMatch(text)) {
        return const NavigationDialogDecision(
          question: '자동차, 대중교통, 도보 중 어떤 방법으로 이동하시나요?',
        );
      }
    }

    final navigationIntent = NavigationRequest.hasNavigationIntent(text);
    if (!navigationIntent && !_awaitingDestination && !_awaitingMode && _last == null) {
      return null;
    }

    if (_currentOriginReply(text)) {
      _currentOrigin = true;
      _origin = '';
      final last = _last;
      if (last != null) {
        final changed = last.fromCurrentLocation();
        return _readyOrAskMode(changed);
      }
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '현재 위치에서 출발할게요. 어디까지 길안내할까요?',
      );
    }

    final originReply = _explicitOriginReply(text);
    if (originReply != null && originReply.isNotEmpty) {
      _currentOrigin = false;
      _origin = originReply;
      final last = _last;
      if (last != null) {
        final changed = NavigationRequest(
          origin: _origin,
          destination: last.destination,
          waypoints: last.waypoints,
          travelMode: last.travelMode,
          travelModeExplicit: last.travelModeExplicit,
        );
        _last = changed;
        _awaitingDestination = false;
        return NavigationDialogDecision(route: changed);
      }
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '출발지를 확인했어요. 목적지는 어디인가요?',
      );
    }

    if (_isUnrelatedNewRequest(text)) {
      _awaitingDestination = false;
      _awaitingMode = false;
      return null;
    }

    final destination = _destinationReply(
      text, awaiting: _awaitingDestination,
    );
    if (destination != null) {
      final previous = _last;
      final result = NavigationRequest(
        origin: previous?.origin ?? _origin,
        destination: destination,
        currentLocation: previous?.currentLocation ?? _currentOrigin,
        waypoints: previous?.waypoints ?? const [],
        travelMode: previous?.travelMode ?? 'driving',
        travelModeExplicit: previous?.travelModeExplicit ?? false,
      );
      return _readyOrAskMode(result);
    }

    if (navigationIntent) {
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '길안내 요청으로 이해했어요. 목적지를 정확히 알려주세요. '
            '출발지를 말씀하지 않으면 현재 위치에서 안내할게요.',
      );
    }
    return null;
  }
}
), '')
        .replaceAll(RegExp(r'(?:까지)\s*(?:가줘|안내해줘|가자)?[.!]?$'), '')
        .replaceAll(RegExp(r'(?:이야|야|입니다|이요|요)[.!]?$'), '')
        .replaceAll(RegExp(r'[\s,.!?]+$'), '')
        .trim();

    final explicit = RegExp(r'목적지|도착지|정정|아니|말고|변경|(?:로|으로)\s*(?:가줘|가자|안내)|까지')
        .hasMatch(compact);
    if (!awaiting && !explicit) return null;
    if (clean.isEmpty || clean.length > 90) return null;
    if (RegExp(r'길\s*(?:알려|안내)|내비|네비|어디|어떻게|왜|무엇|뭐').hasMatch(clean)) {
      return null;
    }
    if (RegExp(r'^(?:여기|현재위치|내위치|지금여기)$').hasMatch(clean)) {
      return null;
    }
    return clean;
  }

  NavigationDialogDecision? interpret(String utterance) {
    // Keep the speaker's correction signal before speech cleanup removes
    // filler words such as '아니, ...'.
    final correctionSpoken = RegExp(
      r'^(?:아니|잠깐|정정|목적지|도착지|그곳|거기)',
    ).hasMatch(utterance.trim());
    final text = NavigationRequest.normalizeUtterance(utterance);
    if (text.isEmpty) return null;

    // A correction such as "아니, 창원시청으로 안내해줘" looks like a
    // complete navigation command to the generic parser. It must instead
    // replace only the destination, retaining the previously selected mode.
    final correctingDestination = _last != null &&
        (correctionSpoken ||
            RegExp(r'^(?:아니|잠깐|정정|목적지|도착지|그곳|거기)')
                .hasMatch(text)) &&
        !RegExp(r'(?:에서|부터)\s+.+(?:까지)').hasMatch(text) &&
        NavigationRequest.explicitTravelMode(text) == null;
    if (correctingDestination) {
      final corrected = _destinationReply(text, awaiting: true);
      if (corrected != null) {
        return _readyOrAskMode(_last!.toDestination(corrected));
      }
    }

    final full = NavigationRequest.tryParse(text);
    if (full != null) {
      return _readyOrAskMode(full);
    }

    // An answer to our transport question continues the same route rather
    // than falling through to unrelated business search.
    if (_awaitingMode && _last != null) {
      if (_isUnrelatedNewRequest(text)) {
        _awaitingMode = false;
        return null;
      }
      final selected = _modeReply(text);
      if (selected != null) {
        return _readyOrAskMode(_last!.withTravelMode(selected));
      }
      if (!NavigationRequest.hasNavigationIntent(text) &&
          !RegExp(r'목적지|출발지|아니고|말고|여기서').hasMatch(text)) {
        return const NavigationDialogDecision(
          question: '자동차, 대중교통, 도보 중 어떤 방법으로 이동하시나요?',
        );
      }
    }

    final navigationIntent = NavigationRequest.hasNavigationIntent(text);
    if (!navigationIntent && !_awaitingDestination && !_awaitingMode && _last == null) {
      return null;
    }

    if (_currentOriginReply(text)) {
      _currentOrigin = true;
      _origin = '';
      final last = _last;
      if (last != null) {
        final changed = last.fromCurrentLocation();
        return _readyOrAskMode(changed);
      }
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '현재 위치에서 출발할게요. 어디까지 길안내할까요?',
      );
    }

    final originReply = _explicitOriginReply(text);
    if (originReply != null && originReply.isNotEmpty) {
      _currentOrigin = false;
      _origin = originReply;
      final last = _last;
      if (last != null) {
        final changed = NavigationRequest(
          origin: _origin,
          destination: last.destination,
          waypoints: last.waypoints,
          travelMode: last.travelMode,
          travelModeExplicit: last.travelModeExplicit,
        );
        _last = changed;
        _awaitingDestination = false;
        return NavigationDialogDecision(route: changed);
      }
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '출발지를 확인했어요. 목적지는 어디인가요?',
      );
    }

    if (_isUnrelatedNewRequest(text)) {
      _awaitingDestination = false;
      _awaitingMode = false;
      return null;
    }

    final destination = _destinationReply(
      text, awaiting: _awaitingDestination,
    );
    if (destination != null) {
      final previous = _last;
      final result = NavigationRequest(
        origin: previous?.origin ?? _origin,
        destination: destination,
        currentLocation: previous?.currentLocation ?? _currentOrigin,
        waypoints: previous?.waypoints ?? const [],
        travelMode: previous?.travelMode ?? 'driving',
        travelModeExplicit: previous?.travelModeExplicit ?? false,
      );
      return _readyOrAskMode(result);
    }

    if (navigationIntent) {
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '길안내 요청으로 이해했어요. 목적지를 정확히 알려주세요. '
            '출발지를 말씀하지 않으면 현재 위치에서 안내할게요.',
      );
    }
    return null;
  }
}
), '')
        .replaceAll(RegExp(r'(?:이야|야|입니다|이요|요)[.!]?
        .replaceAll(RegExp(r'[\s,.!?]+$'), '')
        .trim();

    final explicit = RegExp(r'목적지|도착지|정정|아니|말고|변경|(?:로|으로)\s*(?:가줘|가자|안내)|까지')
        .hasMatch(compact);
    if (!awaiting && !explicit) return null;
    if (clean.isEmpty || clean.length > 90) return null;
    if (RegExp(r'길\s*(?:알려|안내)|내비|네비|어디|어떻게|왜|무엇|뭐').hasMatch(clean)) {
      return null;
    }
    if (RegExp(r'^(?:여기|현재위치|내위치|지금여기)$').hasMatch(clean)) {
      return null;
    }
    return clean;
  }

  NavigationDialogDecision? interpret(String utterance) {
    // Keep the speaker's correction signal before speech cleanup removes
    // filler words such as '아니, ...'.
    final correctionSpoken = RegExp(
      r'^(?:아니|잠깐|정정|목적지|도착지|그곳|거기)',
    ).hasMatch(utterance.trim());
    final text = NavigationRequest.normalizeUtterance(utterance);
    if (text.isEmpty) return null;

    // A correction such as "아니, 창원시청으로 안내해줘" looks like a
    // complete navigation command to the generic parser. It must instead
    // replace only the destination, retaining the previously selected mode.
    final correctingDestination = _last != null &&
        (correctionSpoken ||
            RegExp(r'^(?:아니|잠깐|정정|목적지|도착지|그곳|거기)')
                .hasMatch(text)) &&
        !RegExp(r'(?:에서|부터)\s+.+(?:까지)').hasMatch(text) &&
        NavigationRequest.explicitTravelMode(text) == null;
    if (correctingDestination) {
      final corrected = _destinationReply(text, awaiting: true);
      if (corrected != null) {
        return _readyOrAskMode(_last!.toDestination(corrected));
      }
    }

    final full = NavigationRequest.tryParse(text);
    if (full != null) {
      return _readyOrAskMode(full);
    }

    // An answer to our transport question continues the same route rather
    // than falling through to unrelated business search.
    if (_awaitingMode && _last != null) {
      if (_isUnrelatedNewRequest(text)) {
        _awaitingMode = false;
        return null;
      }
      final selected = _modeReply(text);
      if (selected != null) {
        return _readyOrAskMode(_last!.withTravelMode(selected));
      }
      if (!NavigationRequest.hasNavigationIntent(text) &&
          !RegExp(r'목적지|출발지|아니고|말고|여기서').hasMatch(text)) {
        return const NavigationDialogDecision(
          question: '자동차, 대중교통, 도보 중 어떤 방법으로 이동하시나요?',
        );
      }
    }

    final navigationIntent = NavigationRequest.hasNavigationIntent(text);
    if (!navigationIntent && !_awaitingDestination && !_awaitingMode && _last == null) {
      return null;
    }

    if (_currentOriginReply(text)) {
      _currentOrigin = true;
      _origin = '';
      final last = _last;
      if (last != null) {
        final changed = last.fromCurrentLocation();
        return _readyOrAskMode(changed);
      }
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '현재 위치에서 출발할게요. 어디까지 길안내할까요?',
      );
    }

    final originReply = _explicitOriginReply(text);
    if (originReply != null && originReply.isNotEmpty) {
      _currentOrigin = false;
      _origin = originReply;
      final last = _last;
      if (last != null) {
        final changed = NavigationRequest(
          origin: _origin,
          destination: last.destination,
          waypoints: last.waypoints,
          travelMode: last.travelMode,
          travelModeExplicit: last.travelModeExplicit,
        );
        _last = changed;
        _awaitingDestination = false;
        return NavigationDialogDecision(route: changed);
      }
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '출발지를 확인했어요. 목적지는 어디인가요?',
      );
    }

    if (_isUnrelatedNewRequest(text)) {
      _awaitingDestination = false;
      _awaitingMode = false;
      return null;
    }

    final destination = _destinationReply(
      text, awaiting: _awaitingDestination,
    );
    if (destination != null) {
      final previous = _last;
      final result = NavigationRequest(
        origin: previous?.origin ?? _origin,
        destination: destination,
        currentLocation: previous?.currentLocation ?? _currentOrigin,
        waypoints: previous?.waypoints ?? const [],
        travelMode: previous?.travelMode ?? 'driving',
        travelModeExplicit: previous?.travelModeExplicit ?? false,
      );
      return _readyOrAskMode(result);
    }

    if (navigationIntent) {
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '길안내 요청으로 이해했어요. 목적지를 정확히 알려주세요. '
            '출발지를 말씀하지 않으면 현재 위치에서 안내할게요.',
      );
    }
    return null;
  }
}
), '')
        .replaceAll(RegExp(r'(?:까지)\s*(?:가줘|안내해줘|가자)?[.!]?$'), '')
        .replaceAll(RegExp(r'(?:이야|야|입니다|이요|요)[.!]?$'), '')
        .replaceAll(RegExp(r'[\s,.!?]+$'), '')
        .trim();

    final explicit = RegExp(r'목적지|도착지|정정|아니|말고|변경|(?:로|으로)\s*(?:가줘|가자|안내)|까지')
        .hasMatch(compact);
    if (!awaiting && !explicit) return null;
    if (clean.isEmpty || clean.length > 90) return null;
    if (RegExp(r'길\s*(?:알려|안내)|내비|네비|어디|어떻게|왜|무엇|뭐').hasMatch(clean)) {
      return null;
    }
    if (RegExp(r'^(?:여기|현재위치|내위치|지금여기)$').hasMatch(clean)) {
      return null;
    }
    return clean;
  }

  NavigationDialogDecision? interpret(String utterance) {
    // Keep the speaker's correction signal before speech cleanup removes
    // filler words such as '아니, ...'.
    final correctionSpoken = RegExp(
      r'^(?:아니|잠깐|정정|목적지|도착지|그곳|거기)',
    ).hasMatch(utterance.trim());
    final text = NavigationRequest.normalizeUtterance(utterance);
    if (text.isEmpty) return null;

    // A correction such as "아니, 창원시청으로 안내해줘" looks like a
    // complete navigation command to the generic parser. It must instead
    // replace only the destination, retaining the previously selected mode.
    final correctingDestination = _last != null &&
        (correctionSpoken ||
            RegExp(r'^(?:아니|잠깐|정정|목적지|도착지|그곳|거기)')
                .hasMatch(text)) &&
        !RegExp(r'(?:에서|부터)\s+.+(?:까지)').hasMatch(text) &&
        NavigationRequest.explicitTravelMode(text) == null;
    if (correctingDestination) {
      final corrected = _destinationReply(text, awaiting: true);
      if (corrected != null) {
        return _readyOrAskMode(_last!.toDestination(corrected));
      }
    }

    final full = NavigationRequest.tryParse(text);
    if (full != null) {
      return _readyOrAskMode(full);
    }

    // An answer to our transport question continues the same route rather
    // than falling through to unrelated business search.
    if (_awaitingMode && _last != null) {
      if (_isUnrelatedNewRequest(text)) {
        _awaitingMode = false;
        return null;
      }
      final selected = _modeReply(text);
      if (selected != null) {
        return _readyOrAskMode(_last!.withTravelMode(selected));
      }
      if (!NavigationRequest.hasNavigationIntent(text) &&
          !RegExp(r'목적지|출발지|아니고|말고|여기서').hasMatch(text)) {
        return const NavigationDialogDecision(
          question: '자동차, 대중교통, 도보 중 어떤 방법으로 이동하시나요?',
        );
      }
    }

    final navigationIntent = NavigationRequest.hasNavigationIntent(text);
    if (!navigationIntent && !_awaitingDestination && !_awaitingMode && _last == null) {
      return null;
    }

    if (_currentOriginReply(text)) {
      _currentOrigin = true;
      _origin = '';
      final last = _last;
      if (last != null) {
        final changed = last.fromCurrentLocation();
        return _readyOrAskMode(changed);
      }
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '현재 위치에서 출발할게요. 어디까지 길안내할까요?',
      );
    }

    final originReply = _explicitOriginReply(text);
    if (originReply != null && originReply.isNotEmpty) {
      _currentOrigin = false;
      _origin = originReply;
      final last = _last;
      if (last != null) {
        final changed = NavigationRequest(
          origin: _origin,
          destination: last.destination,
          waypoints: last.waypoints,
          travelMode: last.travelMode,
          travelModeExplicit: last.travelModeExplicit,
        );
        _last = changed;
        _awaitingDestination = false;
        return NavigationDialogDecision(route: changed);
      }
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '출발지를 확인했어요. 목적지는 어디인가요?',
      );
    }

    if (_isUnrelatedNewRequest(text)) {
      _awaitingDestination = false;
      _awaitingMode = false;
      return null;
    }

    final destination = _destinationReply(
      text, awaiting: _awaitingDestination,
    );
    if (destination != null) {
      final previous = _last;
      final result = NavigationRequest(
        origin: previous?.origin ?? _origin,
        destination: destination,
        currentLocation: previous?.currentLocation ?? _currentOrigin,
        waypoints: previous?.waypoints ?? const [],
        travelMode: previous?.travelMode ?? 'driving',
        travelModeExplicit: previous?.travelModeExplicit ?? false,
      );
      return _readyOrAskMode(result);
    }

    if (navigationIntent) {
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '길안내 요청으로 이해했어요. 목적지를 정확히 알려주세요. '
            '출발지를 말씀하지 않으면 현재 위치에서 안내할게요.',
      );
    }
    return null;
  }
}
), '')
        .replaceAll(RegExp(r'[\s,.!?]+$'), '')
        .trim();

    final explicit = RegExp(r'목적지|도착지|정정|아니|말고|변경|(?:로|으로)\s*(?:가줘|가자|안내)|까지')
        .hasMatch(compact);
    if (!awaiting && !explicit) return null;
    if (clean.isEmpty || clean.length > 90) return null;
    if (RegExp(r'길\s*(?:알려|안내)|내비|네비|어디|어떻게|왜|무엇|뭐').hasMatch(clean)) {
      return null;
    }
    if (RegExp(r'^(?:여기|현재위치|내위치|지금여기)$').hasMatch(clean)) {
      return null;
    }
    return clean;
  }

  NavigationDialogDecision? interpret(String utterance) {
    // Keep the speaker's correction signal before speech cleanup removes
    // filler words such as '아니, ...'.
    final correctionSpoken = RegExp(
      r'^(?:아니|잠깐|정정|목적지|도착지|그곳|거기)',
    ).hasMatch(utterance.trim());
    final text = NavigationRequest.normalizeUtterance(utterance);
    if (text.isEmpty) return null;

    // A correction such as "아니, 창원시청으로 안내해줘" looks like a
    // complete navigation command to the generic parser. It must instead
    // replace only the destination, retaining the previously selected mode.
    final correctingDestination = _last != null &&
        (correctionSpoken ||
            RegExp(r'^(?:아니|잠깐|정정|목적지|도착지|그곳|거기)')
                .hasMatch(text)) &&
        !RegExp(r'(?:에서|부터)\s+.+(?:까지)').hasMatch(text) &&
        NavigationRequest.explicitTravelMode(text) == null;
    if (correctingDestination) {
      final corrected = _destinationReply(text, awaiting: true);
      if (corrected != null) {
        return _readyOrAskMode(_last!.toDestination(corrected));
      }
    }

    final full = NavigationRequest.tryParse(text);
    if (full != null) {
      return _readyOrAskMode(full);
    }

    // An answer to our transport question continues the same route rather
    // than falling through to unrelated business search.
    if (_awaitingMode && _last != null) {
      if (_isUnrelatedNewRequest(text)) {
        _awaitingMode = false;
        return null;
      }
      final selected = _modeReply(text);
      if (selected != null) {
        return _readyOrAskMode(_last!.withTravelMode(selected));
      }
      if (!NavigationRequest.hasNavigationIntent(text) &&
          !RegExp(r'목적지|출발지|아니고|말고|여기서').hasMatch(text)) {
        return const NavigationDialogDecision(
          question: '자동차, 대중교통, 도보 중 어떤 방법으로 이동하시나요?',
        );
      }
    }

    final navigationIntent = NavigationRequest.hasNavigationIntent(text);
    if (!navigationIntent && !_awaitingDestination && !_awaitingMode && _last == null) {
      return null;
    }

    if (_currentOriginReply(text)) {
      _currentOrigin = true;
      _origin = '';
      final last = _last;
      if (last != null) {
        final changed = last.fromCurrentLocation();
        return _readyOrAskMode(changed);
      }
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '현재 위치에서 출발할게요. 어디까지 길안내할까요?',
      );
    }

    final originReply = _explicitOriginReply(text);
    if (originReply != null && originReply.isNotEmpty) {
      _currentOrigin = false;
      _origin = originReply;
      final last = _last;
      if (last != null) {
        final changed = NavigationRequest(
          origin: _origin,
          destination: last.destination,
          waypoints: last.waypoints,
          travelMode: last.travelMode,
          travelModeExplicit: last.travelModeExplicit,
        );
        _last = changed;
        _awaitingDestination = false;
        return NavigationDialogDecision(route: changed);
      }
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '출발지를 확인했어요. 목적지는 어디인가요?',
      );
    }

    if (_isUnrelatedNewRequest(text)) {
      _awaitingDestination = false;
      _awaitingMode = false;
      return null;
    }

    final destination = _destinationReply(
      text, awaiting: _awaitingDestination,
    );
    if (destination != null) {
      final previous = _last;
      final result = NavigationRequest(
        origin: previous?.origin ?? _origin,
        destination: destination,
        currentLocation: previous?.currentLocation ?? _currentOrigin,
        waypoints: previous?.waypoints ?? const [],
        travelMode: previous?.travelMode ?? 'driving',
        travelModeExplicit: previous?.travelModeExplicit ?? false,
      );
      return _readyOrAskMode(result);
    }

    if (navigationIntent) {
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '길안내 요청으로 이해했어요. 목적지를 정확히 알려주세요. '
            '출발지를 말씀하지 않으면 현재 위치에서 안내할게요.',
      );
    }
    return null;
  }
}
), '')
        .replaceAll(RegExp(r'(?:까지)\s*(?:가줘|안내해줘|가자)?[.!]?$'), '')
        .replaceAll(RegExp(r'(?:이야|야|입니다|이요|요)[.!]?$'), '')
        .replaceAll(RegExp(r'[\s,.!?]+$'), '')
        .trim();

    final explicit = RegExp(r'목적지|도착지|정정|아니|말고|변경|(?:로|으로)\s*(?:가줘|가자|안내)|까지')
        .hasMatch(compact);
    if (!awaiting && !explicit) return null;
    if (clean.isEmpty || clean.length > 90) return null;
    if (RegExp(r'길\s*(?:알려|안내)|내비|네비|어디|어떻게|왜|무엇|뭐').hasMatch(clean)) {
      return null;
    }
    if (RegExp(r'^(?:여기|현재위치|내위치|지금여기)$').hasMatch(clean)) {
      return null;
    }
    return clean;
  }

  NavigationDialogDecision? interpret(String utterance) {
    // Keep the speaker's correction signal before speech cleanup removes
    // filler words such as '아니, ...'.
    final correctionSpoken = RegExp(
      r'^(?:아니|잠깐|정정|목적지|도착지|그곳|거기)',
    ).hasMatch(utterance.trim());
    final text = NavigationRequest.normalizeUtterance(utterance);
    if (text.isEmpty) return null;

    // A correction such as "아니, 창원시청으로 안내해줘" looks like a
    // complete navigation command to the generic parser. It must instead
    // replace only the destination, retaining the previously selected mode.
    final correctingDestination = _last != null &&
        (correctionSpoken ||
            RegExp(r'^(?:아니|잠깐|정정|목적지|도착지|그곳|거기)')
                .hasMatch(text)) &&
        !RegExp(r'(?:에서|부터)\s+.+(?:까지)').hasMatch(text) &&
        NavigationRequest.explicitTravelMode(text) == null;
    if (correctingDestination) {
      final corrected = _destinationReply(text, awaiting: true);
      if (corrected != null) {
        return _readyOrAskMode(_last!.toDestination(corrected));
      }
    }

    final full = NavigationRequest.tryParse(text);
    if (full != null) {
      return _readyOrAskMode(full);
    }

    // An answer to our transport question continues the same route rather
    // than falling through to unrelated business search.
    if (_awaitingMode && _last != null) {
      if (_isUnrelatedNewRequest(text)) {
        _awaitingMode = false;
        return null;
      }
      final selected = _modeReply(text);
      if (selected != null) {
        return _readyOrAskMode(_last!.withTravelMode(selected));
      }
      if (!NavigationRequest.hasNavigationIntent(text) &&
          !RegExp(r'목적지|출발지|아니고|말고|여기서').hasMatch(text)) {
        return const NavigationDialogDecision(
          question: '자동차, 대중교통, 도보 중 어떤 방법으로 이동하시나요?',
        );
      }
    }

    final navigationIntent = NavigationRequest.hasNavigationIntent(text);
    if (!navigationIntent && !_awaitingDestination && !_awaitingMode && _last == null) {
      return null;
    }

    if (_currentOriginReply(text)) {
      _currentOrigin = true;
      _origin = '';
      final last = _last;
      if (last != null) {
        final changed = last.fromCurrentLocation();
        return _readyOrAskMode(changed);
      }
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '현재 위치에서 출발할게요. 어디까지 길안내할까요?',
      );
    }

    final originReply = _explicitOriginReply(text);
    if (originReply != null && originReply.isNotEmpty) {
      _currentOrigin = false;
      _origin = originReply;
      final last = _last;
      if (last != null) {
        final changed = NavigationRequest(
          origin: _origin,
          destination: last.destination,
          waypoints: last.waypoints,
          travelMode: last.travelMode,
          travelModeExplicit: last.travelModeExplicit,
        );
        _last = changed;
        _awaitingDestination = false;
        return NavigationDialogDecision(route: changed);
      }
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '출발지를 확인했어요. 목적지는 어디인가요?',
      );
    }

    if (_isUnrelatedNewRequest(text)) {
      _awaitingDestination = false;
      _awaitingMode = false;
      return null;
    }

    final destination = _destinationReply(
      text, awaiting: _awaitingDestination,
    );
    if (destination != null) {
      final previous = _last;
      final result = NavigationRequest(
        origin: previous?.origin ?? _origin,
        destination: destination,
        currentLocation: previous?.currentLocation ?? _currentOrigin,
        waypoints: previous?.waypoints ?? const [],
        travelMode: previous?.travelMode ?? 'driving',
        travelModeExplicit: previous?.travelModeExplicit ?? false,
      );
      return _readyOrAskMode(result);
    }

    if (navigationIntent) {
      _awaitingDestination = true;
      return const NavigationDialogDecision(
        question: '길안내 요청으로 이해했어요. 목적지를 정확히 알려주세요. '
            '출발지를 말씀하지 않으면 현재 위치에서 안내할게요.',
      );
    }
    return null;
  }
}
