import 'dart:convert';

import 'package:http/http.dart' as http;

class AppUpdateInfo {
  final String downloadUrl;
  final String targetSha;

  const AppUpdateInfo({
    required this.downloadUrl,
    required this.targetSha,
  });
}

class AppUpdateService {
  static const String currentBuildSha = String.fromEnvironment(
    'ARABA_BUILD_SHA',
    defaultValue: 'local',
  );

  static const String _releaseApiUrl =
      'https://api.github.com/repos/kprism/araba/releases/tags/dev-latest';

  Future<AppUpdateInfo?> check() async {
    final current = currentBuildSha.trim();

    if (current.isEmpty || current == 'local') {
      return null;
    }

    final response = await http.get(
      Uri.parse(_releaseApiUrl),
      headers: const {
        'Accept': 'application/vnd.github+json',
      },
    ).timeout(const Duration(seconds: 10));

    if (response.statusCode != 200) {
      return null;
    }

    final data = jsonDecode(response.body);

    if (data is! Map<String, dynamic>) {
      return null;
    }

    final targetSha = data['target_commitish']?.toString().trim() ?? '';

    if (targetSha.isEmpty ||
        targetSha == current ||
        targetSha.startsWith(current) ||
        current.startsWith(targetSha)) {
      return null;
    }

    final assets = data['assets'];

    if (assets is! List) {
      return null;
    }

    for (final asset in assets) {
      if (asset is! Map<String, dynamic>) {
        continue;
      }

      if (asset['name']?.toString() != 'araba-dev.apk') {
        continue;
      }

      final url = asset['browser_download_url']?.toString().trim();

      if (url == null || url.isEmpty) {
        return null;
      }

      return AppUpdateInfo(
        downloadUrl: url,
        targetSha: targetSha,
      );
    }

    return null;
  }
}
