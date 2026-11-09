// HTTP REST API Client connecting Flutter Parent App to FastAPI Backend.
// Translates HTTP / network errors into clear Mongolian user-facing messages.

import 'dart:convert';
import 'package:http/http.dart' as http;

import '../config/env.dart';
import '../models/api_models.dart';
import 'token_storage.dart';

class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class FamilyScreenApiClient {
  FamilyScreenApiClient({
    http.Client? httpClient,
    TokenStorage? tokenStorage,
    String? baseUrl,
  })  : _http = httpClient ?? http.Client(),
        _storage = tokenStorage ?? SecureMemoryTokenStorage(),
        _baseUrl = (baseUrl ?? AppEnv.apiBaseUrl).replaceAll(RegExp(r'/$'), '');

  final http.Client _http;
  final TokenStorage _storage;
  final String _baseUrl;

  TokenStorage get tokenStorage => _storage;

  Future<Map<String, String>> _buildHeaders({bool authenticated = true}) async {
    final headers = <String, String>{
      'Content-Type': 'application/json; charset=utf-8',
      'Accept': 'application/json',
    };
    if (authenticated) {
      final session = await _storage.readSession();
      if (session != null && session.accessToken.isNotEmpty) {
        headers['Authorization'] = 'Bearer ${session.accessToken}';
      }
    }
    return headers;
  }

  Uri _uri(String path, [Map<String, String>? queryParameters]) {
    final full = '$_baseUrl$path';
    final parsed = Uri.parse(full);
    if (queryParameters == null || queryParameters.isEmpty) {
      return parsed;
    }
    return parsed.replace(queryParameters: queryParameters);
  }

  Never _throwFromResponse(http.Response response) {
    String detailMsg = 'Сервертэй холбогдоход алдаа гарлаа (${response.statusCode}).';
    try {
      final decoded = jsonDecode(utf8.decode(response.bodyBytes));
      if (decoded is Map<String, dynamic>) {
        final rawDetail = decoded['detail'];
        if (rawDetail is String && rawDetail.isNotEmpty) {
          detailMsg = rawDetail;
        } else if (rawDetail is List && rawDetail.isNotEmpty) {
          detailMsg = 'Оруулсан мэдээлэл буруу эсвэл дутуу байна.';
        }
      }
    } catch (_) {
      // Fallback to default Mongolian status message
    }
    throw ApiException(detailMsg, statusCode: response.statusCode);
  }

  // -------------------------------------------------------------------------
  // FR-01: Authentication (Register / Login / Session / Logout)
  // -------------------------------------------------------------------------

  Future<AuthSessionData> register({
    required String email,
    required String password,
    required String fullName,
    required String familyName,
    required String pinCode,
    String? phone,
  }) async {
    try {
      final response = await _http.post(
        _uri('/api/v1/auth/register'),
        headers: await _buildHeaders(authenticated: false),
        body: jsonEncode({
          'email': email.trim(),
          'phone': (phone != null && phone.trim().isNotEmpty) ? phone.trim() : null,
          'password': password,
          'full_name': fullName.trim(),
          'family_name': familyName.trim(),
          'pin_code': pinCode.trim(),
        }),
      );
      if (response.statusCode != 201 && response.statusCode != 200) {
        _throwFromResponse(response);
      }
      final data = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      final session = _parseAuthResponse(data);
      await _storage.saveSession(session);
      return session;
    } on ApiException {
      rethrow;
    } catch (_) {
      throw const ApiException(
        'Сервертэй холбогдож чадсангүй. Интернэт эсвэл серверийн хаягаа шалгана уу.',
      );
    }
  }

  Future<AuthSessionData> login({
    required String email,
    required String password,
  }) async {
    try {
      final response = await _http.post(
        _uri('/api/v1/auth/login'),
        headers: await _buildHeaders(authenticated: false),
        body: jsonEncode({
          'email': email.trim(),
          'password': password,
        }),
      );
      if (response.statusCode != 200) {
        _throwFromResponse(response);
      }
      final data = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      final session = _parseAuthResponse(data);
      await _storage.saveSession(session);
      return session;
    } on ApiException {
      rethrow;
    } catch (_) {
      throw const ApiException(
        'Нэвтрэх үед сүлжээний алдаа гарлаа. Сервер ажиллаж байгаа эсэхийг шалгана уу.',
      );
    }
  }

