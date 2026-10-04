import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../services/app_update_service.dart';
import '../home/home_screen.dart';
import '../my/my_screen.dart';
import '../notifications/notifications_screen.dart';
import '../tasks/tasks_screen.dart';

class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  final AppUpdateService _updateService = AppUpdateService();

  int _selectedIndex = 0;
  bool _updatePromptShown = false;

  static const List<Widget> _screens = [
    HomeScreen(),
    TasksScreen(),
    NotificationsScreen(),
    MyScreen(),
  ];

  @override
  void initState() {
    super.initState();

    WidgetsBinding.instance.addPostFrameCallback((_) {
      _checkForUpdate();
    });
  }

  Future<void> _checkForUpdate() async {
    if (_updatePromptShown) {
      return;
    }

    try {
      final update = await _updateService.check();

      if (!mounted || update == null) {
        return;
      }

      _updatePromptShown = true;

      await showDialog<void>(
        context: context,
        builder: (dialogContext) {
          return AlertDialog(
            title: const Text('새 ARABA 테스트 버전'),
            content: const Text(
              '새로운 개발 버전이 준비되었습니다. '
              '지금 업데이트할 수 있습니다.',
            ),
            actions: [
              TextButton(
                onPressed: () {
                  Navigator.of(dialogContext).pop();
                },
                child: const Text('나중에'),
              ),
              FilledButton(
                onPressed: () async {
                  Navigator.of(dialogContext).pop();

                  final opened = await launchUrl(
                    Uri.parse(update.downloadUrl),
                    mode: LaunchMode.externalApplication,
                  );

                  if (!opened && mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text(
                          '업데이트 다운로드 페이지를 열 수 없습니다.',
                        ),
                      ),
                    );
                  }
                },
                child: const Text('업데이트'),
              ),
            ],
          );
        },
      );
    } catch (_) {
      // 업데이트 확인 실패가 앱 사용을 막아서는 안 된다.
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(index: _selectedIndex, children: _screens),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedIndex,
        onDestinationSelected: (index) {
          setState(() {
            _selectedIndex = index;
          });
        },
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
