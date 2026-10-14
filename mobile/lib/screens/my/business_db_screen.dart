import 'package:flutter/material.dart';

import '../../services/araba_api.dart';
import '../../services/admin_business_manage_api.dart';

class BusinessDbScreen extends StatefulWidget {
  const BusinessDbScreen({super.key});

  @override
  State<BusinessDbScreen> createState() => _BusinessDbScreenState();
}

class _BusinessDbScreenState extends State<BusinessDbScreen> {
  final ArabaApi _api = ArabaApi();
  final AdminBusinessManageApi _managementApi = AdminBusinessManageApi();
  final Set<int> _selectedBusinessIds = <int>{};
  bool _selectionMode = false;
  bool _changingVisibility = false;
  final TextEditingController _searchController = TextEditingController();

  bool _loading = true;
  bool _filterOpen = false;
  String? _error;

  Map<String, dynamic> _summary = const {};
  List<Map<String, dynamic>> _businesses = const [];

  String _category = '';
  String _provider = '';
  String _active = 'active';
  String _freshness = 'all';
  String _sort = 'latest';

  bool _hasPhone = false;
  bool _hasHours = false;
  bool _hasParking = false;
  bool _hasPrices = false;
  bool _hasImage = false;
  bool _hasExperience = false;

  int _filteredCount = 0;
  int _page = 1;
  bool _hasMore = false;

  final Set<int> _expandedBusinessIds = <int>{};