  /// Connects with Supabase Auth session JWT and initializes backend family profile.
  Future<AuthSessionData> loginWithSupabaseToken(String supabaseJwt) async {
    try {
      final response = await _http.get(
        _uri('/api/v1/auth/me'),
        headers: {
          'Content-Type': 'application/json; charset=utf-8',
          'Accept': 'application/json',
          'Authorization': 'Bearer $supabaseJwt',
        },
      );
      if (response.statusCode != 200) {
        _throwFromResponse(response);
      }
      final data = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      final session = _parseAuthResponse(data);
      await _storage.saveSession(session);
      return session;
    } on ApiException {
      rethrow;
    } catch (_) {
      throw const ApiException(
        'Supabase нэвтрэлтийг баталгаажуулахад сүлжээний алдаа гарлаа.',
      );
    }
  }

  /// Syncs or updates initial family details for a Supabase-authenticated parent.
  Future<AuthSessionData> syncSupabaseProfile({
    String? familyName,
    String? pinCode,
    String? timezone,
  }) async {
    try {
      final response = await _http.post(
        _uri('/api/v1/auth/supabase/sync'),
        headers: await _buildHeaders(authenticated: true),
        body: jsonEncode({
          if (familyName != null) 'family_name': familyName,
          if (pinCode != null) 'pin_code': pinCode,
          if (timezone != null) 'timezone': timezone,
        }),
      );
      if (response.statusCode != 200) {
        _throwFromResponse(response);
      }
      final data = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      final session = _parseAuthResponse(data);
      await _storage.saveSession(session);
      return session;
    } on ApiException {
      rethrow;
    } catch (_) {
      throw const ApiException(
        'Supabase бүртгэлийг системтэй холбоход сүлжээний алдаа гарлаа.',
      );
    }
  }

  Future<void> logout() async {
    await _storage.clearSession();
  }

  AuthSessionData _parseAuthResponse(Map<String, dynamic> data) {
    final user = data['user'] as Map<String, dynamic>;
    final family = data['family'] as Map<String, dynamic>;
    return AuthSessionData(
      accessToken: data['access_token'] as String,
      userId: user['id'] as String,
      userEmail: user['email'] as String,
      userFullName: user['full_name'] as String,
      familyId: family['id'] as String,
      familyName: family['name'] as String,
      planTier: (family['plan_tier'] as String?) ?? 'FREE',
      pinConfigured: (family['pin_configured'] as bool?) ?? false,
    );
  }

  /// Explicitly links an existing local account to a verified Supabase login.
  Future<AuthSessionData> linkSupabaseAccount({
    required String localPassword,
    String? supabaseJwt,
  }) async {
    try {
      final headers = await _buildHeaders(authenticated: false);
      if (supabaseJwt != null && supabaseJwt.isNotEmpty) {
        headers['Authorization'] = 'Bearer $supabaseJwt';
      }
      final response = await _http.post(
        _uri('/api/v1/auth/supabase/link-account'),
        headers: headers,
        body: jsonEncode({
          'local_password': localPassword,
        }),
      );
      if (response.statusCode != 200) {
        _throwFromResponse(response);
      }
      final data = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
      final session = _parseAuthResponse(data);
      await _storage.saveSession(session);
      return session;
    } on ApiException {
      rethrow;
    } catch (_) {
      throw const ApiException(
        'Supabase данс холбоход сүлжээний алдаа гарлаа.',
      );
    }
  }

  // -------------------------------------------------------------------------
  // FR-02: Child Profile CRUD
  // -------------------------------------------------------------------------

