// Flutter widget & API client integration tests for FamilyScreen Parent App.

import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:familyscreen_parent/main.dart';
import 'package:familyscreen_parent/services/api_client.dart';
import 'package:familyscreen_parent/services/token_storage.dart';

void main() {
  testWidgets(
    'Parent login, child dashboard load, and remote +15m override flow',
    (WidgetTester tester) async {
      int overrideMinutes = 0;

      final mockHttp = MockClient((http.Request request) async {
        final path = request.url.path;

        if (path == '/api/v1/auth/login' && request.method == 'POST') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'access_token': 'test-token-123',
                'token_type': 'bearer',
                'user': {
                  'id': 'u-1',
                  'email': 'parent@familyscreen.mn',
                  'full_name': 'Сарангэрэл',
                },
                'family': {
                  'id': 'f-1',
                  'name': 'Сарангэрэлийн гэр бүл',
                  'timezone': 'Asia/Ulaanbaatar',
                  'plan_tier': 'FREE',
                  'pin_configured': true,
                },
              }),
            ),
            200,
          );
        }

        if (path == '/api/v1/families/f-1/children' &&
            request.method == 'GET') {
          final allowedSec = (60 + overrideMinutes) * 60;
          return http.Response.bytes(
            utf8.encode(
              jsonEncode([
                {
                  'id': 'c-1',
                  'family_id': 'f-1',
                  'nickname': 'Тэмүүлэн',
                  'age_group': '7-9',
                  'avatar_key': 'fox',
                  'is_active': true,
                  'policy_id': 'p-1',
                  'daily_limit_minutes': 60,
                  'is_instant_locked': false,
                  'time_state': {
                    'state': 'ALLOW',
                    'reason': 'WITHIN_LIMIT_AND_SCHEDULE',
                    'local_date': '2026-11-08',
                    'local_time_str': '15:00:00',
                    'allowed_seconds_today': allowedSec,
                    'used_seconds_today': 0,
                    'override_seconds_today': overrideMinutes * 60,
                    'remaining_seconds_today': allowedSec,
                    'effective_remaining_seconds': allowedSec,
                  },
                }
              ]),
            ),
            200,
          );
        }

        if (path == '/api/v1/families/f-1/devices' && request.method == 'GET') {
          return http.Response.bytes(utf8.encode(jsonEncode([])), 200);
        }

        if (path == '/api/v1/policies/c-1' && request.method == 'GET') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'id': 'p-1',
                'family_id': 'f-1',
                'child_id': 'c-1',
                'daily_limit_minutes': 60,
                'weekend_bonus_minutes': 0,
                'warning_minutes': [15, 5, 1],
                'enforce_whitelist': true,
                'is_instant_locked': false,
                'version': 1,
                'schedules': [],
                'allowed_apps': [],
              }),
            ),
            200,
          );
        }

        if (path == '/api/v1/reports/summary' && request.method == 'GET') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'family_id': 'f-1',
                'child_id': 'c-1',
                'child_nickname': 'Тэмүүлэн',
                'days': 7,
                'total_used_minutes': 0,
                'daily_items': [],
                'app_breakdown': [],
              }),
            ),
            200,
          );
        }

        if (path == '/api/v1/overrides' && request.method == 'POST') {
          overrideMinutes += 15;
          final allowedSec = (60 + overrideMinutes) * 60;
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'override_id': 'ov-1',
                'added_minutes': 15,
                'time_state': {
                  'state': 'ALLOW',
                  'reason': 'WITHIN_LIMIT_AND_SCHEDULE',
                  'local_date': '2026-11-08',
                  'local_time_str': '15:05:00',
                  'allowed_seconds_today': allowedSec,
                  'used_seconds_today': 0,
                  'override_seconds_today': overrideMinutes * 60,
                  'remaining_seconds_today': allowedSec,
                  'effective_remaining_seconds': allowedSec,
                },
              }),
            ),
            201,
          );
        }

        return http.Response('Not Found', 404);
      });

      final apiClient = FamilyScreenApiClient(
        httpClient: mockHttp,
        tokenStorage: SecureMemoryTokenStorage(),
        baseUrl: 'http://127.0.0.1:8000',
      );

      await tester.pumpWidget(FamilyScreenParentApp(apiClient: apiClient));
      await tester.pumpAndSettle();

      // Verify Login screen is shown initially
      expect(find.byKey(const Key('auth_email_field')), findsOneWidget);

      await tester.enterText(
        find.byKey(const Key('auth_email_field')),
        'parent@familyscreen.mn',
      );
      await tester.enterText(
        find.byKey(const Key('auth_password_field')),
        'SafePass123!',
      );
      await tester.tap(find.byKey(const Key('auth_submit_button')));
      await tester.pumpAndSettle();

      // Verify child dashboard loaded with 60 remaining minutes
      expect(find.text('60'), findsOneWidget);

      // Tap +15m remote override button
      await tester.tap(find.byKey(const Key('override_15_button')));
      await tester.pumpAndSettle();

      // Verify remaining minutes updated to 75
      expect(find.text('75'), findsOneWidget);
    },
  );

  testWidgets(
    'New family onboarding: unconfigured PIN routes to PinSetupScreen, initializes PIN, and unlocks dashboard',
    (WidgetTester tester) async {
      bool pinInitCalled = false;

      final mockHttp = MockClient((http.Request request) async {
        final path = request.url.path;

        if (path == '/api/v1/auth/login' && request.method == 'POST') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'access_token': 'new-parent-token',
                'token_type': 'bearer',
                'user': {
                  'id': 'u-new',
                  'email': 'new_parent@familyscreen.mn',
                  'full_name': 'Шинэ Эцэг',
                },
                'family': {
                  'id': 'f-new',
                  'name': 'Шинэ гэр бүл',
                  'timezone': 'Asia/Ulaanbaatar',
                  'plan_tier': 'FREE',
                  'pin_configured': false,
                },
              }),
            ),
            200,
          );
        }

        if (path == '/api/v1/families/f-new/pin/init' && request.method == 'POST') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          if (body['new_pin'] == '5678') {
            pinInitCalled = true;
            return http.Response.bytes(
              utf8.encode(
                jsonEncode({
                  'family_id': 'f-new',
                  'message': 'Эцэг эхийн PIN код амжилттай тохируулагдлаа.',
                }),
              ),
              200,
            );
          }
          return http.Response('Invalid PIN', 400);
        }

        if (path == '/api/v1/families/f-new/children' && request.method == 'GET') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode([
                {
                  'id': 'c-new',
                  'family_id': 'f-new',
                  'nickname': 'Энэрэл',
                  'age_group': '7-9',
                  'avatar_key': 'fox',
                  'is_active': true,
                  'policy_id': 'p-new',
                  'daily_limit_minutes': 90,
                  'is_instant_locked': false,
                  'time_state': {
                    'state': 'ALLOW',
                    'reason': 'WITHIN_LIMIT_AND_SCHEDULE',
                    'local_date': '2026-11-09',
                    'local_time_str': '10:00:00',
                    'allowed_seconds_today': 5400,
                    'used_seconds_today': 0,
                    'override_seconds_today': 0,
                    'remaining_seconds_today': 5400,
                    'effective_remaining_seconds': 5400,
                  },
                }
              ]),
            ),
            200,
          );
        }

        if (path == '/api/v1/families/f-new/devices' && request.method == 'GET') {
          return http.Response.bytes(utf8.encode(jsonEncode([])), 200);
        }

        if (path == '/api/v1/policies/c-new' && request.method == 'GET') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'id': 'p-new',
                'family_id': 'f-new',
                'child_id': 'c-new',
                'daily_limit_minutes': 90,
                'weekend_bonus_minutes': 0,
                'warning_minutes': [15, 5, 1],
                'enforce_whitelist': true,
                'is_instant_locked': false,
                'version': 1,
                'schedules': [],
                'allowed_apps': [],
              }),
            ),
            200,
          );
        }

        if (path == '/api/v1/reports/summary' && request.method == 'GET') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'family_id': 'f-new',
                'child_id': 'c-new',
                'child_nickname': 'Энэрэл',
                'days': 7,
                'total_used_minutes': 0,
                'daily_items': [],
                'app_breakdown': [],
              }),
            ),
            200,
          );
        }

        return http.Response('Not Found', 404);
      });

      final apiClient = FamilyScreenApiClient(
        httpClient: mockHttp,
        tokenStorage: SecureMemoryTokenStorage(),
        baseUrl: 'http://127.0.0.1:8000',
      );

      await tester.pumpWidget(FamilyScreenParentApp(apiClient: apiClient));
      await tester.pumpAndSettle();

      // 1. Log in
      await tester.enterText(
        find.byKey(const Key('auth_email_field')),
        'new_parent@familyscreen.mn',
      );
      await tester.enterText(
        find.byKey(const Key('auth_password_field')),
        'Secret123!',
      );
      await tester.tap(find.byKey(const Key('auth_submit_button')));
      await tester.pumpAndSettle();

      // 2. Verify routed directly to PinSetupScreen because pin_configured == false
      expect(find.byKey(const Key('pin_setup_input')), findsOneWidget);
      expect(find.byKey(const Key('pin_setup_confirm_input')), findsOneWidget);
      expect(find.text('Эцэг эхийн PIN код үүсгэх'), findsOneWidget);

      // 3. Test validation: mismatching PINs
      await tester.enterText(find.byKey(const Key('pin_setup_input')), '5678');
      await tester.enterText(find.byKey(const Key('pin_setup_confirm_input')), '9999');
      await tester.tap(find.byKey(const Key('pin_setup_submit_button')));
      await tester.pumpAndSettle();
      expect(find.text('Оруулсан PIN кодууд хоорондоо таарахгүй байна.'), findsOneWidget);
      expect(pinInitCalled, isFalse);

      // 4. Test validation: matching valid PIN
      await tester.enterText(find.byKey(const Key('pin_setup_confirm_input')), '5678');
      await tester.tap(find.byKey(const Key('pin_setup_submit_button')));
      await tester.pumpAndSettle();

      // 5. Verify /pin/init was called, session updated, and dashboard unlocked
      expect(pinInitCalled, isTrue);
      expect(find.text('90'), findsOneWidget);
      expect(find.text('Энэрэл'), findsOneWidget);
    },
  );
}
