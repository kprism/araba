import 'package:url_launcher/url_launcher.dart';

/// Deterministic routing for movement requests, independently of place search.
/// The map application resolves place names. ARABA never invents coordinates.
class NavigationRequest {
  final String origin;
  final String destination;
  final List<String> waypoints;
  final String travelMode;
  final bool travelModeExplicit;
  final bool currentLocation;

  const NavigationRequest({
    required this.origin,
    required this.destination,
    this.waypoints = const [],
    this.travelMode = 'driving',
    this.travelModeExplicit = false,
    this.currentLocation = false,
  });

  NavigationRequest fromCurrentLocation() => NavigationRequest(
        origin: '',
        destination: destination,
        waypoints: waypoints,
        travelMode: travelMode,
        travelModeExplicit: travelModeExplicit,
        currentLocation: true,
      );

  NavigationRequest toDestination(String value) => NavigationRequest(
        origin: origin,
        destination: value,
        waypoints: waypoints,
        travelMode: travelMode,
        travelModeExplicit: travelModeExplicit,
        currentLocation: currentLocation,
      );



  NavigationRequest withTravelMode(String mode) => NavigationRequest(
        origin: origin,
        destination: destination,
        waypoints: waypoints,
        travelMode: mode,
        travelModeExplicit: true,
        currentLocation: currentLocation,
      );

  /// No map provider may silently choose a transportation method.
  static String? explicitTravelMode(String text) {
    final input = normalizeUtterance(text)
        .split(RegExp(r'아니라|말고'))
        .last
        .trim();
    // The latest explicitly selected mode wins a spoken correction.
    // Require transport wording instead of matching place names such as
    // "버스정류장" and "자동차정비소".
    if (RegExp(
      r'대중교통|(?:버스|지하철|전철|기차|열차)(?:로|를|타고|이용|편으로|편)|'
      r'(?:버스|지하철|전철)\s+(?:타고|이용)',
    ).hasMatch(input)) {
      return 'transit';
    }
    if (RegExp(r'도보|걸어서|걸어가|걷기|걸어갈|걸어\s+가').hasMatch(input)) {
      return 'walking';
    }
    if (RegExp(r'자전거(?:로|타고|를)?').hasMatch(input)) {
      return 'bicycling';
    }
    if (RegExp(
      r'자동차(?:로|를|타고|이용|운전|\s+길)|'
      r'자가용(?:으로|타고|을)|'
      r'차(?:로|를?\s*타고)|승용차(?:로|타고)|'
      r'차량(?:으로|을\s+이용)|운전해서|드라이브',
    ).hasMatch(input)) {
      return 'driving';
    }
    return null;
  }

  static String travelModeLabel(String mode) => switch (mode) {
    'transit' => '대중교통',
    'walking' => '도보',
    'bicycling' => '자전거',
    _ => '자동차',
  };

  /// Speech recognition may include non-speech markers and short fillers.
  /// Never send them as place names or allow them into a map deep link.
  static String normalizeUtterance(String input) {
    return input
        .replaceAll(
          RegExp(
            r'\[(?:cough|coughing|laugh|laughter|breath|breathing|'
            r'sigh|noise|music|silence|applause|inaudible|sniff|'
            r'clears throat)[^\]]*\]',
            caseSensitive: false,
          ),
          ' ',
        )
        .replaceAll(RegExp(r'^(?:(?:어|음|아|저기|그러니까|아니|아니야|잠깐)[,\s]+)+'), '')
        .replaceFirst(
          RegExp(r'^(?:지금\s+)?(?:여기서|이곳에서)\s*[-,:：]?\s*'),
          '여기에서 ',
        )
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
  }

  static bool hasNavigationIntent(String value) {
    final text = normalizeUtterance(value);
    if (text.isEmpty) return false;
    return RegExp(
      r'길(?:을|좀|만)?\s*(?:좀\s*)?(?:알려|안내|찾|보여)|가는\s*길|가는\s*법|'
      r'길찾기|경로|내비(?:게이션)?|네비(?:게이션)?|'
      r'길\s*안내|안내해|가려면|어떻게\s*가|'
      r'몇\s*분\s*걸려|얼마나\s*걸려|거쳐\s*\S+까지',
    ).hasMatch(text) ||
        RegExp(r'\S+(?:에서|부터)\s+\S+까지\s*(?:가|이동|출발)')
            .hasMatch(text);
  }

  static bool isCurrentOriginFollowUp(String text) {
    final compact = text.replaceAll(RegExp(r'\s+'), '');
    return RegExp(
      r'^(?:지금)?(?:여기|여기서|현재위치|내위치|이곳)'
      r'(?:에서|부터)?(?:출발해|출발할게|출발|로해줘|야|로)?[.!]?$',
    ).hasMatch(compact);
  }

