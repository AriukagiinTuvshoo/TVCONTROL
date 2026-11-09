// Secure session & token storage abstraction for FamilyScreen Parent App.
// Supports in-memory persistence out of the box and can be backed by
// Keychain / EncryptedSharedPreferences in native builds.

class AuthSessionData {
  const AuthSessionData({
    required this.accessToken,
    required this.userId,
    required this.userEmail,
    required this.userFullName,
    required this.familyId,
    required this.familyName,
    required this.planTier,
    this.refreshToken,
    this.expiresAtMs,
  });

  final String accessToken;
  final String userId;
  final String userEmail;
  final String userFullName;
  final String familyId;
  final String familyName;
  final String planTier;
  final String? refreshToken;
  final int? expiresAtMs;

  bool get isExpired {
    if (expiresAtMs == null) return false;
    return DateTime.now().millisecondsSinceEpoch >= expiresAtMs!;
  }
}

abstract class TokenStorage {
  Future<void> saveSession(AuthSessionData session);
  Future<AuthSessionData?> readSession();
  Future<void> clearSession();
}

class SecureMemoryTokenStorage implements TokenStorage {
  AuthSessionData? _cached;

  @override
  Future<void> saveSession(AuthSessionData session) async {
    _cached = session;
  }

  @override
  Future<AuthSessionData?> readSession() async {
    return _cached;
  }

  @override
  Future<void> clearSession() async {
    _cached = null;
  }
}