  @override
  void initState() {
    super.initState();
    _load(resetPage: true);
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  List<Map<String, dynamic>> get _categoryCounts {
    final raw = _summary['category_counts'];
    if (raw is! List) return const [];
    return raw
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  List<Map<String, dynamic>> get _providerCounts {
    final raw = _summary['provider_counts'];
    if (raw is! List) return const [];
    return raw
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  Map<String, dynamic> get _coverage {
    final raw = _summary['coverage'];
    if (raw is Map) {
      return Map<String, dynamic>.from(raw);
    }
    return const {};
  }

  Future<void> _load({required bool resetPage}) async {
    if (resetPage) {
      _page = 1;
    }

    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final result = await _api.adminBusinesses(
        query: _searchController.text,
        category: _category,
        provider: _provider,
        active: _active,
        freshness: _freshness,
        hasPhone: _hasPhone,
        hasHours: _hasHours,
        hasParking: _hasParking,
        hasPrices: _hasPrices,
        hasImage: _hasImage,
        hasExperience: _hasExperience,
        sort: _sort,
        page: _page,
        pageSize: 30,
      );

      final rawSummary = result['summary'];
      final rawBusinesses = result['businesses'];

      if (!mounted) return;

      setState(() {
        // A new result page or filter must not retain off-screen selection.
        _selectedBusinessIds.clear();
        _summary = rawSummary is Map
            ? Map<String, dynamic>.from(rawSummary)
            : const {};
        _businesses = rawBusinesses is List
            ? rawBusinesses
                .whereType<Map>()
                .map((item) => Map<String, dynamic>.from(item))
                .toList()
            : const [];
        _filteredCount = int.tryParse(
              result['filtered_count']?.toString() ?? '',
            ) ??
            0;
        _page = int.tryParse(
              result['page']?.toString() ?? '',
            ) ??
            1;
        _hasMore = result['has_more'] == true;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.toString();
      });
    } finally {
      if (mounted) {
        setState(() {
          _loading = false;
        });
      }
    }
  }

  Future<void> _toggleSelectionMode() async {
    if (_selectionMode) {
      setState(() {
        _selectionMode = false;
        _selectedBusinessIds.clear();
      });
      return;
    }
    try {
      var authorized = await _managementApi.isStaffAuthenticated();
      if (!authorized) {
        var username = '';
        var password = '';
        if (!mounted) return;
        final confirmed = await showDialog<bool>(
          context: context,
          builder: (dialogContext) => AlertDialog(
            title: const Text('관리자 계정 확인'),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text(
                  '선택한 업체만 숨기거나 복원하려면 관리자 로그인이 필요합니다. '
                  '화면의 관리자 테스트 모드는 실제 관리권한이 아닙니다.',
                  style: TextStyle(fontSize: 12),
                ),
                const SizedBox(height: 12),
                TextField(
                  autofocus: true,
                  onChanged: (value) => username = value,
                  decoration: const InputDecoration(
                    labelText: '관리자 아이디',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 10),
                TextField(
                  obscureText: true,
                  onChanged: (value) => password = value,
                  decoration: const InputDecoration(
                    labelText: '비밀번호',
                    border: OutlineInputBorder(),
                  ),
                ),
              ],
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('취소'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(dialogContext, true),
                child: const Text('인증'),
              ),
            ],
          ),
        );
        if (confirmed != true || !mounted) return;
        await _managementApi.adminLogin(username.trim(), password);
        authorized = true;
      }
      if (!mounted) return;
      if (authorized) {
        setState(() {
          _selectionMode = true;
          _selectedBusinessIds.clear();
        });
      }
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(
          error is ArabaApiException
              ? error.message
              : '관리자 인증에 실패했습니다. 네트워크와 계정을 확인해주세요.',
        )),
      );
    }
  }

  Future<void> _changeSelectedBusinessVisibility() async {
    if (_changingVisibility || _selectedBusinessIds.isEmpty ||
        _active == 'all') return;
    final restore = _active == 'inactive';
    final ids = _selectedBusinessIds.toList()..sort();
    final names = _businesses
        .where((item) => ids.contains(item['id']))
        .map((item) => item['name']?.toString() ?? '업체')
        .toList();
    final action = restore ? '복원' : '숨기기';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text('선택한 ${ids.length}곳 $action'),
        content: Text(
          '선택하지 않은 업체는 유지됩니다.\n\n'
          '${names.take(8).join(' · ')}'
          '${names.length > 8 ? ' 외 ${names.length - 8}곳' : ''}'
          '\n\n'
          '${restore ? '다시 검색과 가입 대상에 표시합니다.' : '영구 삭제하지 않고 비활성 목록에 보관합니다.'}',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(restore ? '선택한 업체 복원' : '선택한 업체만 숨기기'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _changingVisibility = true);
    try {
      final result = await _managementApi.updateSelected(
        businessIds: ids, active: restore,
      );
      if (!mounted) return;
      await _load(resetPage: true);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(result['message']?.toString() ?? '처리했습니다.')),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(
          error is ArabaApiException
              ? error.message
              : '변경에 실패했습니다. 서버 API 배포 및 권한을 확인해주세요.',
        )),
      );
    } finally {
      if (mounted) setState(() => _changingVisibility = false);
    }
  }

  void _resetFilters() {
    setState(() {
      _selectedBusinessIds.clear();
      _category = '';
      _provider = '';
      _active = 'active';
      _freshness = 'all';
      _sort = 'latest';
      _hasPhone = false;
      _hasHours = false;
      _hasParking = false;
      _hasPrices = false;
      _hasImage = false;
      _hasExperience = false;
      _searchController.clear();
    });
    _load(resetPage: true);
  }

  Widget _metric(String label, Object? value) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: 12,
          vertical: 14,
        ),
        decoration: BoxDecoration(
          color: const Color(0xFFF8FAFC),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(
            color: const Color(0xFFEAECF0),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '${value ?? 0}',
              style: const TextStyle(
                fontSize: 23,
                fontWeight: FontWeight.w900,
                letterSpacing: -0.8,
              ),
            ),
            const SizedBox(height: 3),
            Text(
              label,
              style: const TextStyle(
                color: Color(0xFF667085),
                fontSize: 11,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _coverageChip(String label, String key) {
    final value = _coverage[key] ?? 0;
    return Chip(
      visualDensity: VisualDensity.compact,
      label: Text(
        '$label $value',
        style: const TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }

  Widget _filterFlag({
    required String label,
    required bool selected,
    required ValueChanged<bool> onChanged,
  }) {
    return FilterChip(
      label: Text(label),
      selected: selected,
      onSelected: onChanged,
      visualDensity: VisualDensity.compact,
    );
  }

  String _formatDate(Object? value) {
    final text = value?.toString() ?? '';
    if (text.length >= 16) {
      return text
          .substring(0, 16)
          .replaceFirst('T', ' ');
    }
    return text.isEmpty ? '없음' : text;
  }

  Widget _statusChip(
    String label,
    bool active,
  ) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: 8,
        vertical: 4,
      ),
      decoration: BoxDecoration(
        color: active
            ? const Color(0xFFECFDF3)
            : const Color(0xFFF2F4F7),
        borderRadius: BorderRadius.circular(30),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: active
              ? const Color(0xFF027A48)
              : const Color(0xFF667085),
          fontSize: 10.5,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }

  Widget _businessCard(Map<String, dynamic> item) {
    final id = int.tryParse(
          item['id']?.toString() ?? '',
        ) ??
        item.hashCode;
    final name = item['name']?.toString() ?? '상호명 없음';
    final category = item['category_label']?.toString() ?? '미분류';
    final address = item['address']?.toString() ?? '';
    final phone = item['phone']?.toString() ?? '';
    final provider = item['provider']?.toString() ?? '';
    final experienceCount = item['experience_count'] ?? 0;
    final expanded = _expandedBusinessIds.contains(id);

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: expanded
              ? const Color(0xFFB2CCFF)
              : const Color(0xFFEAECF0),
        ),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () {
          setState(() {
            if (expanded) {
              _expandedBusinessIds.remove(id);
            } else {
              _expandedBusinessIds.add(id);
            }
          });
        },
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: 15,
            vertical: 13,
          ),
          child: AnimatedSize(
            duration: const Duration(milliseconds: 180),
            curve: Curves.easeOutCubic,
            alignment: Alignment.topCenter,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    if (_selectionMode) ...[
                      Checkbox(
                        value: _selectedBusinessIds.contains(id),
                        onChanged: (selected) {
                          setState(() {
                            if (selected == true) {
                              _selectedBusinessIds.add(id);
                            } else {
                              _selectedBusinessIds.remove(id);
                            }
                          });
                        },
                      ),
                      const SizedBox(width: 4),
                    ],
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            name,
                            maxLines: expanded ? 2 : 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              fontSize: 15.5,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                          const SizedBox(height: 3),
                          Text(
                            '$category · ${provider.isEmpty ? '출처 미상' : provider}',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              color: Color(0xFF667085),
                              fontSize: 11.5,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 8),
                    _statusChip(
                      item['detail_fresh'] == true ? '최신' : '갱신 필요',
                      item['detail_fresh'] == true,
                    ),
                    const SizedBox(width: 4),
                    AnimatedRotation(
                      turns: expanded ? 0.5 : 0,
                      duration: const Duration(milliseconds: 180),
                      child: const Icon(
                        Icons.keyboard_arrow_down_rounded,
                        size: 22,
                        color: Color(0xFF667085),
                      ),
                    ),
                  ],
                ),
                if (expanded) ...[
                  const SizedBox(height: 12),
                  const Divider(height: 1),
                  if (address.isNotEmpty) ...[
                    const SizedBox(height: 11),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(
                          Icons.location_on_outlined,
                          size: 16,
                          color: Color(0xFF667085),
                        ),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(
                            address,
                            style: const TextStyle(
                              color: Color(0xFF344054),
                              fontSize: 12,
                              height: 1.35,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                  if (phone.isNotEmpty) ...[
                    const SizedBox(height: 7),
                    Row(
                      children: [
                        const Icon(
                          Icons.phone_outlined,
                          size: 16,
                          color: Color(0xFF667085),
                        ),
                        const SizedBox(width: 6),
                        Text(
                          phone,
                          style: const TextStyle(
                            color: Color(0xFF475467),
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  ],
                  const SizedBox(height: 11),
                  Wrap(
                    spacing: 5,
                    runSpacing: 5,
                    children: [
                      _statusChip('전화', item['has_phone'] == true),
                      _statusChip('영업시간', item['has_hours'] == true),
                      _statusChip('주차', item['has_parking'] == true),
                      _statusChip('가격', item['has_prices'] == true),
                      _statusChip('사진', item['has_image'] == true),
                      _statusChip(
                        '경험 $experienceCount',
                        item['has_experience'] == true,
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  Text(
                    '최근 검색/확인: ${_formatDate(item['last_seen_at'])}',
                    style: const TextStyle(
                      color: Color(0xFF98A2B3),
                      fontSize: 10.5,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    '상세갱신: ${_formatDate(item['last_detail_refresh_at'])}',
                    style: const TextStyle(
                      color: Color(0xFF98A2B3),
                      fontSize: 10.5,
                    ),
                  ),
                ] else ...[
                  const SizedBox(height: 7),
                  Text(
                    '터치해서 상세보기',
                    style: const TextStyle(
                      color: Color(0xFF98A2B3),
                      fontSize: 10.5,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _dropDown({
    required String label,
    required String value,
    required List<DropdownMenuItem<String>> items,
    required ValueChanged<String?> onChanged,
  }) {
    return InputDecorator(
      decoration: InputDecoration(
        labelText: label,
        border: const OutlineInputBorder(),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 12,
          vertical: 4,
        ),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          value: value,
          isExpanded: true,
          items: items,
          onChanged: onChanged,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final total = _summary['total_count'] ?? 0;
    final active = _summary['active_count'] ?? 0;
    final fresh = _summary['fresh_detail_count'] ?? 0;
    final stale = _summary['stale_detail_count'] ?? 0;

    final providerItems = <DropdownMenuItem<String>>[
      const DropdownMenuItem(
        value: '',
        child: Text('전체 출처'),
      ),
      ..._providerCounts.map(
        (item) => DropdownMenuItem<String>(
          value: item['provider']?.toString() ?? '',
          child: Text(
            '${item['provider'] ?? '미상'} (${item['count'] ?? 0})',
          ),
        ),
      ),
    ];

    return Scaffold(
      appBar: AppBar(
        title: const Text(
          '검색 상점 DB',
          style: TextStyle(fontWeight: FontWeight.w900),
        ),
        actions: [
          IconButton(
            tooltip: '새로고침',
            onPressed: _loading
                ? null
                : () => _load(resetPage: true),
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(
              maxWidth: 820,
            ),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(
                18,
                16,
                18,
                100,
              ),
              children: [
                Row(
                  children: [
                    _metric('전체', total),
                    const SizedBox(width: 8),
                    _metric('활성', active),
                    const SizedBox(width: 8),
                    _metric('상세 최신', fresh),
                    const SizedBox(width: 8),
                    _metric('갱신 필요', stale),
                  ],
                ),
                const SizedBox(height: 12),
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(
                      color: const Color(0xFFEAECF0),
                    ),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        '데이터 보유 현황',
                        style: TextStyle(
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: [
                          _coverageChip('전화', 'phone'),
                          _coverageChip('영업시간', 'hours'),
                          _coverageChip('주차', 'parking'),
                          _coverageChip('가격', 'prices'),
                          _coverageChip('사진', 'image'),
                          _coverageChip('경험', 'experience'),
                        ],
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _searchController,
                  textInputAction: TextInputAction.search,
                  onSubmitted: (_) => _load(
                    resetPage: true,
                  ),
                  decoration: InputDecoration(
                    hintText: '상호명 · 주소 · 업종 · 전화 검색',
                    prefixIcon: const Icon(
                      Icons.search_rounded,
                    ),
                    suffixIcon: IconButton(
                      onPressed: () => _load(
                        resetPage: true,
                      ),
                      icon: const Icon(
                        Icons.arrow_forward_rounded,
                      ),
                    ),
                    border: const OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: () {
                          setState(() {
                            _filterOpen = !_filterOpen;
                          });
                        },
                        icon: const Icon(
                          Icons.tune_rounded,
                        ),
                        label: Text(
                          _filterOpen
                              ? '필터 접기'
                              : '상세 필터',
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    TextButton(
                      onPressed: _resetFilters,
                      child: const Text('초기화'),
                    ),
                  ],
                ),
                if (_filterOpen) ...[
                  const SizedBox(height: 10),
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF8FAFC),
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(
                        color: const Color(0xFFEAECF0),
                      ),
                    ),
                    child: Column(
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: _dropDown(
                                label: '상태',
                                value: _active,
                                items: const [
                                  DropdownMenuItem(
                                    value: 'active',
                                    child: Text('활성'),
                                  ),
                                  DropdownMenuItem(
                                    value: 'inactive',
                                    child: Text('비활성'),
                                  ),
                                  DropdownMenuItem(
                                    value: 'all',
                                    child: Text('전체'),
                                  ),
                                ],
                                onChanged: (value) {
                                  if (value == null) return;
                                  setState(() {
                                    _active = value;
                                  });
                                },
                              ),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: _dropDown(
                                label: '상세 정보',
                                value: _freshness,
                                items: const [
                                  DropdownMenuItem(
                                    value: 'all',
                                    child: Text('전체'),
                                  ),
                                  DropdownMenuItem(
                                    value: 'fresh',
                                    child: Text('최신'),
                                  ),
                                  DropdownMenuItem(
                                    value: 'stale',
                                    child: Text('갱신 필요'),
                                  ),
                                ],
                                onChanged: (value) {
                                  if (value == null) return;
                                  setState(() {
                                    _freshness = value;
                                  });
                                },
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 10),
                        _dropDown(
                          label: '수집 출처',
                          value: _provider,
                          items: providerItems,
                          onChanged: (value) {
                            setState(() {
                              _provider = value ?? '';
                            });
                          },
                        ),
                        const SizedBox(height: 10),
                        _dropDown(
                          label: '정렬',
                          value: _sort,
                          items: const [
                            DropdownMenuItem(
                              value: 'latest',
                              child: Text('최근 확인순'),
                            ),
                            DropdownMenuItem(
                              value: 'oldest',
                              child: Text('오래된 순'),
                            ),
                            DropdownMenuItem(
                              value: 'name',
                              child: Text('상호명 순'),
                            ),
                          ],
                          onChanged: (value) {
                            if (value == null) return;
                            setState(() {
                              _sort = value;
                            });
                          },
                        ),
                        const SizedBox(height: 10),
                        Align(
                          alignment: Alignment.centerLeft,
                          child: Wrap(
                            spacing: 6,
                            runSpacing: 6,
                            children: [
                              _filterFlag(
                                label: '전화 있음',
                                selected: _hasPhone,
                                onChanged: (value) {
                                  setState(() {
                                    _hasPhone = value;
                                  });
                                },
                              ),
                              _filterFlag(
                                label: '영업시간 있음',
                                selected: _hasHours,
                                onChanged: (value) {
                                  setState(() {
                                    _hasHours = value;
                                  });
                                },
                              ),
                              _filterFlag(
                                label: '주차정보 있음',
                                selected: _hasParking,
                                onChanged: (value) {
                                  setState(() {
                                    _hasParking = value;
                                  });
                                },
                              ),
                              _filterFlag(
                                label: '가격 있음',
                                selected: _hasPrices,
                                onChanged: (value) {
                                  setState(() {
                                    _hasPrices = value;
                                  });
                                },
                              ),
                              _filterFlag(
                                label: '사진 있음',
                                selected: _hasImage,
                                onChanged: (value) {
                                  setState(() {
                                    _hasImage = value;
                                  });
                                },
                              ),
                              _filterFlag(
                                label: '이용경험 있음',
                                selected: _hasExperience,
                                onChanged: (value) {
                                  setState(() {
                                    _hasExperience = value;
                                  });
                                },
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: 10),
                        SizedBox(
                          width: double.infinity,
                          child: FilledButton.icon(
                            onPressed: () => _load(
                              resetPage: true,
                            ),
                            icon: const Icon(
                              Icons.filter_alt_rounded,
                            ),
                            label: const Text('필터 적용'),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
                const SizedBox(height: 16),
                const Text(
                  '업종별 저장 현황',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    ChoiceChip(
                      label: Text(
                        '전체 $active',
                      ),
                      selected: _category.isEmpty,
                      onSelected: (_) {
                        setState(() {
                          _category = '';
                        });
                        _load(resetPage: true);
                      },
                    ),
                    ..._categoryCounts.take(30).map(
                      (item) {
                        final name =
                            item['category']?.toString() ??
                                '미분류';
                        final count =
                            item['count']?.toString() ?? '0';
                        return ChoiceChip(
                          label: Text('$name $count'),
                          selected: _category == name,
                          onSelected: (_) {
                            setState(() {
                              _category = name;
                            });
                            _load(resetPage: true);
                          },
                        );
                      },
                    ),
                  ],
                ),
                const SizedBox(height: 18),
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        '저장 사업장 $_filteredCount개',
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ),
                    if (_loading || _changingVisibility)
                      const Padding(
                        padding: EdgeInsets.only(right: 6),
                        child: SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                      ),
                    OutlinedButton.icon(
                      onPressed: _changingVisibility ? null : _toggleSelectionMode,
                      icon: Icon(_selectionMode
                          ? Icons.close_rounded
                          : Icons.checklist_rtl_rounded, size: 18),
                      label: Text(_selectionMode ? '선택 종료' : '선택 관리'),
                    ),
                  ],
                ),
                if (_selectionMode) ...[
                  const SizedBox(height: 8),
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF2F5FF),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text(
                          '선택 ${_selectedBusinessIds.length}곳 · '
                          '체크한 업체만 변경 (나머지는 유지)',
                          style: const TextStyle(
                            fontSize: 12, fontWeight: FontWeight.w800),
                        ),
                        const SizedBox(height: 5),
                        Wrap(
                          spacing: 8,
                          children: [
                            TextButton(
                              onPressed: () => setState(() {
                                _selectedBusinessIds.addAll(
                                  _businesses
                                      .map((b) => b['id'])
                                      .whereType<int>(),
                                );
                              }),
                              child: const Text('현재 페이지 전체 선택'),
                            ),
                            TextButton(
                              onPressed: () => setState(
                                () => _selectedBusinessIds.clear(),
                              ),
                              child: const Text('선택 해제'),
                            ),
                          ],
                        ),
                        FilledButton.icon(
                          onPressed: _selectedBusinessIds.isEmpty ||
                                  _active == 'all' || _changingVisibility
                              ? null : _changeSelectedBusinessVisibility,
                          icon: Icon(_active == 'inactive'
                              ? Icons.restore
                              : Icons.visibility_off_outlined),
                          label: Text(_active == 'inactive'
                              ? '선택한 업체만 복원'
                              : '선택한 업체만 숨기기'),
                        ),
                        const SizedBox(height: 5),
                        Text(
                          _active == 'all'
                              ? '전체 보기에서는 변경할 수 없습니다. 활성 또는 비활성으로 필터를 변경해주세요.'
                              : '삭제가 아니라 비활성 보관입니다. 상태 필터에서 언제든 복원할 수 있습니다.',
                          style: const TextStyle(fontSize: 11, color: Color(0xFF667085)),
                        ),
                      ],
                    ),
                  ),
                ],
                const SizedBox(height: 10),
                if (_error != null)
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFEF3F2),
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: Text(
                      _error!,
                      style: const TextStyle(
                        color: Color(0xFFB42318),
                      ),
                    ),
                  )
                else if (!_loading && _businesses.isEmpty)
                  const Padding(
                    padding: EdgeInsets.symmetric(
                      vertical: 30,
                    ),
                    child: Center(
                      child: Text(
                        '조건에 맞는 저장 상점이 없습니다.',
                        style: TextStyle(
                          color: Color(0xFF667085),
                        ),
                      ),
                    ),
                  )
                else
                  ..._businesses.map(_businessCard),
                if (_businesses.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      Expanded(
                        child: OutlinedButton(
                          onPressed: _page > 1 && !_loading
                              ? () {
                                  _page -= 1;
                                  _load(resetPage: false);
                                }
                              : null,
                          child: const Text('이전'),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        '$_page 페이지',
                        style: const TextStyle(
                          color: Color(0xFF667085),
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: OutlinedButton(
                          onPressed: _hasMore && !_loading
                              ? () {
                                  _page += 1;
                                  _load(resetPage: false);
                                }
                              : null,
                          child: const Text('다음'),
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
