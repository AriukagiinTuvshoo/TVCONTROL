// FamilyScreen — Эцэг эхийн удирдлагын гар утасны апп (Flutter — iOS & Android)
// FastAPI Cloud Backend-тэй бодит HTTP REST интеграци хийгдсэн хувилбар.

import 'package:flutter/material.dart';

import 'config/env.dart';
import 'models/api_models.dart';
import 'services/api_client.dart';
import 'services/token_storage.dart';

void main() {
  final apiClient = FamilyScreenApiClient();
  runApp(FamilyScreenParentApp(apiClient: apiClient));
}

class FamilyScreenParentApp extends StatelessWidget {
  const FamilyScreenParentApp({
    super.key,
    required this.apiClient,
  });

  final FamilyScreenApiClient apiClient;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'FamilyScreen',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF0F766E),
          brightness: Brightness.light,
        ),
        scaffoldBackgroundColor: const Color(0xFFF8FAFC),
        cardTheme: CardTheme(
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
            side: const BorderSide(color: Color(0xFFE2E8F0)),
          ),
        ),
      ),
      home: AuthGateScreen(apiClient: apiClient),
    );
  }
}

class AuthGateScreen extends StatefulWidget {
  const AuthGateScreen({super.key, required this.apiClient});

  final FamilyScreenApiClient apiClient;

  @override
  State<AuthGateScreen> createState() => _AuthGateScreenState();
}

class _AuthGateScreenState extends State<AuthGateScreen> {
  AuthSessionData? _session;
  bool _checkingSession = true;

  @override
  void initState() {
    super.initState();
    _restoreSession();
  }

  Future<void> _restoreSession() async {
    final stored = await widget.apiClient.tokenStorage.readSession();
    if (!mounted) return;
    setState(() {
      _session = stored;
      _checkingSession = false;
    });
  }

  void _onAuthenticated(AuthSessionData session) {
    setState(() {
      _session = session;
    });
  }

  Future<void> _onLogout() async {
    await widget.apiClient.logout();
    if (!mounted) return;
    setState(() {
      _session = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_checkingSession) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }
    if (_session == null) {
      return AuthScreen(
        apiClient: widget.apiClient,
        onAuthenticated: _onAuthenticated,
      );
    }
    return ParentHomeShell(
      apiClient: widget.apiClient,
      session: _session!,
      onLogout: _onLogout,
    );
  }
}

// ============================================================================
// FR-01: Login & Registration Screen
// ============================================================================

class AuthScreen extends StatefulWidget {
  const AuthScreen({
    super.key,
    required this.apiClient,
    required this.onAuthenticated,
  });

