import 'package:flutter/material.dart';

class TasksScreen extends StatelessWidget {
  const TasksScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const _EmptyScreen(
      icon: Icons.assignment_outlined,
      title: '작업',
      description: 'ARABA에게 맡긴 작업이 여기에 표시됩니다.',
    );
  }
}

class _EmptyScreen extends StatelessWidget {
  final IconData icon;
  final String title;
  final String description;

  const _EmptyScreen({
    required this.icon,
    required this.title,
    required this.description,
  });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
      ),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 48, color: const Color(0xFF667085)),
              const SizedBox(height: 16),
              Text(
                description,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Color(0xFF667085)),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
