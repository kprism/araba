import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../home/home_screen.dart';
import '../merchant/merchant_portal_screen.dart';
import '../my/my_screen.dart';
import '../my/device_permissions_screen.dart';
import '../../services/device_permissions.dart';
import '../notifications/notifications_screen.dart';
import '../tasks/tasks_screen.dart';

enum TestAppRole { administrator, consumer, merchant }

class AppShell extends StatefulWidget {
  const AppShell({super.key});
  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int _selectedIndex = 0;
  TestAppRole _testRole = TestAppRole.administrator;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      unawaited(_openPermissionsOnFirstRun());
    });
  }

  Future<void> _openPermissionsOnFirstRun() async {
    if (defaultTargetPlatform != TargetPlatform.android) return;
    try {
      final needed = await DevicePermissions.firstRunNeeded();
      if (needed && mounted) _openPermissions(firstRun: true);
    } catch (_) {
      // A missing native channel on web/widget tests must not block the app.
    }
  }

  void _openPermissions({bool firstRun = false}) {
    if (!mounted) return;
    Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => DevicePermissionsScreen(firstRun: firstRun),
    ));
  }

  // This is a display-only preview in Android debug builds. In production
  // server-authenticated memberships will decide available roles.
  static const bool _rolePreviewEnabled = kDebugMode;

  Widget _previewBar() => Container(
    color: const Color(0xFFE8EEFF),
    padding: const EdgeInsets.fromLTRB(9, 5, 9, 5),
    child: Row(children: [
      const Padding(
        padding: EdgeInsets.only(right: 7),
        child: Text('테스트', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800)),
      ),
      Expanded(child: SegmentedButton<TestAppRole>(
        style: const ButtonStyle(visualDensity: VisualDensity.compact),
        selected: {_testRole},
        showSelectedIcon: false,
        segments: const [
          ButtonSegment(value: TestAppRole.administrator, label: Text('관리자')),
          ButtonSegment(value: TestAppRole.consumer, label: Text('사용자')),
          ButtonSegment(value: TestAppRole.merchant, label: Text('사업자')),
        ],
        onSelectionChanged: (value) => setState(() {
          _testRole = value.first;
          _selectedIndex = 0;
        }),
      )),
    ]),
  );

  Widget _consumerMy() => const SafeArea(
    child: Padding(
      padding: EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(height: 15),
          Text('MY', style: TextStyle(fontSize: 30, fontWeight: FontWeight.w800)),
          SizedBox(height: 18),
          Text('일반 사용자 화면 미리보기',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
          SizedBox(height: 10),
          Text('내 검색·대리업무·예약 내역과 알림을 확인하는 공간입니다.'),
          SizedBox(height: 12),
          Text('관리자 전용 API 키 설정은 사용자 화면에 표시하지 않습니다.',
              style: TextStyle(color: Color(0xFF667085))),
        ],
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final merchant = _rolePreviewEnabled && _testRole == TestAppRole.merchant;
    final consumer = _rolePreviewEnabled && _testRole == TestAppRole.consumer;
    final screens = <Widget>[
      const HomeScreen(),
      TasksScreen(active: _selectedIndex == 1 && !merchant),
      const NotificationsScreen(),
      consumer ? _consumerMy() : const MyScreen(),
    ];

    return Scaffold(
      body: Column(children: [
        SafeArea(bottom: false, child: Align(
          alignment: Alignment.centerRight,
          child: TextButton.icon(
            onPressed: _openPermissions,
            icon: const Icon(Icons.admin_panel_settings_outlined, size: 17),
            label: const Text('권한 관리'),
          ),
        )),
        if (_rolePreviewEnabled) SafeArea(
          bottom: false,
          child: _previewBar(),
        ),
        Expanded(
          child: merchant
              ? const MerchantPortalScreen()
              : IndexedStack(index: _selectedIndex, children: screens),
        ),
      ]),
      bottomNavigationBar: merchant ? null : NavigationBar(
        selectedIndex: _selectedIndex,
        onDestinationSelected: (index) => setState(() => _selectedIndex = index),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home_rounded),
            label: '홈',
          ),
          NavigationDestination(
            icon: Icon(Icons.assignment_outlined),
            selectedIcon: Icon(Icons.assignment_rounded),
            label: '작업',
          ),
          NavigationDestination(
            icon: Icon(Icons.notifications_none_rounded),
            selectedIcon: Icon(Icons.notifications_rounded),
            label: '알림',
          ),
          NavigationDestination(
            icon: Icon(Icons.person_outline_rounded),
            selectedIcon: Icon(Icons.person_rounded),
            label: 'MY',
          ),
        ],
      ),
    );
  }
}