  Future<List<ChildDto>> listChildren(String familyId) async {
    final response = await _http.get(
      _uri('/api/v1/families/$familyId/children'),
      headers: await _buildHeaders(),
    );
    if (response.statusCode != 200) {
      _throwFromResponse(response);
    }
    final list = jsonDecode(utf8.decode(response.bodyBytes)) as List<dynamic>;
    return list
        .map((e) => ChildDto.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<ChildDto> createChild({
    required String familyId,
    required String nickname,
    required String ageGroup,
    required int dailyLimitMinutes,
    String avatarKey = 'fox',
  }) async {
    final response = await _http.post(
      _uri('/api/v1/children'),
      headers: await _buildHeaders(),
      body: jsonEncode({
        'family_id': familyId,
        'nickname': nickname.trim(),
        'age_group': ageGroup,
        'avatar_key': avatarKey,
        'daily_limit_minutes': dailyLimitMinutes,
      }),
    );
    if (response.statusCode != 201 && response.statusCode != 200) {
      _throwFromResponse(response);
    }
    return ChildDto.fromJson(
      jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
    );
  }

  Future<ChildDto> updateChild({
    required String childId,
    String? nickname,
    String? ageGroup,
    int? dailyLimitMinutes,
  }) async {
    final body = <String, dynamic>{};
    if (nickname != null) body['nickname'] = nickname.trim();
    if (ageGroup != null) body['age_group'] = ageGroup;
    if (dailyLimitMinutes != null) {
      body['daily_limit_minutes'] = dailyLimitMinutes;
    }

    final response = await _http.patch(
      _uri('/api/v1/children/$childId'),
      headers: await _buildHeaders(),
      body: jsonEncode(body),
    );
    if (response.statusCode != 200) {
      _throwFromResponse(response);
    }
    return ChildDto.fromJson(
      jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
    );
  }

  Future<void> deleteChild(String childId) async {
    final response = await _http.delete(
      _uri('/api/v1/children/$childId'),
      headers: await _buildHeaders(),
    );
    if (response.statusCode != 204 && response.statusCode != 200) {
      _throwFromResponse(response);
    }
  }

  // -------------------------------------------------------------------------
  // FR-04, FR-05, FR-10: Policy, Schedule & Allowed Apps Whitelist
  // -------------------------------------------------------------------------

  Future<PolicyDto> getPolicy(String childId) async {
    final response = await _http.get(
      _uri('/api/v1/policies/$childId'),
      headers: await _buildHeaders(),
    );
    if (response.statusCode != 200) {
      _throwFromResponse(response);
    }
    return PolicyDto.fromJson(
      jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
    );
  }

  Future<PolicyDto> updatePolicy({
    required String childId,
    required int dailyLimitMinutes,
    required int weekendBonusMinutes,
    required bool enforceWhitelist,
    required bool isInstantLocked,
    List<int> warningMinutes = const [15, 5, 1],
    List<ScheduleItemDto>? schedules,
    List<AllowedAppDto>? allowedApps,
  }) async {
    final payload = <String, dynamic>{
      'daily_limit_minutes': dailyLimitMinutes,
      'weekend_bonus_minutes': weekendBonusMinutes,
      'warning_minutes': warningMinutes,
      'enforce_whitelist': enforceWhitelist,
      'is_instant_locked': isInstantLocked,
    };
    if (schedules != null) {
      payload['schedules'] = schedules.map((s) => s.toJson()).toList();
    }
    if (allowedApps != null) {
      payload['allowed_apps'] = allowedApps.map((a) => a.toJson()).toList();
    }

    final response = await _http.put(
      _uri('/api/v1/policies/$childId'),
      headers: await _buildHeaders(),
      body: jsonEncode(payload),
    );
    if (response.statusCode != 200) {
      _throwFromResponse(response);
    }
    return PolicyDto.fromJson(
      jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
    );
  }

  // -------------------------------------------------------------------------
  // FR-03: Device Pairing Init / Claim / List / Unpair
  // -------------------------------------------------------------------------

  Future<DevicePairInitDto> initDevicePairing({
    required String hardwareUid,
    String deviceType = 'FAMILYSCREEN_BOX',
    String deviceName = 'FamilyScreen Box',
  }) async {
    final response = await _http.post(
      _uri('/api/v1/devices/pair/init'),
      headers: await _buildHeaders(authenticated: false),
      body: jsonEncode({
        'hardware_uid': hardwareUid,
        'device_type': deviceType,
        'device_name': deviceName,
      }),
    );
    if (response.statusCode != 201 && response.statusCode != 200) {
      _throwFromResponse(response);
    }
    return DevicePairInitDto.fromJson(
      jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
    );
  }

  Future<DeviceDto> claimDevicePairing({
    required String familyId,
    required String pairingCode,
    required String deviceName,
    String? activeChildId,
  }) async {
    final response = await _http.post(
      _uri('/api/v1/devices/pair/claim'),
      headers: await _buildHeaders(),
      body: jsonEncode({
        'family_id': familyId,
        'pairing_code': pairingCode.trim(),
        'device_name': deviceName.trim(),
        'active_child_id': activeChildId,
      }),
    );
    if (response.statusCode != 200) {
      _throwFromResponse(response);
    }
    return DeviceDto.fromJson(
      jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
    );
  }

  Future<List<DeviceDto>> listDevices(String familyId) async {
    final response = await _http.get(
      _uri('/api/v1/families/$familyId/devices'),
      headers: await _buildHeaders(),
    );
    if (response.statusCode != 200) {
      _throwFromResponse(response);
    }
    final list = jsonDecode(utf8.decode(response.bodyBytes)) as List<dynamic>;
    return list
        .map((e) => DeviceDto.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> unpairDevice(String deviceId) async {
    final response = await _http.delete(
      _uri('/api/v1/devices/$deviceId'),
      headers: await _buildHeaders(),
    );
    if (response.statusCode != 204 && response.statusCode != 200) {
      _throwFromResponse(response);
    }
  }

  // -------------------------------------------------------------------------
  // FR-07: Remote Override (+15 / +30 min) & PIN Management
  // -------------------------------------------------------------------------

  Future<TimeStateDto> grantRemoteOverride({
    required String familyId,
    required String childId,
    required int addedMinutes,
    String? deviceId,
    String reason = 'Эцэг эхийн гар утаснаас сунгав',
  }) async {
    final response = await _http.post(
      _uri('/api/v1/overrides'),
      headers: await _buildHeaders(),
      body: jsonEncode({
        'family_id': familyId,
        'child_id': childId,
        'device_id': deviceId,
        'source': 'REMOTE_APP',
        'added_minutes': addedMinutes,
        'reason': reason,
      }),
    );
    if (response.statusCode != 201 && response.statusCode != 200) {
      _throwFromResponse(response);
    }
    final data = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return TimeStateDto.fromJson(data['time_state'] as Map<String, dynamic>);
  }

  Future<String> initFamilyPin({
    required String familyId,
    required String newPin,
  }) async {
    final response = await _http.post(
      _uri('/api/v1/families/$familyId/pin/init'),
      headers: await _buildHeaders(),
      body: jsonEncode({
        'new_pin': newPin.trim(),
      }),
    );
    if (response.statusCode != 200) {
      _throwFromResponse(response);
    }
    final data = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return (data['message'] as String?) ?? 'PIN код амжилттай тохируулагдлаа.';
  }

  Future<String> updateFamilyPin({
    required String familyId,
    required String newPin,
    String? currentPin,
  }) async {
    final response = await _http.put(
      _uri('/api/v1/families/$familyId/pin'),
      headers: await _buildHeaders(),
      body: jsonEncode({
        'current_pin': currentPin,
        'new_pin': newPin.trim(),
      }),
    );
    if (response.statusCode != 200) {
      _throwFromResponse(response);
    }
    final data = jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    return (data['message'] as String?) ?? 'PIN код шинэчлэгдлээ.';
  }

  // -------------------------------------------------------------------------
  // FR-08: Usage Report
  // -------------------------------------------------------------------------

  Future<UsageReportDto> getUsageReport({
    required String familyId,
    required String childId,
    int days = 7,
  }) async {
    final response = await _http.get(
      _uri('/api/v1/reports/summary', {
        'family_id': familyId,
        'child_id': childId,
        'days': '$days',
      }),
      headers: await _buildHeaders(),
    );
    if (response.statusCode != 200) {
      _throwFromResponse(response);
    }
    return UsageReportDto.fromJson(
      jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>,
    );
  }
}