  final FamilyScreenApiClient apiClient;
  final ValueChanged<AuthSessionData> onAuthenticated;

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  bool _isLoginMode = true;
  bool _isSubmitting = false;
  String? _errorMessage;

  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _fullNameController = TextEditingController();
  final _familyNameController = TextEditingController();
  final _pinController = TextEditingController(text: '2580');

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _fullNameController.dispose();
    _familyNameController.dispose();
    _pinController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _isSubmitting = true;
      _errorMessage = null;
    });

    try {
      if (_isLoginMode) {
        final session = await widget.apiClient.login(
          email: _emailController.text,
          password: _passwordController.text,
        );
        widget.onAuthenticated(session);
      } else {
        final session = await widget.apiClient.register(
          email: _emailController.text,
          password: _passwordController.text,
          fullName: _fullNameController.text,
          familyName: _familyNameController.text,
          pinCode: _pinController.text,
        );
        widget.onAuthenticated(session);
      }
    } on ApiException catch (e) {
      setState(() {
        _errorMessage = e.message;
      });
    } finally {
      if (mounted) {
        setState(() {
          _isSubmitting = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Card(
                color: Colors.white,
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Icon(
                        Icons.live_tv_rounded,
                        size: 48,
                        color: Color(0xFF0F766E),
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        'FamilyScreen',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 24,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      Text(
                        _isLoginMode
                            ? 'Эцэг эхийн бүртгэлээр нэвтрэх'
                            : 'Гэр бүлийн шинэ бүртгэл үүсгэх',
                        textAlign: TextAlign.center,
                        style: const TextStyle(color: Colors.black54),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'API: ${AppEnv.apiBaseUrl}',
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          fontSize: 11,
                          color: Colors.black38,
                        ),
                      ),
                      const SizedBox(height: 20),
                      if (_errorMessage != null) ...[
                        Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: const Color(0xFFFEE2E2),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Text(
                            _errorMessage!,
                            style: const TextStyle(
                              color: Color(0xFFB91C1C),
                              fontSize: 13,
                            ),
                          ),
                        ),
                        const SizedBox(height: 16),
                      ],
                      TextField(
                        key: const Key('auth_email_field'),
                        controller: _emailController,
                        keyboardType: TextInputType.emailAddress,
                        decoration: const InputDecoration(
                          labelText: 'Имэйл хаяг',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        key: const Key('auth_password_field'),
                        controller: _passwordController,
                        obscureText: true,
                        decoration: const InputDecoration(
                          labelText: 'Нууц үг (6+ тэмдэгт)',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      if (!_isLoginMode) ...[
                        const SizedBox(height: 12),
                        TextField(
                          key: const Key('auth_fullname_field'),
                          controller: _fullNameController,
                          decoration: const InputDecoration(
                            labelText: 'Эцэг эхийн нэр',
                            border: OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          key: const Key('auth_familyname_field'),
                          controller: _familyNameController,
                          decoration: const InputDecoration(
                            labelText: 'Гэр бүлийн нэр (жнь: Болдын гэр бүл)',
                            border: OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          key: const Key('auth_pin_field'),
                          controller: _pinController,
                          keyboardType: TextInputType.number,
                          maxLength: 6,
                          decoration: const InputDecoration(
                            labelText: 'ТВ нээх 4-6 оронтой PIN код',
                            border: OutlineInputBorder(),
                          ),
                        ),
                      ],
                      const SizedBox(height: 16),
                      FilledButton(
                        key: const Key('auth_submit_button'),
                        onPressed: _isSubmitting ? null : _submit,
                        child: _isSubmitting
                            ? const SizedBox(
                                height: 18,
                                width: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : Text(_isLoginMode ? 'Нэвтрэх' : 'Бүртгүүлэх'),
                      ),
                      const SizedBox(height: 8),
                      TextButton(
                        key: const Key('auth_toggle_mode_button'),
                        onPressed: () {
                          setState(() {
                            _isLoginMode = !_isLoginMode;
                            _errorMessage = null;
                          });
                        },
                        child: Text(
                          _isLoginMode
                              ? 'Шинэ хэрэглэгч үү? Бүртгэл үүсгэх'
                              : 'Бүртгэлтэй юу? Нэвтрэх',
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ============================================================================
// Authenticated Parent Home Shell
// ============================================================================

class ParentHomeShell extends StatefulWidget {
  const ParentHomeShell({
    super.key,
    required this.apiClient,
    required this.session,
    required this.onLogout,
  });

  final FamilyScreenApiClient apiClient;
  final AuthSessionData session;
  final VoidCallback onLogout;

  @override
  State<ParentHomeShell> createState() => _ParentHomeShellState();
}

class _ParentHomeShellState extends State<ParentHomeShell> {
  int _selectedIndex = 0;
  bool _isLoading = true;
  String? _errorMessage;

  List<ChildDto> _children = [];
  int _selectedChildIdx = 0;
  PolicyDto? _activePolicy;
  List<DeviceDto> _devices = [];
  UsageReportDto? _usageReport;

  static const List<String> _dayNames = [
    'Даваа',
    'Мягмар',
    'Лхагва',
    'Пүрэв',
    'Баасан',
    'Бямба',
    'Ням',
  ];

  ChildDto? get _activeChild =>
      (_children.isNotEmpty && _selectedChildIdx < _children.length)
          ? _children[_selectedChildIdx]
          : null;

  @override
  void initState() {
    super.initState();
    _loadFamilyData();
  }

  Future<void> _loadFamilyData() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final children =
          await widget.apiClient.listChildren(widget.session.familyId);
      final devices =
          await widget.apiClient.listDevices(widget.session.familyId);

      if (_selectedChildIdx >= children.length) {
        _selectedChildIdx = 0;
      }

      PolicyDto? policy;
      UsageReportDto? report;
      if (children.isNotEmpty) {
        final activeId = children[_selectedChildIdx].id;
        policy = await widget.apiClient.getPolicy(activeId);
        report = await widget.apiClient.getUsageReport(
          familyId: widget.session.familyId,
          childId: activeId,
          days: 7,
        );
      }

      if (!mounted) return;
      setState(() {
        _children = children;
        _devices = devices;
        _activePolicy = policy;
        _usageReport = report;
        _isLoading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = e.message;
        _isLoading = false;
      });
    }
  }

  Future<void> _selectChild(int index) async {
    setState(() {
      _selectedChildIdx = index;
    });
    await _loadFamilyData();
  }

  void _showSnack(String message, {bool isError = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? const Color(0xFFB91C1C) : null,
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  // -------------------------------------------------------------------------
  // FR-02: Create / Edit / Delete Child Dialogs
  // -------------------------------------------------------------------------

  Future<void> _showAddOrEditChildDialog({ChildDto? existing}) async {
    final nicknameCtrl =
        TextEditingController(text: existing?.nickname ?? '');
    String ageGroup = existing?.ageGroup ?? '7-9';
    int limitMin = existing?.dailyLimitMinutes ?? 90;

    await showDialog<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: Text(
            existing == null
                ? 'Хүүхдийн профайл нэмэх'
                : 'Хүүхдийн мэдээлэл засах',
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                key: const Key('child_nickname_input'),
                controller: nicknameCtrl,
                decoration: const InputDecoration(
                  labelText: 'Хүүхдийн нэр эсвэл хоч',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                value: ageGroup,
                decoration: const InputDecoration(
                  labelText: 'Насны бүлэг',
                  border: OutlineInputBorder(),
                ),
                items: const [
                  DropdownMenuItem(value: '4-6', child: Text('4-6 нас')),
                  DropdownMenuItem(value: '7-9', child: Text('7-9 нас')),
                  DropdownMenuItem(value: '10-12', child: Text('10-12 нас')),
                  DropdownMenuItem(value: '13-16', child: Text('13-16 нас')),
                ],
                onChanged: (val) {
                  if (val != null) setDialogState(() => ageGroup = val);
                },
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<int>(
                value: limitMin,
                decoration: const InputDecoration(
                  labelText: 'Өдрийн лимит',
                  border: OutlineInputBorder(),
                ),
                items: const [30, 60, 90, 120, 180]
                    .map(
                      (m) => DropdownMenuItem(
                        value: m,
                        child: Text('$m минут'),
                      ),
                    )
                    .toList(),
                onChanged: (val) {
                  if (val != null) setDialogState(() => limitMin = val);
                },
              ),
            ],
          ),
          actions: [
            if (existing != null)
              TextButton(
                onPressed: () async {
                  Navigator.pop(ctx);
                  try {
                    await widget.apiClient.deleteChild(existing.id);
                    _showSnack('${existing.nickname} профайл устгагдлаа.');
                    await _loadFamilyData();
                  } on ApiException catch (e) {
                    _showSnack(e.message, isError: true);
                  }
                },
                child: const Text(
                  'Устгах',
                  style: TextStyle(color: Color(0xFFB91C1C)),
                ),
              ),
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Болих'),
            ),
            FilledButton(
              key: const Key('save_child_button'),
              onPressed: () async {
                if (nicknameCtrl.text.trim().isEmpty) return;
                Navigator.pop(ctx);
                try {
                  if (existing == null) {
                    await widget.apiClient.createChild(
                      familyId: widget.session.familyId,
                      nickname: nicknameCtrl.text,
                      ageGroup: ageGroup,
                      dailyLimitMinutes: limitMin,
                    );
                    _showSnack('Хүүхдийн профайл амжилттай үүслээ.');
                  } else {
                    await widget.apiClient.updateChild(
                      childId: existing.id,
                      nickname: nicknameCtrl.text,
                      ageGroup: ageGroup,
                      dailyLimitMinutes: limitMin,
                    );
                    _showSnack('Мэдээлэл шинэчлэгдлээ.');
                  }
                  await _loadFamilyData();
                } on ApiException catch (e) {
                  _showSnack(e.message, isError: true);
                }
              },
              child: const Text('Хадгалах'),
            ),
          ],
        ),
      ),
    );
  }

  // -------------------------------------------------------------------------
  // FR-03: Device Pairing Init + Claim Dialog
  // -------------------------------------------------------------------------

  Future<void> _showPairDeviceDialog() async {
    final codeController = TextEditingController();
    final nameController =
        TextEditingController(text: 'Зочны өрөөний FamilyScreen Box');

    await showDialog<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: const Text('TV / FamilyScreen Box холбох'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'ТВ дэлгэц дээр харагдаж буй 6 оронтой кодыг оруулна уу.',
                style: TextStyle(fontSize: 13, color: Colors.black54),
              ),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                key: const Key('simulate_tv_code_button'),
                onPressed: () async {
                  try {
                    final res = await widget.apiClient.initDevicePairing(
                      hardwareUid:
                          'box-${DateTime.now().millisecondsSinceEpoch}',
                    );
                    setDialogState(() {
                      codeController.text = res.pairingCode;
                    });
                  } on ApiException catch (e) {
                    _showSnack(e.message, isError: true);
                  }
                },
                icon: const Icon(Icons.tv_rounded, size: 18),
                label: const Text('Туршилтын ТВ код үүсгэх (Pair Init)'),
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key('pair_code_input'),
                controller: codeController,
                keyboardType: TextInputType.number,
                maxLength: 6,
                decoration: const InputDecoration(
                  labelText: '6 оронтой холбох код',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 8),
              TextField(
                key: const Key('pair_device_name_input'),
                controller: nameController,
                decoration: const InputDecoration(
                  labelText: 'Төхөөрөмжийн нэр',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Болих'),
            ),
            FilledButton(
              key: const Key('claim_device_button'),
              onPressed: () async {
                if (codeController.text.trim().length < 6) return;
                Navigator.pop(ctx);
                try {
                  final claimed = await widget.apiClient.claimDevicePairing(
                    familyId: widget.session.familyId,
                    pairingCode: codeController.text,
                    deviceName: nameController.text,
                    activeChildId: _activeChild?.id,
                  );
                  _showSnack('${claimed.deviceName} амжилттай холбогдлоо!');
                  await _loadFamilyData();
                } on ApiException catch (e) {
                  _showSnack(e.message, isError: true);
                }
              },
              child: const Text('Холбох'),
            ),
          ],
        ),
      ),
    );
  }

  // -------------------------------------------------------------------------
  // FR-07: Remote Override (+15 / +30 min) & Instant Lock
  // -------------------------------------------------------------------------

  Future<void> _grantRemoteExtraTime(int minutes) async {
    final child = _activeChild;
    if (child == null) return;
    try {
      await widget.apiClient.grantRemoteOverride(
        familyId: widget.session.familyId,
        childId: child.id,
        addedMinutes: minutes,
      );
      _showSnack('${child.nickname}-д +$minutes минут нэмэлт хугацаа олголоо.');
      await _loadFamilyData();
    } on ApiException catch (e) {
      _showSnack(e.message, isError: true);
    }
  }

  Future<void> _toggleInstantLock() async {
    final policy = _activePolicy;
    final child = _activeChild;
    if (policy == null || child == null) return;
    try {
      await widget.apiClient.updatePolicy(
        childId: child.id,
        dailyLimitMinutes: policy.dailyLimitMinutes,
        weekendBonusMinutes: policy.weekendBonusMinutes,
        enforceWhitelist: policy.enforceWhitelist,
        isInstantLocked: !policy.isInstantLocked,
        warningMinutes: policy.warningMinutes,
        schedules: policy.schedules,
        allowedApps: policy.allowedApps,
      );
      await _loadFamilyData();
    } on ApiException catch (e) {
      _showSnack(e.message, isError: true);
    }
  }

  Future<void> _saveCurrentPolicy() async {
    final policy = _activePolicy;
    final child = _activeChild;
    if (policy == null || child == null) return;
    try {
      await widget.apiClient.updatePolicy(
        childId: child.id,
        dailyLimitMinutes: policy.dailyLimitMinutes,
        weekendBonusMinutes: policy.weekendBonusMinutes,
        enforceWhitelist: policy.enforceWhitelist,
        isInstantLocked: policy.isInstantLocked,
        warningMinutes: policy.warningMinutes,
        schedules: policy.schedules,
        allowedApps: policy.allowedApps,
      );
      _showSnack('Хяналтын дүрэм серверт хадгалагдлаа.');
      await _loadFamilyData();
    } on ApiException catch (e) {
      _showSnack(e.message, isError: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              widget.session.familyName,
              style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 18),
            ),
            Text(
              'Эцэг эх: ${widget.session.userFullName} (${widget.session.planTier})',
              style: const TextStyle(fontSize: 12, color: Colors.black54),
            ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Шинэчлэх',
            onPressed: _loadFamilyData,
            icon: const Icon(Icons.refresh_rounded),
          ),
          IconButton(
            tooltip: 'Төхөөрөмж холбох (QR / Код)',
            onPressed: _showPairDeviceDialog,
            icon: const Icon(Icons.qr_code_scanner_rounded),
          ),
          IconButton(
            tooltip: 'Гарах',
            onPressed: widget.onLogout,
            icon: const Icon(Icons.logout_rounded),
          ),
        ],
      ),
      body: SafeArea(
        child: _buildBody(),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedIndex,
        onDestinationSelected: (idx) => setState(() => _selectedIndex = idx),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.dashboard_outlined),
            selectedIcon: Icon(Icons.dashboard_rounded),
            label: 'Хяналт',
          ),
          NavigationDestination(
            icon: Icon(Icons.timer_outlined),
            selectedIcon: Icon(Icons.timer_rounded),
            label: 'Хугацаа',
          ),
          NavigationDestination(
            icon: Icon(Icons.apps_outlined),
            selectedIcon: Icon(Icons.apps_rounded),
            label: 'Апп Whitelist',
          ),
          NavigationDestination(
            icon: Icon(Icons.bar_chart_outlined),
            selectedIcon: Icon(Icons.bar_chart_rounded),
            label: 'Тайлан & PIN',
          ),
        ],
      ),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_errorMessage != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(
                Icons.error_outline_rounded,
                size: 48,
                color: Color(0xFFB91C1C),
              ),
              const SizedBox(height: 12),
              Text(
                _errorMessage!,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 15),
              ),
              const SizedBox(height: 16),
              FilledButton.icon(
                onPressed: _loadFamilyData,
                icon: const Icon(Icons.refresh_rounded),
                label: const Text('Дахин оролдох'),
              ),
            ],
          ),
        ),
      );
    }

    if (_children.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(
                Icons.child_care_rounded,
                size: 56,
                color: Color(0xFF0F766E),
              ),
              const SizedBox(height: 12),
              const Text(
                'Одоогоор хүүхдийн профайл нэмээгүй байна',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 8),
              const Text(
                'Хүүхдийнхээ нэр болон өдрийн ТВ үзэх хязгаарыг тохируулж эхэлнэ үү.',
                textAlign: TextAlign.center,
                style: TextStyle(color: Colors.black54),
              ),
              const SizedBox(height: 16),
              FilledButton.icon(
                key: const Key('empty_add_child_button'),
                onPressed: () => _showAddOrEditChildDialog(),
                icon: const Icon(Icons.add_rounded),
                label: const Text('Хүүхдийн профайл нэмэх'),
              ),
            ],
          ),
        ),
      );
    }

    final pages = [
      _buildDashboardTab(),
      _buildLimitsAndScheduleTab(),
      _buildWhitelistTab(),
      _buildReportsAndPinTab(),
    ];

    return Column(
      children: [
        _buildChildSelectorBar(),
        Expanded(child: pages[_selectedIndex]),
      ],
    );
  }

  Widget _buildChildSelectorBar() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      color: Colors.white,
      child: Row(
        children: [
          const Text(
            'Хүүхэд:',
            style: TextStyle(fontWeight: FontWeight.w600),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  ...List.generate(_children.length, (idx) {
                    final child = _children[idx];
                    final selected = idx == _selectedChildIdx;
                    return Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: InputChip(
                        label: Text('${child.nickname} (${child.ageGroup})'),
                        selected: selected,
                        onSelected: (_) => _selectChild(idx),
                        onDeleted: () =>
                            _showAddOrEditChildDialog(existing: child),
                        deleteIcon: const Icon(Icons.edit_outlined, size: 16),
                      ),
                    );
                  }),
                  ActionChip(
                    key: const Key('add_child_chip'),
                    avatar: const Icon(Icons.add_rounded, size: 18),
                    label: const Text('Нэмэх'),
                    onPressed: () => _showAddOrEditChildDialog(),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildDashboardTab() {
    final child = _activeChild!;
    final state = child.engineState;
    final Color badgeColor = state == 'ALLOW'
        ? const Color(0xFF16A34A)
        : state == 'WARNING'
            ? const Color(0xFFD97706)
            : const Color(0xFFDC2626);

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          color: Colors.white,
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      '${child.nickname}-ийн өнөөдрийн төлөв',
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 4,
                      ),
                      decoration: BoxDecoration(
                        color: badgeColor.withOpacity(0.12),
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Text(
                        state,
                        style: TextStyle(
                          color: badgeColor,
                          fontWeight: FontWeight.bold,
                          fontSize: 12,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.baseline,
                  textBaseline: TextBaseline.alphabetic,
                  children: [
                    Text(
                      '${child.remainingMinutes}',
                      key: const Key('remaining_minutes_text'),
                      style: const TextStyle(
                        fontSize: 44,
                        fontWeight: FontWeight.w900,
                        color: Color(0xFF0F172A),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      'минут үлдсэн (Нийт ${child.totalAllowedMinutes} мин)',
                      style: const TextStyle(
                        fontSize: 14,
                        color: Colors.black54,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                LinearProgressIndicator(
                  value: child.totalAllowedMinutes == 0
                      ? 1
                      : (child.usedMinutesToday / child.totalAllowedMinutes)
                          .clamp(0.0, 1.0),
                  minHeight: 10,
                  borderRadius: BorderRadius.circular(8),
                ),
                const SizedBox(height: 16),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    FilledButton.tonalIcon(
                      key: const Key('override_15_button'),
                      onPressed: () => _grantRemoteExtraTime(15),
                      icon: const Icon(Icons.add_alarm_rounded),
                      label: const Text('+15 мин нэмэх'),
                    ),
                    FilledButton.tonalIcon(
                      key: const Key('override_30_button'),
                      onPressed: () => _grantRemoteExtraTime(30),
                      icon: const Icon(Icons.more_time_rounded),
                      label: const Text('+30 мин нэмэх'),
                    ),
                    OutlinedButton.icon(
                      key: const Key('instant_lock_button'),
                      onPressed: _toggleInstantLock,
                      icon: Icon(
                        (_activePolicy?.isInstantLocked ?? false)
                            ? Icons.lock_open_rounded
                            : Icons.lock_rounded,
                      ),
                      label: Text(
                        (_activePolicy?.isInstantLocked ?? false)
                            ? 'Түгжээ гаргах'
                            : 'ТВ Түгжих',
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text(
              'Холбогдсон ТВ төхөөрөмжүүд (FR-03)',
              style: TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
            ),
            TextButton.icon(
              onPressed: _showPairDeviceDialog,
              icon: const Icon(Icons.add_rounded, size: 18),
              label: const Text('Төхөөрөмж нэмэх'),
            ),
          ],
        ),
        if (_devices.isEmpty)
          const Card(
            color: Colors.white,
            child: Padding(
              padding: EdgeInsets.all(16),
              child: Text(
                'Холбогдсон ТВ байхгүй байна. Баруун дээд булангийн QR товчоор ТВ-ээ холбоно уу.',
                style: TextStyle(color: Colors.black54),
              ),
            ),
          )
        else
          ..._devices.map(
            (dev) => Card(
              color: Colors.white,
              margin: const EdgeInsets.only(bottom: 8),
              child: ListTile(
                leading: const CircleAvatar(
                  backgroundColor: Color(0xFFDCFCE7),
                  child: Icon(Icons.tv_rounded, color: Color(0xFF15803D)),
                ),
                title: Text(
                  dev.deviceName,
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                subtitle: Text('${dev.deviceType} • Төлөв: ${dev.status}'),
                trailing: IconButton(
                  tooltip: 'Төхөөрөмж салгах',
                  icon: const Icon(Icons.link_off_rounded),
                  onPressed: () async {
                    try {
                      await widget.apiClient.unpairDevice(dev.id);
                      _showSnack('${dev.deviceName} салгагдлаа.');
                      await _loadFamilyData();
                    } on ApiException catch (e) {
                      _showSnack(e.message, isError: true);
                    }
                  },
                ),
              ),
            ),
          ),
      ],
    );
  }

  Widget _buildLimitsAndScheduleTab() {
    final policy = _activePolicy;
    if (policy == null) {
      return const Center(child: Text('Дүрмийн мэдээлэл олдсонгүй.'));
    }
    const presetLimits = [30, 60, 90, 120, 180];

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          color: Colors.white,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Өдрийн үзэх хугацааны лимит (FR-04)',
                  style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  children: presetLimits.map((minVal) {
                    final selected = policy.dailyLimitMinutes == minVal;
                    return ChoiceChip(
                      label: Text('$minVal мин'),
                      selected: selected,
                      onSelected: (_) async {
                        setState(() => policy.dailyLimitMinutes = minVal);
                        await _saveCurrentPolicy();
                      },
                    );
                  }).toList(),
                ),
                const SizedBox(height: 16),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text('Амралтын өдрийн нэмэлт бонус:'),
                    DropdownButton<int>(
                      value: policy.weekendBonusMinutes,
                      items: const [0, 15, 30, 60]
                          .map(
                            (b) => DropdownMenuItem(
                              value: b,
                              child: Text('+$b мин'),
                            ),
                          )
                          .toList(),
                      onChanged: (val) async {
                        if (val == null) return;
                        setState(() => policy.weekendBonusMinutes = val);
                        await _saveCurrentPolicy();
                      },
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        Card(
          color: Colors.white,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Долоо хоногийн цагийн хуваарь (FR-05)',
                  style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
                ),
                const SizedBox(height: 8),
                ...policy.schedules.map((sched) {
                  final dayLabel = _dayNames[sched.dayOfWeek % 7];
                  return SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(
                      '$dayLabel (${sched.startTime} – ${sched.endTime})',
                    ),
                    subtitle: Text(
                      sched.isSchoolDay ? 'Хичээлтэй өдөр' : 'Амралтын өдөр',
                    ),
                    value: sched.isEnabled,
                    onChanged: (val) async {
                      setState(() => sched.isEnabled = val);
                      await _saveCurrentPolicy();
                    },
                  );
                }),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildWhitelistTab() {
    final policy = _activePolicy;
    if (policy == null) {
      return const Center(child: Text('Дүрмийн мэдээлэл олдсонгүй.'));
    }

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          color: Colors.white,
          margin: const EdgeInsets.only(bottom: 12),
          child: SwitchListTile(
            title: const Text(
              'Зөвшөөрөгдсөн аппын хязгаарлалт (Whitelist Enforcement)',
              style: TextStyle(fontWeight: FontWeight.w700),
            ),
            subtitle: const Text(
              'Идэвхтэй үед зөвхөн доор сонгосон аппууд FamilyScreen Box дээр нээгдэнэ.',
            ),
            value: policy.enforceWhitelist,
            onChanged: (val) async {
              setState(() => policy.enforceWhitelist = val);
              await _saveCurrentPolicy();
            },
          ),
        ),
        ...policy.allowedApps.map(
          (app) => Card(
            color: Colors.white,
            margin: const EdgeInsets.only(bottom: 8),
            child: SwitchListTile(
              title: Text(
                app.appLabel,
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
              subtitle: Text('${app.category} • ${app.packageName}'),
              value: app.isAllowed,
              onChanged: (val) async {
                setState(() => app.isAllowed = val);
                await _saveCurrentPolicy();
              },
            ),
          ),
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: () async {
            final pkgCtrl = TextEditingController();
            final labelCtrl = TextEditingController();
            await showDialog<void>(
              context: context,
              builder: (ctx) => AlertDialog(
                title: const Text('Шинэ зөвшөөрөгдсөн апп нэмэх'),
                content: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    TextField(
                      controller: labelCtrl,
                      decoration: const InputDecoration(
                        labelText: 'Аппын нэр (жнь: PBS Kids)',
                        border: OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: pkgCtrl,
                      decoration: const InputDecoration(
                        labelText: 'Package name (жнь: org.pbskids.video)',
                        border: OutlineInputBorder(),
                      ),
                    ),
                  ],
                ),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.pop(ctx),
                    child: const Text('Болих'),
                  ),
                  FilledButton(
                    onPressed: () async {
                      if (labelCtrl.text.trim().isEmpty ||
                          pkgCtrl.text.trim().isEmpty) {
                        return;
                      }
                      Navigator.pop(ctx);
                      policy.allowedApps.add(
                        AllowedAppDto(
                          packageName: pkgCtrl.text.trim(),
                          appLabel: labelCtrl.text.trim(),
                          category: 'EDUCATION',
                          isAllowed: true,
                        ),
                      );
                      await _saveCurrentPolicy();
                    },
                    child: const Text('Нэмэх'),
                  ),
                ],
              ),
            );
          },
          icon: const Icon(Icons.add_rounded),
          label: const Text('Шинэ апп жагсаалтад нэмэх'),
        ),
      ],
    );
  }

  Widget _buildReportsAndPinTab() {
    final report = _usageReport;
    final newPinCtrl = TextEditingController();

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          color: Colors.white,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${_activeChild?.nickname ?? ""}-ийн 7 хоногийн хэрэглээний тайлан (FR-08)',
                  style: const TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 16,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  'Нийт үзсэн: ${report?.totalUsedMinutes ?? 0} минут',
                  style: const TextStyle(
                    fontWeight: FontWeight.w600,
                    color: Color(0xFF0F766E),
                  ),
                ),
                const SizedBox(height: 12),
                if (report == null || report.dailyItems.isEmpty)
                  const Text('Хэрэглээний мэдээлэл одоогоор алга.')
                else
                  ...report.dailyItems.map(
                    (item) => Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(item.usageDate),
                          Text(
                            '${item.usedMinutes} мин / ${item.allowedMinutes} мин'
                            '${item.overrideMinutes > 0 ? " (+${item.overrideMinutes}м)" : ""}',
                            style: const TextStyle(fontWeight: FontWeight.w600),
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        Card(
          color: Colors.white,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Эцэг эхийн PIN код шинэчлэх (FR-07)',
                  style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: newPinCtrl,
                        keyboardType: TextInputType.number,
                        maxLength: 6,
                        decoration: const InputDecoration(
                          labelText: 'Шинэ PIN (4-6 оронтой тоо)',
                          border: OutlineInputBorder(),
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    FilledButton(
                      onPressed: () async {
                        if (newPinCtrl.text.trim().length < 4) return;
                        try {
                          final msg = await widget.apiClient.updateFamilyPin(
                            familyId: widget.session.familyId,
                            newPin: newPinCtrl.text.trim(),
                          );
                          _showSnack(msg);
                        } on ApiException catch (e) {
                          _showSnack(e.message, isError: true);
                        }
                      },
                      child: const Text('Хадгалах'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
