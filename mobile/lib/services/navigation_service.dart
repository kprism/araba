import 'package:url_launcher/url_launcher.dart';

/// Deterministic routing for movement requests, independently of place search.
/// The map application resolves place names. ARABA never invents coordinates.
class NavigationRequest {
  final String origin;
  final String destination;
  final List<String> waypoints;
  final String travelMode;
  final bool currentLocation;

  const NavigationRequest({
    required this.origin,
    required this.destination,
    this.waypoints = const [],
    this.travelMode = 'driving',
    this.currentLocation = false,
  });

  NavigationRequest fromCurrentLocation() => NavigationRequest(
        origin: '',
        destination: destination,
        waypoints: waypoints,
        travelMode: travelMode,
        currentLocation: true,
      );

  NavigationRequest toDestination(String value) => NavigationRequest(
        origin: origin,
        destination: value,
        waypoints: waypoints,
        travelMode: travelMode,
        currentLocation: currentLocation,
      );

  static bool hasNavigationIntent(String value) {
    final text = value.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (text.isEmpty) return false;
    return RegExp(
      r'길\s*(?:알려|안내|찾|보여)|가는\s*길|가는\s*법|'
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
    final raw = utterance.replaceAll(RegExp(r'\s+'), ' ').trim();
    // "여기서" has a contracted case particle. Canonicalize it before
    // parsing to avoid treating "여기서 목적지" as the destination itself.
    final text = raw.replaceFirst(
      RegExp(r'^(?:지금\s+)?여기서\s+'),
      '여기에서 ',
    );
    if (!hasNavigationIntent(text)) return null;

    final mode = RegExp(r'대중교통|버스|지하철|전철').hasMatch(text)
        ? 'transit'
        : RegExp(r'도보|걸어서|걸어가는').hasMatch(text)
            ? 'walking'
            : RegExp(r'자전거|자전거로').hasMatch(text)
                ? 'bicycling'
                : 'driving';

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
      final labels = RegExp(
        r'출발지(?:는|가)?\s*[:：]?\s*(.+?)[,，]\s*'
        r'목적지(?:는|가)?\s*[:：]?\s*(.+?)(?:\s+(?:로|까지)\s*|$)',
      ).firstMatch(text);
      if (labels != null) {
        origin = _cleanPlace(labels.group(1) ?? '');
        path = labels.group(2)?.trim() ?? '';
      } else {
        final onlyDestination = RegExp(
          r'^(?:지금\s+)?(.+?)\s*까지(?:\s|$)',
        ).firstMatch(text);
        if (onlyDestination == null) return null;
        path = onlyDestination.group(1)?.trim() ?? '';
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
