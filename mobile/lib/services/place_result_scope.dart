/// UI safety boundary for search counts and result-set follow-ups.
/// AI reasoning may rank results, but must not enlarge or replace the cohort.
class PlaceResultScope {
  static int requestedCount(Map<String, dynamic> mission) {
    final raw = mission['requested_count'];
    final count = raw is num ? raw.toInt() : int.tryParse('$raw');
    return (count ?? 5).clamp(1, 10);
  }

  static String _identity(Map<String, dynamic> item) {
    final id = item['id']?.toString().trim() ?? '';
    final name = item['name']?.toString().trim().toLowerCase() ?? '';
    final address = item['address']?.toString().trim().toLowerCase() ?? '';
    // Require the provider id AND geographic/name identity, rather than
    // accepting a coincidentally reused id with an unrelated address.
    return '${id.isNotEmpty ? id : 'no-id'}|$name|$address';
  }

  static List<Map<String, dynamic>> firstResults(
    Map<String, dynamic> mission,
    List<Map<String, dynamic>> results,
  ) => results.take(requestedCount(mission)).toList();

  static List<Map<String, dynamic>> followup(
    List<Map<String, dynamic>> original,
    List<Map<String, dynamic>> returned,
  ) {
    final allowed = original.map(_identity).toSet();
    final seen = <String>{};
    return returned.where((item) {
      final key = _identity(item);
      return allowed.contains(key) && seen.add(key);
    }).take(original.length).toList();
  }
}
