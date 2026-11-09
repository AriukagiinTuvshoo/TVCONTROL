// Environment configuration for FamilyScreen Parent App.
// Can be overridden via:
// flutter run --dart-define=API_BASE_URL=https://api.familyscreen.mn --dart-define=SUPABASE_URL=https://xyz.supabase.co --dart-define=SUPABASE_ANON_KEY=public-anon-key

import 'package:flutter/foundation.dart';

class AppEnv {
  const AppEnv._();

  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  static const String supabaseUrl = String.fromEnvironment(
    'SUPABASE_URL',
    defaultValue: '',
  );

  static const String supabaseAnonKey = String.fromEnvironment(
    'SUPABASE_ANON_KEY',
    defaultValue: '',
  );

  static bool get isSupabaseConfigured =>
      supabaseUrl.isNotEmpty && supabaseAnonKey.isNotEmpty;

  /// In production release mode, enforces HTTPS for all remote endpoints to prevent cleartext exposure
  static void validateProductionSecurity() {
    if (kReleaseMode) {
      final isLocalhost = apiBaseUrl.contains('10.0.2.2') ||
          apiBaseUrl.contains('127.0.0.1') ||
          apiBaseUrl.contains('localhost');
      if (apiBaseUrl.startsWith('http://') && !isLocalhost) {
        throw StateError(
          'CRITICAL SECURITY ERROR: Production builds must strictly use HTTPS for API_BASE_URL: $apiBaseUrl',
        );
      }
      if (supabaseUrl.isNotEmpty && supabaseUrl.startsWith('http://')) {
        throw StateError(
          'CRITICAL SECURITY ERROR: Production builds must strictly use HTTPS for SUPABASE_URL: $supabaseUrl',
        );
      }
    }
  }
}
