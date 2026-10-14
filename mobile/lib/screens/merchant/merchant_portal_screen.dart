import 'package:flutter/material.dart';
import '../../services/araba_api.dart';
import '../../services/merchant_account_api.dart';

/// Merchant view in the debug-only role preview. Server permissions still apply.
class MerchantPortalScreen extends StatefulWidget {
  const MerchantPortalScreen({super.key});
  @override
  State<MerchantPortalScreen> createState() => _MerchantPortalScreenState();
}

class _MerchantPortalScreenState extends State<MerchantPortalScreen> {
  final _api = MerchantAccountApi();
  final Map<String, TextEditingController> inputs = {
    for (final name in [
      'username', 'password', 'confirm', 'search', 'owner', 'number',
      'contact', 'name', 'category', 'address', 'phone', 'opening_hours',
      'parking', 'prices', 'extra', 'instructions',
    ]) name: TextEditingController(),
  };
  TextEditingController field(String name) => inputs[name]!;
  static const labels = <String, String>{
    'name': '상호명', 'category': '업종', 'address': '주소', 'phone': '전화번호',
    'opening_hours': '영업시간', 'parking': '주차정보', 'prices': '상품·가격',
  };
  bool busy = false, signedIn = false, isSignup = false;
  bool usernameChecked = false, terms = false, privacy = false;
  String message = '', username = '';
  List<Map<String, dynamic>> businesses = [], claims = [];
  Map<String, dynamic>? picked, editing;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  @override
  void dispose() {
    for (final controller in inputs.values) {
      controller.dispose();
    }
    super.dispose();
  }

  List<Map<String, dynamic>> _items(dynamic raw) => raw is List
      ? raw.whereType<Map>().map((row) => Map<String, dynamic>.from(row)).toList()
      : <Map<String, dynamic>>[];

