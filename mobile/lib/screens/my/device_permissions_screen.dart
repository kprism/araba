import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../services/device_permissions.dart';

class DevicePermissionsScreen extends StatefulWidget {
  const DevicePermissionsScreen({super.key, this.firstRun = false});
  final bool firstRun;
  @override
  State<DevicePermissionsScreen> createState() => _DevicePermissionsScreenState();
}

class _DevicePermissionsScreenState extends State<DevicePermissionsScreen>
    with WidgetsBindingObserver {
  Map<String, bool> _status = {};
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _refresh();
  }

  Future<void> _refresh() async {
    try {
      final status = await DevicePermissions.status();
      if (mounted) setState(() => _status = status);
    } on PlatformException catch (e) {
      if (mounted) setState(() => _error = e.message ?? '권한 조회 실패');
    }
  }

  Future<void> _request() async {
    if (_busy) return;
    setState(() { _busy = true; _error = null; });
    try {
      final status = await DevicePermissions.requestAll();
      if (mounted) setState(() => _status = status);
    } on PlatformException catch (e) {
      if (mounted) setState(() => _error = e.message ?? '권한 요청 실패');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _done() async {
    await DevicePermissions.markFirstRunComplete();
    if (mounted) Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.firstRun ? 'ARABA 사용 권한 준비' : '앱 권한 관리'),
        automaticallyImplyLeading: !widget.firstRun,
      ),
      body: SafeArea(child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text(
            '필요한 권한을 한곳에서 확인하고 설정할 수 있습니다. '
            'Android는 설치하기 전에 권한을 일괄 승인할 수 없으므로 '
            '첫 실행 시 시스템 승인창을 표시합니다. '
            '거절한 권한이 있어도 검색 등 다른 기능은 이용할 수 있습니다.',
            style: TextStyle(fontSize: 14, height: 1.5),
          ),
          const SizedBox(height: 15),
          for (final entry in DevicePermissions.permissionNames.entries)
            Card(child: ListTile(
              title: Text(entry.value, style: const TextStyle(fontSize: 14)),
              trailing: Text(
                _status[entry.key] == true ? '허용됨' : '미허용',
                style: TextStyle(
                  fontWeight: FontWeight.w700,
                  color: _status[entry.key] == true
                      ? const Color(0xFF027A48) : const Color(0xFF946200),
                ),
              ),
            )),
          const SizedBox(height: 10),
          if (_error != null) Text(_error!, style: const TextStyle(color: Colors.red)),
          FilledButton.icon(
            onPressed: _busy ? null : _request,
            icon: const Icon(Icons.verified_user_outlined),
            label: Text(_busy ? '권한 확인 중…' : '필요한 권한 한 번에 요청'),
          ),
          OutlinedButton.icon(
            onPressed: () async {
              try {
                await DevicePermissions.openSettings();
              } on PlatformException catch (e) {
                if (mounted) setState(() => _error = e.message);
              }
            },
            icon: const Icon(Icons.settings_outlined),
            label: const Text('Android 앱 권한 설정 열기'),
          ),
          TextButton.icon(
            onPressed: _refresh,
            icon: const Icon(Icons.refresh),
            label: const Text('현재 권한 다시 확인'),
          ),
          if (widget.firstRun)
            TextButton(
              onPressed: _done,
              child: const Text('설정 완료 · ARABA 시작 (나중에 변경 가능)'),
            ),
        ],
      )),
    );
  }
}
