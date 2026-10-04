import 'package:flutter/material.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final TextEditingController _missionController = TextEditingController();

  @override
  void dispose() {
    _missionController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: Colors.white,
        surfaceTintColor: Colors.white,
        titleSpacing: 20,
        title: const Row(
          children: [
            Text(
              'ARABA',
              style: TextStyle(
                fontWeight: FontWeight.w900,
                letterSpacing: -0.5,
              ),
            ),
            SizedBox(width: 8),
            Text(
              '알아봐',
              style: TextStyle(
                fontSize: 14,
                color: Color(0xFF667085),
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
        actions: [
          Container(
            margin: const EdgeInsets.only(right: 16),
            padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 6),
            decoration: BoxDecoration(
              color: const Color(0xFFEEF4FF),
              borderRadius: BorderRadius.circular(30),
            ),
            child: const Text(
              'POC',
              style: TextStyle(
                color: Color(0xFF3157D5),
                fontSize: 12,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(22, 36, 22, 120),
              children: [
                const Text(
                  '무엇을 알아볼까요?',
                  style: TextStyle(
                    fontSize: 30,
                    height: 1.2,
                    fontWeight: FontWeight.w900,
                    letterSpacing: -1.2,
                  ),
                ),
                const SizedBox(height: 10),
                const Text(
                  '검색해서 없으면, ARABA가 직접 전화해서 알아봅니다.',
                  style: TextStyle(
                    fontSize: 15,
                    height: 1.5,
                    color: Color(0xFF667085),
                  ),
                ),
                const SizedBox(height: 28),
                Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: const Color(0xFFE4E7EC)),
                    boxShadow: const [
                      BoxShadow(
                        color: Color(0x0A101828),
                        blurRadius: 18,
                        offset: Offset(0, 6),
                      ),
                    ],
                  ),
                  child: Column(
                    children: [
                      TextField(
                        controller: _missionController,
                        minLines: 3,
                        maxLines: 6,
                        decoration: const InputDecoration(
                          hintText:
                              '예: 오늘 창원에서 BMW X6 타이어 교체 가능한 곳 중 가장 저렴한 곳 알아봐',
                          hintStyle: TextStyle(
                            color: Color(0xFF98A2B3),
                            height: 1.5,
                          ),
                          border: InputBorder.none,
                          contentPadding: EdgeInsets.all(14),
                        ),
                      ),
                      Row(
                        children: [
                          IconButton(
                            tooltip: '음성으로 말하기',
                            onPressed: () {},
                            icon: const Icon(Icons.mic_none_rounded),
                          ),
                          const Spacer(),
                          FilledButton.icon(
                            onPressed: () {
                              final text = _missionController.text.trim();

                              if (text.isEmpty) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  const SnackBar(
                                    content: Text('알아볼 내용을 입력해주세요.'),
                                  ),
                                );
                                return;
                              }

                              ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(content: Text('POC 준비 중 · "$text"')),
                              );
                            },
                            icon: const Icon(
                              Icons.arrow_upward_rounded,
                              size: 18,
                            ),
                            label: const Text('알아봐'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 36),
                const Text(
                  'ARABA가 하는 일',
                  style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
                ),
                const SizedBox(height: 14),
                const _FeatureCard(
                  icon: Icons.search_rounded,
                  title: '먼저 찾아봅니다',
                  description: '웹과 Fresh DB에서 필요한 정보를 확인합니다.',
                ),
                const SizedBox(height: 10),
                const _FeatureCard(
                  icon: Icons.call_outlined,
                  title: '없으면 직접 전화합니다',
                  description: 'AI가 업체에 전화해 가격, 재고, 가능시간과 조건을 확인합니다.',
                ),
                const SizedBox(height: 10),
                const _FeatureCard(
                  icon: Icons.notifications_none_rounded,
                  title: '결과가 나오면 알려드립니다',
                  description: '휴대폰과 PC에서 조사 결과를 확인할 수 있습니다.',
                ),
                const SizedBox(height: 32),
                const _PocStatus(),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _FeatureCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String description;

  const _FeatureCard({
    required this.icon,
    required this.title,
    required this.description,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFEAECF0)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              color: const Color(0xFFEEF4FF),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(icon, color: const Color(0xFF3157D5)),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 15,
                  ),
                ),
                const SizedBox(height: 5),
                Text(
                  description,
                  style: const TextStyle(
                    color: Color(0xFF667085),
                    height: 1.45,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _PocStatus extends StatelessWidget {
  const _PocStatus();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: const Color(0xFF101828),
        borderRadius: BorderRadius.circular(17),
      ),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'POC STATUS',
            style: TextStyle(
              color: Color(0xFF98A2B3),
              fontSize: 11,
              fontWeight: FontWeight.w800,
              letterSpacing: 1,
            ),
          ),
          SizedBox(height: 14),
          _StatusLine(name: 'Flutter App', value: 'RUNNING', active: true),
          _StatusLine(name: 'OpenAI', value: 'SETUP', active: false),
          _StatusLine(name: 'Voice', value: 'WAITING', active: false),
          _StatusLine(name: 'Telephone', value: 'WAITING', active: false),
        ],
      ),
    );
  }
}

class _StatusLine extends StatelessWidget {
  final String name;
  final String value;
  final bool active;

  const _StatusLine({
    required this.name,
    required this.value,
    required this.active,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Icon(
            Icons.circle,
            size: 9,
            color: active ? const Color(0xFF32D583) : const Color(0xFF667085),
          ),
          const SizedBox(width: 10),
          Text(name, style: const TextStyle(color: Colors.white)),
          const Spacer(),
          Text(
            value,
            style: TextStyle(
              color: active ? const Color(0xFF32D583) : const Color(0xFF98A2B3),
              fontSize: 12,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }
}