  Future<void> _run(Future<void> Function() action) async {
    if (busy) return;
    setState(() { busy = true; message = ''; });
    try {
      await action();
    } catch (error) {
      if (mounted) {
        setState(() => message = error is ArabaApiException
            ? error.message : '연결 오류입니다. 서버 배포 및 네트워크를 확인해주세요.');
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _refresh() => _run(() async {
    final token = await _api.token();
    if (token == null || token.isEmpty) return;
    final result = await _api.me();
    if (!mounted) return;
    setState(() {
      signedIn = true;
      username = (result['user'] as Map?)?['username']?.toString() ?? '';
      claims = _items(result['claims']);
    });
  });

  Future<void> _checkId() => _run(() async {
    final result = await _api.usernameAvailable(field('username').text);
    if (!mounted) return;
    setState(() {
      usernameChecked = result['available'] == true;
      message = usernameChecked ? '사용 가능한 아이디입니다.' : '이미 사용 중인 아이디입니다.';
    });
  });

  Future<void> _login() => _run(() async {
    if (isSignup) {
      if (!usernameChecked) throw const ArabaApiException('아이디 중복 확인이 필요합니다.');
      if (!terms || !privacy) throw const ArabaApiException('필수 약관에 동의해주세요.');
      if (field('password').text != field('confirm').text) {
        throw const ArabaApiException('비밀번호가 일치하지 않습니다.');
      }
      await _api.signup(
        username: field('username').text,
        password: field('password').text,
        confirm: field('confirm').text,
      );
    } else {
      await _api.login(username: field('username').text, password: field('password').text);
    }
    field('password').clear();
    field('confirm').clear();
    final result = await _api.me();
    if (!mounted) return;
    setState(() {
      signedIn = true;
      username = (result['user'] as Map?)?['username']?.toString() ?? '';
      claims = _items(result['claims']);
      message = '로그인 완료. 기존 업체를 검색해 주세요.';
    });
  });

  Future<void> _search() => _run(() async {
    final result = await _api.searchExistingBusinesses(field('search').text);
    if (!mounted) return;
    setState(() {
      businesses = _items(result['businesses']);
      picked = null;
      message = businesses.isEmpty ? '검색 결과가 없습니다. 신규 업체 등록은 추후 지원합니다.'
          : '상호명과 주소를 확인한 뒤 본인 업체를 선택해주세요.';
    });
  });

  void _edit(Map<String, dynamic> claim) {
    final raw = claim['proposed_info'];
    final proposed = raw is Map ? Map<String, dynamic>.from(raw) : <String, dynamic>{};
    Map<String, dynamic> selected = {};
    for (final business in businesses) {
      if (business['id'] == claim['business_id']) {
        selected = business;
        break;
      }
    }
    for (final name in labels.keys) {
      final fallback = switch (name) {
        'name' => claim['business_name'] ?? selected['name'],
        'category' => claim['business_category'] ?? selected['category'],
        'address' => claim['business_address'] ?? selected['address'],
        'phone' => claim['business_phone'] ?? selected['phone'],
        _ => '',
      };
      field(name).text = proposed[name]?.toString() ?? fallback?.toString() ?? '';
    }
    field('extra').text = claim['extra_information']?.toString() ?? '';
    field('instructions').text = claim['agent_instructions']?.toString() ?? '';
    setState(() { editing = claim; picked = null; });
  }

  Future<void> _claim() => _run(() async {
    final id = int.tryParse(picked?['id']?.toString() ?? '');
    if (id == null) throw const ArabaApiException('업체를 선택해주세요.');
    final result = await _api.claim(
      businessId: id, ownerName: field('owner').text,
      registrationNumber: field('number').text,
      phone: field('contact').text,
    );
    final raw = result['claim'];
    if (!mounted || raw is! Map) return;
    final claim = Map<String, dynamic>.from(raw);
    final previous = picked;
    setState(() {
      claims = [claim, ...claims];
      picked = previous;
      message = '신청 완료. 승인 전 수정 내용은 초안으로만 저장됩니다.';
    });
    _edit(claim);
    field('number').clear();
  });

  Future<void> _save() => _run(() async {
    final id = int.tryParse(editing?['id']?.toString() ?? '');
    if (id == null) return;
    final result = await _api.saveDraft(
      claimId: id,
      basic: {for (final name in labels.keys) name: field(name).text.trim()},
      extraInformation: field('extra').text.trim(),
      agentInstructions: field('instructions').text.trim(),
    );
    if (!mounted) return;
    final raw = result['claim'];
    if (raw is Map) {
      final newClaim = Map<String, dynamic>.from(raw);
      setState(() {
        editing = newClaim;
        claims = claims.map((old) => old['id'] == id ? newClaim : old).toList();
      });
    }
    setState(() => message = result['message']?.toString() ?? '저장했습니다.');
  });

  Future<void> _logout() => _run(() async {
    await _api.logout();
    if (!mounted) return;
    setState(() {
      signedIn = false;
      claims = [];
      businesses = [];
      editing = null;
      picked = null;
    });
  });

  Widget _input(String name, String label, {bool obscure = false, int lines = 1}) =>
      Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: TextField(
          controller: field(name),
          obscureText: obscure,
          maxLines: obscure ? 1 : lines,
          onChanged: name == 'username'
              ? (_) => setState(() => usernameChecked = false) : null,
          decoration: InputDecoration(labelText: label, isDense: true,
              border: const OutlineInputBorder()),
        ),
      );

  Widget _notice(String text) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: const Color(0xFFEDF2FF),
      borderRadius: BorderRadius.circular(12),
    ),
    child: Text(text, style: const TextStyle(fontSize: 13, height: 1.4)),
  );

