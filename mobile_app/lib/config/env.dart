// Environment configuration for FamilyScreen Parent App.
// Can be overridden via: flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000

class AppEnv {
  const AppEnv._();

  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );
}
