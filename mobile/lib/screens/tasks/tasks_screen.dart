import 'package:flutter/material.dart';

import '../../services/araba_api.dart';

class TasksScreen extends StatefulWidget {
  final bool active;

  const TasksScreen({
    super.key,
    this.active = false,
  });

  @override
  State<TasksScreen> createState() => _TasksScreenState();
}

class _TasksScreenState extends State<TasksScreen> {
  final _api = ArabaApi();
  final _searchController = TextEditingController();

  bool _loading = true;
  String? _error;
  List<Map<String, dynamic>> _categories = const [];
  Map<String, dynamic> _filters = const {};
  String? _selectedCategory;
  final Map<String, String> _selectedSubfilters = {};

  @override
  void initState() {
    super.initState();
    if (widget.active) {
      _load();
    } else {
      _loading = false;
    }
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant TasksScreen oldWidget) {
    super.didUpdateWidget(oldWidget);

    if (widget.active && !oldWidget.active) {
      _load();
    }
  }

  Future<void> _load() async {
    if (!mounted) return;

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final result = await _api.researchHistory();
      final rawCategories = result['categories'];
      final categories = rawCategories is List
          ? rawCategories
                .whereType<Map>()
                .map(
                  (item) => Map<String, dynamic>.from(item),
                )
                .toList()
          : <Map<String, dynamic>>[];

      final rawFilters = result['filters'];
      final filters = rawFilters is Map
          ? Map<String, dynamic>.from(rawFilters)
          : <String, dynamic>{};

      if (!mounted) return;

      setState(() {
        _categories = categories;
        _filters = filters;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;

      setState(() {
        _loading = false;
        _error = error is ArabaApiException
            ? error.message
            : '조사 기록을 불러오지 못했어요.';
      });
    }
  }

  List<Map<String, dynamic>> _categoryOptions() {
    final raw = _filters['categories'];

    if (raw is! List) {
      return const [];
    }

    return raw
        .whereType<Map>()
        .map(
          (item) => Map<String, dynamic>.from(item),
        )
        .toList();
  }

  List<Map<String, dynamic>> _activeFilterSections() {
    final category = _selectedCategory;

    if (category == null || category.isEmpty) {
      return const [];
    }

    final rawByCategory = _filters['by_category'];

    if (rawByCategory is! Map) {
      return const [];
    }

    final rawCategory = rawByCategory[category];

    if (rawCategory is! Map) {
      return const [];
    }

    final rawSections = rawCategory['sections'];

    if (rawSections is! List) {
      return const [];
    }

    return rawSections
        .whereType<Map>()
        .map(
          (item) => Map<String, dynamic>.from(item),
        )
        .toList();
  }

  bool _matchesSearch(
    Map<String, dynamic> record,
  ) {
    final query =
        _searchController.text.trim().toLowerCase();

    if (query.isEmpty) {
      return true;
    }

    final buffer = StringBuffer()
      ..write(' ')
      ..write(record['subject'] ?? '')
      ..write(' ')
      ..write(record['location'] ?? '')
      ..write(' ')
      ..write(record['category'] ?? '')
      ..write(' ')
      ..write(record['intent'] ?? '')
      ..write(' ')
      ..write(record['comparison'] ?? '');

    final recommendation = record['recommendation'];
    if (recommendation is Map) {
      buffer
        ..write(' ')
        ..write(recommendation['name'] ?? '');
    }

    final subcategories = record['subcategories'];
    if (subcategories is List) {
      buffer
        ..write(' ')
        ..write(subcategories.join(' '));
    }

    final attributes = record['attributes'];
    if (attributes is Map) {
      for (final entry in attributes.entries) {
        buffer
          ..write(' ')
          ..write(entry.key)
          ..write(' ')
          ..write(entry.value);
      }
    }

    return buffer
        .toString()
        .toLowerCase()
        .contains(query);
  }

  bool _matchesDynamicFilters(
    Map<String, dynamic> record,
  ) {
    if (_selectedSubfilters.isEmpty) {
      return true;
    }

    for (final entry in _selectedSubfilters.entries) {
      final key = entry.key;
      final expected = entry.value;

      if (key == 'subcategory') {
        final values = record['subcategories'];
        if (values is! List ||
            !values.map((item) => item.toString()).contains(expected)) {
          return false;
        }
        continue;
      }

      if (key == 'location') {
        if (record['location']?.toString() != expected) {
          return false;
        }
        continue;
      }

      if (key == 'intent') {
        if (record['intent']?.toString() != expected) {
          return false;
        }
        continue;
      }

      if (key == 'comparison') {
        if (record['comparison']?.toString() != expected) {
          return false;
        }
        continue;
      }

      if (key.startsWith('attribute:')) {
        final attributeName =
            key.substring('attribute:'.length);
        final attributes = record['attributes'];

        if (attributes is! Map) {
          return false;
        }

        final raw = attributes[attributeName];

        if (raw is List) {
          if (!raw
              .map((item) => item.toString())
              .contains(expected)) {
            return false;
          }
        } else if (raw?.toString() != expected) {
          return false;
        }
      }
    }

    return true;
  }

  List<Map<String, dynamic>> _visibleCategories() {
    final result = <Map<String, dynamic>>[];

    for (final category in _categories) {
      final name =
          category['category']?.toString().trim() ?? '';

      if (_selectedCategory != null &&
          _selectedCategory!.isNotEmpty &&
          name != _selectedCategory) {
        continue;
      }

      final rawRecords = category['records'];
      final records = rawRecords is List
          ? rawRecords
                .whereType<Map>()
                .map(
                  (item) => Map<String, dynamic>.from(item),
                )
                .where(_matchesSearch)
                .where(_matchesDynamicFilters)
                .toList()
          : <Map<String, dynamic>>[];

      if (records.isEmpty) {
        continue;
      }

      result.add({
        ...category,
        'records': records,
        'count': records.length,
      });
    }

    return result;
  }

  void _selectCategory(String? category) {
    setState(() {
      _selectedCategory = category;
      _selectedSubfilters.clear();
    });
  }

  void _toggleSubfilter(
    String key,
    String value,
  ) {
    setState(() {
      if (_selectedSubfilters[key] == value) {
        _selectedSubfilters.remove(key);
      } else {
        _selectedSubfilters[key] = value;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF7F8FC),
      appBar: AppBar(
        backgroundColor: Colors.white,
        surfaceTintColor: Colors.white,
        title: const Text(
          '조사 기록',
          style: TextStyle(
            fontWeight: FontWeight.w900,
          ),
        ),
        actions: [
          IconButton(
            tooltip: '새로고침',
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      body: _body(),
    );
  }

  Widget _body() {
    if (_loading && _categories.isEmpty) {
      return const Center(
        child: CircularProgressIndicator(),
      );
    }

    if (_error != null && _categories.isEmpty) {
      return _StateMessage(
        icon: Icons.cloud_off_rounded,
        title: '조사 기록을 불러오지 못했어요',
        description: _error!,
        actionText: '다시 시도',
        onAction: _load,
      );
    }

    if (_categories.isEmpty) {
      return _StateMessage(
        icon: Icons.inventory_2_outlined,
        title: '아직 저장된 조사가 없어요',
        description:
            'ARABA가 조사와 통화 비교를 마치면 결과가 여기에 자동으로 쌓입니다.',
        actionText: '새로고침',
        onAction: _load,
      );
    }

    final visibleCategories = _visibleCategories();
    final categoryOptions = _categoryOptions();
    final filterSections = _activeFilterSections();

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(
          16,
          18,
          16,
          28,
        ),
        children: [
          const _DatabaseNotice(),
          const SizedBox(height: 14),
          TextField(
            controller: _searchController,
            onChanged: (_) => setState(() {}),
            decoration: InputDecoration(
              hintText: '조사내용·지역·업체·조건 검색',
              prefixIcon: const Icon(
                Icons.search_rounded,
              ),
              suffixIcon: _searchController.text.isEmpty
                  ? null
                  : IconButton(
                      tooltip: '검색 지우기',
                      onPressed: () {
                        _searchController.clear();
                        setState(() {});
                      },
                      icon: const Icon(
                        Icons.close_rounded,
                      ),
                    ),
              filled: true,
              fillColor: Colors.white,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(16),
                borderSide: const BorderSide(
                  color: Color(0xFFE4E7EC),
                ),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(16),
                borderSide: const BorderSide(
                  color: Color(0xFFE4E7EC),
                ),
              ),
            ),
          ),
          const SizedBox(height: 14),
          const Text(
            '카테고리',
            style: TextStyle(
              color: Color(0xFF344054),
              fontSize: 13,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              ChoiceChip(
                label: const Text('전체'),
                selected: _selectedCategory == null,
                onSelected: (_) => _selectCategory(null),
              ),
              for (final option in categoryOptions)
                ChoiceChip(
                  label: Text(
                    '${option['value']} ${option['count']}',
                  ),
                  selected:
                      _selectedCategory == option['value']?.toString(),
                  onSelected: (_) => _selectCategory(
                    option['value']?.toString(),
                  ),
                ),
            ],
          ),
          if (filterSections.isNotEmpty) ...[
            const SizedBox(height: 16),
            for (final section in filterSections) ...[
              Text(
                section['label']?.toString() ?? '필터',
                style: const TextStyle(
                  color: Color(0xFF344054),
                  fontSize: 13,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 7),
              Wrap(
                spacing: 7,
                runSpacing: 7,
                children: [
                  for (final option
                      in (section['options'] is List
                          ? section['options'] as List
                          : const []))
                    if (option is Map)
                      FilterChip(
                        label: Text(
                          '${option['value']} ${option['count']}',
                        ),
                        selected: _selectedSubfilters[
                                section['key']?.toString() ?? ''] ==
                            option['value']?.toString(),
                        onSelected: (_) => _toggleSubfilter(
                          section['key']?.toString() ?? '',
                          option['value']?.toString() ?? '',
                        ),
                      ),
                ],
              ),
              const SizedBox(height: 12),
            ],
          ],
          const SizedBox(height: 6),
          if (visibleCategories.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(
                vertical: 48,
              ),
              child: Center(
                child: Text(
                  '조건에 맞는 조사 기록이 없어요.',
                  style: TextStyle(
                    color: Color(0xFF667085),
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            )
          else
            for (final category in visibleCategories) ...[
              _CategorySection(
                category: category,
              ),
              const SizedBox(height: 18),
            ],
        ],
      ),
    );
  }

}

class _DatabaseNotice extends StatelessWidget {
  const _DatabaseNotice();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFEEF4FF),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: const Color(0xFFD6E4FF),
        ),
      ),
      child: const Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            Icons.storage_rounded,
            color: Color(0xFF3157D5),
          ),
          SizedBox(width: 10),
          Expanded(
            child: Text(
              '가상 통화에서 확인한 질문·비교 결과를 조사 단위로 저장합니다. '
              '현재 POC에서는 사용자가 실제로 요청한 업종만 표시합니다.',
              style: TextStyle(
                color: Color(0xFF344054),
                height: 1.4,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CategorySection extends StatelessWidget {
  final Map<String, dynamic> category;

  const _CategorySection({
    required this.category,
  });

  @override
  Widget build(BuildContext context) {
    final name =
        category['category']?.toString().trim() ?? '기타';
    final rawRecords = category['records'];
    final records = rawRecords is List
        ? rawRecords
              .whereType<Map>()
              .map(
                (item) => Map<String, dynamic>.from(item),
              )
              .toList()
        : <Map<String, dynamic>>[];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(
              name,
              style: const TextStyle(
                color: Color(0xFF101828),
                fontSize: 18,
                fontWeight: FontWeight.w900,
              ),
            ),
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(
                horizontal: 8,
                vertical: 3,
              ),
              decoration: BoxDecoration(
                color: const Color(0xFFF2F4F7),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Text(
                '${records.length}건',
                style: const TextStyle(
                  color: Color(0xFF667085),
                  fontSize: 11,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        for (final record in records) ...[
          _ResearchRecordCard(record: record),
          const SizedBox(height: 10),
        ],
      ],
    );
  }
}

class _ResearchRecordCard extends StatelessWidget {
  final Map<String, dynamic> record;

  const _ResearchRecordCard({
    required this.record,
  });

  String _won(dynamic value) {
    if (value is! num) return '-';

    final digits = value.round().toString();
    final buffer = StringBuffer();

    for (var i = 0; i < digits.length; i++) {
      if (i > 0 && (digits.length - i) % 3 == 0) {
        buffer.write(',');
      }
      buffer.write(digits[i]);
    }

    return '${buffer.toString()}원';
  }

  void _showDetails(
    BuildContext context,
    List<Map<String, dynamic>> businesses,
  ) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (context) {
        return FractionallySizedBox(
          heightFactor: 0.88,
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  18,
                  16,
                  8,
                  10,
                ),
                child: Row(
                  children: [
                    const Expanded(
                      child: Text(
                        '가상 통화 수집정보',
                        style: TextStyle(
                          color: Color(0xFF101828),
                          fontSize: 18,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ),
                    IconButton(
                      tooltip: '닫기',
                      onPressed: () => Navigator.of(context).pop(),
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
              ),
              const Divider(height: 1),
              Expanded(
                child: ListView.separated(
                  padding: const EdgeInsets.all(16),
                  itemCount: businesses.length,
                  separatorBuilder: (context, index) =>
                      const SizedBox(height: 12),
                  itemBuilder: (context, index) {
                    return _StoredBusinessDetail(
                      business: businesses[index],
                    );
                  },
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final subject =
        record['subject']?.toString().trim() ?? '조사';
    final location =
        record['location']?.toString().trim() ?? '';
    final recommendationValue = record['recommendation'];
    final recommendation = recommendationValue is Map
        ? Map<String, dynamic>.from(recommendationValue)
        : <String, dynamic>{};

    final name =
        recommendation['name']?.toString().trim() ?? '추천 후보';
    final price = recommendation['mock_total_price'];
    final distance = recommendation['distance_km'];
    final driveMinutes = recommendation['drive_minutes'];
    final totalTimeMinutes =
        recommendation['total_time_minutes'];
    final effective = recommendation['effective_cost'];
    final isMock = record['is_mock'] == true;
    final rawBusinesses = record['businesses'];
    final businesses = rawBusinesses is List
        ? rawBusinesses
              .whereType<Map>()
              .map(
                (item) => Map<String, dynamic>.from(item),
              )
              .toList()
        : <Map<String, dynamic>>[];

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(15),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(
          color: const Color(0xFFE4E7EC),
        ),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0A101828),
            blurRadius: 10,
            offset: Offset(0, 3),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(
                  subject,
                  style: const TextStyle(
                    color: Color(0xFF101828),
                    fontSize: 15,
                    fontWeight: FontWeight.w900,
                    height: 1.35,
                  ),
                ),
              ),
              if (isMock)
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFFF4E5),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: const Text(
                    '가상통화',
                    style: TextStyle(
                      color: Color(0xFFB54708),
                      fontSize: 10.5,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                ),
            ],
          ),
          if (location.isNotEmpty) ...[
            const SizedBox(height: 5),
            Text(
              location,
              style: const TextStyle(
                color: Color(0xFF667085),
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
          const SizedBox(height: 13),
          Text(
            name,
            style: const TextStyle(
              color: Color(0xFF3157D5),
              fontSize: 15,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _MetricChip(
                label: '총액',
                value: _won(price),
              ),
              _MetricChip(
                label: '거리',
                value: distance is num
                    ? '${distance.toStringAsFixed(1)}km'
                    : '-',
              ),
              _MetricChip(
                label: '편도 이동',
                value: driveMinutes is num
                    ? '약 ${driveMinutes.round()}분'
                    : '-',
              ),
              _MetricChip(
                label: '총 소요',
                value: totalTimeMinutes is num
                    ? '약 ${totalTimeMinutes.round()}분'
                    : '-',
              ),
              _MetricChip(
                label: '경제성 비용',
                value: _won(effective),
                strong: true,
              ),
            ],
          ),
          if (businesses.isNotEmpty) ...[
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: () => _showDetails(
                  context,
                  businesses,
                ),
                icon: const Icon(
                  Icons.fact_check_outlined,
                  size: 18,
                ),
                label: Text(
                  '업체 ${businesses.length}곳 통화정보 보기',
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _StoredBusinessDetail extends StatelessWidget {
  final Map<String, dynamic> business;

  const _StoredBusinessDetail({
    required this.business,
  });

  String _won(dynamic value) {
    if (value is! num) return '-';

    final digits = value.round().toString();
    final buffer = StringBuffer();

    for (var i = 0; i < digits.length; i++) {
      if (i > 0 && (digits.length - i) % 3 == 0) {
        buffer.write(',');
      }
      buffer.write(digits[i]);
    }

    return '${buffer.toString()}원';
  }

  @override
  Widget build(BuildContext context) {
    final name =
        business['name']?.toString().trim() ?? '업체';
    final rank = business['economic_rank'];
    final totalPrice = business['mock_total_price'];
    final effective = business['effective_cost'];
    final distance = business['distance_km'];
    final drive = business['drive_minutes'];
    final wait = business['mock_wait_minutes'];
    final work = business['mock_work_minutes'];
    final stock = business['mock_stock'];
    final rawQuestions = business['mock_questions'];
    final questions = rawQuestions is List
        ? rawQuestions
              .whereType<Map>()
              .map(
                (item) => Map<String, dynamic>.from(item),
              )
              .toList()
        : <Map<String, dynamic>>[];

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: rank == 1
              ? const Color(0xFF9DB7FF)
              : const Color(0xFFE4E7EC),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  name,
                  style: const TextStyle(
                    color: Color(0xFF101828),
                    fontSize: 15,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
              if (rank is num)
                Text(
                  '경제성 ${rank.round()}위',
                  style: const TextStyle(
                    color: Color(0xFF3157D5),
                    fontSize: 11.5,
                    fontWeight: FontWeight.w900,
                  ),
                ),
            ],
          ),
          const SizedBox(height: 9),
          Wrap(
            spacing: 7,
            runSpacing: 7,
            children: [
              _MetricChip(
                label: '최종금액',
                value: _won(totalPrice),
              ),
              if (stock is bool)
                _MetricChip(
                  label: '재고',
                  value: stock ? '있음' : '없음',
                ),
              if (distance is num)
                _MetricChip(
                  label: '거리',
                  value: '${distance.toStringAsFixed(1)}km',
                ),
              if (drive is num)
                _MetricChip(
                  label: '이동',
                  value: '${drive.round()}분',
                ),
              if (wait is num)
                _MetricChip(
                  label: '대기',
                  value: '${wait.round()}분',
                ),
              if (work is num)
                _MetricChip(
                  label: '작업',
                  value: '${work.round()}분',
                ),
              _MetricChip(
                label: '경제성 비용',
                value: _won(effective),
                strong: rank == 1,
              ),
            ],
          ),
          if (questions.isNotEmpty) ...[
            const SizedBox(height: 13),
            for (final qa in questions) ...[
              Text(
                'Q. ${qa['question']?.toString() ?? ''}',
                style: const TextStyle(
                  color: Color(0xFF344054),
                  fontSize: 12,
                  fontWeight: FontWeight.w800,
                  height: 1.4,
                ),
              ),
              const SizedBox(height: 3),
              Text(
                'A. ${qa['answer']?.toString() ?? ''}',
                style: const TextStyle(
                  color: Color(0xFF667085),
                  fontSize: 12,
                  height: 1.4,
                ),
              ),
              const SizedBox(height: 9),
            ],
          ],
        ],
      ),
    );
  }
}

class _MetricChip extends StatelessWidget {
  final String label;
  final String value;
  final bool strong;

  const _MetricChip({
    required this.label,
    required this.value,
    this.strong = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: 10,
        vertical: 7,
      ),
      decoration: BoxDecoration(
        color: strong
            ? const Color(0xFFEEF4FF)
            : const Color(0xFFF9FAFB),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: strong
              ? const Color(0xFFC7D7FE)
              : const Color(0xFFEAECF0),
        ),
      ),
      child: Text.rich(
        TextSpan(
          children: [
            TextSpan(
              text: '$label ',
              style: const TextStyle(
                color: Color(0xFF667085),
                fontSize: 11,
                fontWeight: FontWeight.w700,
              ),
            ),
            TextSpan(
              text: value,
              style: TextStyle(
                color: strong
                    ? const Color(0xFF1939A6)
                    : const Color(0xFF344054),
                fontSize: 11.5,
                fontWeight: FontWeight.w900,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StateMessage extends StatelessWidget {
  final IconData icon;
  final String title;
  final String description;
  final String actionText;
  final VoidCallback onAction;

  const _StateMessage({
    required this.icon,
    required this.title,
    required this.description,
    required this.actionText,
    required this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              icon,
              size: 46,
              color: const Color(0xFF667085),
            ),
            const SizedBox(height: 14),
            Text(
              title,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: Color(0xFF101828),
                fontSize: 17,
                fontWeight: FontWeight.w900,
              ),
            ),
            const SizedBox(height: 7),
            Text(
              description,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: Color(0xFF667085),
                height: 1.45,
              ),
            ),
            const SizedBox(height: 15),
            OutlinedButton.icon(
              onPressed: onAction,
              icon: const Icon(Icons.refresh_rounded),
              label: Text(actionText),
            ),
          ],
        ),
      ),
    );
  }
}