  static String _cleanPlace(String value) {
    return value
        .replaceAll(RegExp(r'^(?:지금\s+|출발지(?:는|가)?\s*[:：]?\s*)'), '')
        .replaceAll(RegExp(r'[\s,.!?]+$'), '')
        .trim();
  }

  static bool _isCurrent(String value) {
    final compact = value.replaceAll(RegExp(r'\s+'), '');
    return {
      '여기',
      '지금여기',
      '현재위치',
      '내위치',
      '현재내위치',
      '지금있는곳',
      '이곳',
      '내가있는곳',
    }.contains(compact);
  }

  static NavigationRequest? tryParse(String utterance) {
    final text = normalizeUtterance(utterance);
    if (!hasNavigationIntent(text)) return null;

    final requestedMode = explicitTravelMode(text);
    final mode = requestedMode ?? 'driving';

    String origin = '';
    String destination = '';
    String path = '';
    final startToEnd = RegExp(
      r'(.+?)(?:에서|부터)\s+(.+?)(?:까지|(?:으)?로(?=\s*(?:가는|가|안내|길|이동)))(?=\s|$)',
    ).firstMatch(text);

    if (startToEnd != null) {
      origin = _cleanPlace(startToEnd.group(1) ?? '');
      path = startToEnd.group(2)?.trim() ?? '';
    } else {
      // "여기서 창원 대산고등학교 가는 길" states the origin but omits
      // "까지". Keep the explicit current origin out of the destination.
      final hereToDestination = RegExp(
        r'^(?:여기에서|여기서|현재\s*위치에서|내\s*위치에서)\s+'
        r'(.+?)\s+가는\s*길',
      ).firstMatch(text);
      if (hereToDestination != null) {
        path = hereToDestination.group(1)?.trim() ?? '';
      }
      final labels = RegExp(
        r'출발지(?:는|가)?\s*[:：]?\s*(.+?)[,，]\s*'
        r'목적지(?:는|가)?\s*[:：]?\s*(.+?)(?:\s+(?:로|까지)\s*|$)',
      ).firstMatch(text);
      if (labels != null) {
        origin = _cleanPlace(labels.group(1) ?? '');
        path = labels.group(2)?.trim() ?? '';
      } else if (path.isEmpty) {
        final onlyDestination = RegExp(
          r'^(?:지금\s+)?(.+?)\s*까지(?:\s|$)',
        ).firstMatch(text);
        final destinationOnly =
            onlyDestination ??
            RegExp(r'^(.+?)(?:으로|로)\s*(?:가는|가|안내|길|경로)')
                .firstMatch(text) ??
            RegExp(r'^(.+?)\s+가는\s*길').firstMatch(text);
        if (destinationOnly == null) return null;
        path = destinationOnly.group(1)?.trim() ?? '';
      }
    }

    if (path.isEmpty) return null;
    final segments = path
        .split(RegExp(r'\s*(?:을|를)?\s*거쳐\s*'))
        .map(_cleanPlace)
        .where((item) => item.isNotEmpty)
        .toList();
    if (segments.isEmpty) return null;
    destination = segments.last;
    if (destination == origin || destination.isEmpty) return null;

    final current = origin.isEmpty || _isCurrent(origin);
    return NavigationRequest(
      origin: current ? '' : origin,
      destination: destination,
      waypoints: segments.length > 1
          ? segments.sublist(0, segments.length - 1)
          : const [],
      travelMode: mode,
      travelModeExplicit: requestedMode != null,
      currentLocation: current,
    );
  }
}

class NavigationLauncher {
  static Uri directionsUri(
    NavigationRequest request, {
    double? latitude,
    double? longitude,
  }) {
    if (request.destination.trim().isEmpty) {
      throw ArgumentError('목적지가 필요합니다.');
    }
    if (request.currentLocation &&
        (latitude == null || longitude == null)) {
      throw ArgumentError('현재 위치를 확인해야 합니다.');
    }
    final origin = request.currentLocation
        ? '$latitude,$longitude'
        : request.origin;
    return Uri.https('www.google.com', '/maps/dir/', {
      'api': '1',
      'origin': origin,
      'destination': request.destination,
      'travelmode': request.travelMode,
      if (request.waypoints.isNotEmpty)
        'waypoints': request.waypoints.join('|'),
    });
  }

  static Future<bool> open(Uri uri) async {
    final opened = await launchUrl(
      uri,
      mode: LaunchMode.externalApplication,
    );
    return opened;
  }
}