  Widget _auth() => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
    const Text('사업자 회원', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
    const SizedBox(height: 12),
    SegmentedButton<bool>(
      segments: const [
        ButtonSegment(value: false, label: Text('로그인')),
        ButtonSegment(value: true, label: Text('회원가입')),
      ],
      selected: {isSignup},
      onSelectionChanged: (value) => setState(() => isSignup = value.first),
    ),
    const SizedBox(height: 15),
    _input('username', '아이디'),
    if (isSignup) OutlinedButton(
      onPressed: busy ? null : _checkId,
      child: Text(usernameChecked ? '아이디 사용 가능' : '아이디 중복 확인'),
    ),
    _input('password', '비밀번호', obscure: true),
    if (isSignup) ...[
      _input('confirm', '비밀번호 재입력', obscure: true),
      CheckboxListTile(
        title: const Text('이용약관 동의'),
        value: terms, onChanged: (value) => setState(() => terms = value ?? false),
        controlAffinity: ListTileControlAffinity.leading,
        contentPadding: EdgeInsets.zero,
      ),
      CheckboxListTile(
        title: const Text('개인정보 처리방침 동의'),
        value: privacy, onChanged: (value) => setState(() => privacy = value ?? false),
        controlAffinity: ListTileControlAffinity.leading,
        contentPadding: EdgeInsets.zero,
      ),
    ],
    FilledButton(onPressed: busy ? null : _login, child: Text(isSignup ? '회원가입' : '로그인')),
    const SizedBox(height: 12),
    _notice('관리자 테스트 앱의 사업자 화면입니다. 모드를 바꿔도 사업장 관리권한은 생기지 않으며 서버가 소유권을 검증합니다.'),
  ]);

  Widget _businessArea() => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
    Row(children: [
      const Expanded(child: Text('내 업체 관리', style: TextStyle(fontSize: 21, fontWeight: FontWeight.w800))),
      TextButton(onPressed: busy ? null : _logout, child: const Text('로그아웃')),
    ]),
    Text('로그인: $username', style: const TextStyle(color: Colors.black54)),
    const SizedBox(height: 12),
    if (claims.isEmpty) _notice('기존 업체 DB에서 상호명을 찾아 관리권한을 신청하세요.'),
    for (final claim in claims) Card(child: ListTile(
      leading: const Icon(Icons.store_outlined),
      title: Text(claim['business_name']?.toString() ?? ''),
      subtitle: Text(claim['status'] == 'approved' ? '인증완료 · 직접 수정 가능'
          : claim['status'] == 'rejected' ? '심사 거절' : '심사중 · 초안만 저장 가능'),
      trailing: const Icon(Icons.edit_outlined),
      onTap: () => _edit(claim),
    )),
    const SizedBox(height: 12),
    const Text('ARABA 기존 업체 DB 검색', style: TextStyle(fontWeight: FontWeight.w800)),
    const SizedBox(height: 8),
    _input('search', '상호명 또는 지역'),
    FilledButton(onPressed: busy ? null : _search, child: const Text('업체 검색')),
    for (final business in businesses) Card(child: ListTile(
      title: Text(business['name']?.toString() ?? ''),
      subtitle: Text(business['address']?.toString() ?? ''),
      trailing: const Icon(Icons.chevron_right),
      onTap: () => setState(() { picked = business; editing = null; }),
    )),
    if (picked != null) _claimArea(),
    if (editing != null) _editArea(),
  ]);

  Widget _claimArea() => Card(child: Padding(
    padding: const EdgeInsets.all(14),
    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text('관리권한 신청: ${picked?['name']?.toString() ?? ''}',
          style: const TextStyle(fontWeight: FontWeight.w800)),
      Text(picked?['address']?.toString() ?? ''),
      const SizedBox(height: 12),
      _input('owner', '대표자 성명'),
      _input('number', '사업자등록번호 (10자리)'),
      _input('contact', '연락처 (선택)'),
      _notice('사업자등록번호 원문은 저장하지 않습니다. 증명서 첨부는 비공개 문서 저장소와 본인확인 기능을 갖춘 뒤 추가합니다. 승인 전에는 공개 업체 DB를 수정할 수 없습니다.'),
      const SizedBox(height: 10),
      FilledButton(onPressed: busy ? null : _claim, child: const Text('관리권한 신청')),
    ]),
  ));

  Widget _editArea() {
    final approved = editing?['status'] == 'approved';
    return Card(child: Padding(
      padding: const EdgeInsets.all(14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(approved ? '업체 정보 수정' : '업체 정보 수정 초안',
          style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800)),
        const SizedBox(height: 8),
        _notice(approved
          ? '인증된 사업주입니다. 저장하면 기존 업체 DB에 반영됩니다.'
          : '관리권한 심사 중입니다. 수정은 초안으로만 저장됩니다.'),
        const SizedBox(height: 12),
        for (final entry in labels.entries) _input(entry.key, entry.value),
        _input('extra', '추가 업체 정보 (자유 입력)', lines: 5),
        _input('instructions', 'AI 직원 운영지침 (자유 입력)', lines: 5),
        _notice('자유 입력 AI 지침만으로 예약·할인·결제 자동 확정 권한이 생기지 않습니다.'),
        const SizedBox(height: 10),
        FilledButton.icon(
          onPressed: busy ? null : _save,
          icon: const Icon(Icons.save_outlined),
          label: Text(approved ? '기존 업체 DB에 저장' : '수정 초안 저장'),
        ),
      ]),
    ));
  }

  @override
  Widget build(BuildContext context) => SafeArea(child: ListView(
    padding: const EdgeInsets.all(16),
    children: [
      const SizedBox(height: 5),
      if (message.isNotEmpty) ...[_notice(message), const SizedBox(height: 12)],
      if (busy) const LinearProgressIndicator(),
      if (signedIn) _businessArea() else _auth(),
      const SizedBox(height: 32),
    ],
  ));
}
