# FamilyScreen — Документ 07: Supabase Auth Security Remediation & Production Verification Audit

**Огноо:** 2026-11-09  
**Branch:** `fix/supabase-auth-security`  
**Статус:** 100% Засварлагдсан, Бүх 17 тест PASS  
**Хамрах хүрээ:** Supabase JWKS Key Management, RS256/HS256 Algorithm Whitelisting, Claims Validation, JIT User/Family Provisioning, Cross-Family Access Security  

---

## 1. Илэрсэн Асуудлууд (Identified Security Vulnerabilities)

1. **RS256 түлхүүрийн төрлийн зөрчил (Key Mismatch)**:
   - Өмнөх кодонд RS256 болон HS256 алгоритмуудыг нэг ижил тэгш хэмт (symmetric) secret-ээр шалгаж байсан. Гэтэл RS256 нь тэгш хэмт secret биш, зөвхөн RSA Public Key / JWKS шаарддаг.
2. **Algorithm Confusion Attack эрсдэл**:
   - `algorithms=["HS256", "RS256"]` жагсаалтыг зөвшөөрөгдсөн түлхүүрийн төрлийг тусгаарлалгүй тавьснаар халдагч нийтийн түлхүүрийг HMAC нууц болгон ашиглаж хуурамч токен үүсгэх эрсдэлтэй байсан.
3. **Claim баталгаажуулалт дутуу байсан**:
   - `iss` (Issuer), `aud` (Audience: "authenticated"), `exp` (Хугацаа), `sub` (User UUID) зэрэг Supabase стандартын claim-үүдийг хатуу баталгаажуулах логик дутуу байсан.
4. **Supabase User / Family Provisioning дутуу байсан**:
   - Supabase Auth-аар шинээр нэвтэрсэн хэрэглэгч backend-ийн `/api/v1/auth/me` рүү анх удаа хандахад database дээр User болон Family бүртгэл байхгүй тул шууд HTTP 401 "Хэрэглэгч олдсонгүй" алдаа зааж гацдаг байсан.
5. **CI Workflow Trigger дутуу байсан**:
   - CI workflow нь зөвхөн `main, master` дээр ажиллахаар тохируулагдсан байсан тул `fix/**` салбаруудад автомат шалгалт эхлэхгүй байв.

---

## 2. Хэрэгжүүлсэн Шийдэл (Engineering Solutions)

### 2.1. Dynamic Supabase JWKS Manager ба Key Rotation (`SupabaseJwksManager`)
- `PyJWKSet` ашиглан Supabase-ийн нийтийн түлхүүрүүдийг (`${SUPABASE_URL}/auth/v1/.well-known/jwks.json`) татаж, санах ойд TTL-тэйгээр кэшлэдэг болгов.
- Хэрэв токен доторх `kid` нь кэш дотор байхгүй бол шууд нэг удаагийн автомат refresh хийж түлхүүрийн эргэлтийг (Key Rotation) алдаагүй дэмждэг болгов.
- Түлхүүр олдохгүй бол аюулгүйгээр HTTP 401 Unauthorized буцаана.
- Тестийн үед интернэт холболт шаардахгүйгээр in-memory JWKS inject хийх `set_test_jwks()` боломжийг бүрдүүлсэн.

### 2.2. Хатуу Алгоритм ба Claim Шалгалт (Algorithm Confusion Mitigation)
- Токеныг тайлахаас өмнө `jwt.get_unverified_header(token)`-оор шалгаж, зөвхөн сервер талд зөвшөөрөгдсөн `ALLOWED_SUPABASE_ALGORITHMS` (RS256, HS256)-д нийцэж буй эсэхийг шалгана.
- **RS256** үед: Зөвхөн RSA Public Key ашиглана.
- **HS256** үед: Зөвхөн тусгайлан тохируулсан `SUPABASE_JWT_SECRET`-ийг ашиглана. Тохируулаагүй үед HS256 шууд татгалзагдана.
- `aud="authenticated"`, `iss` (зөвхөн манай Supabase төсөл), `exp` (хугацаа дуусаагүй байх), `sub` (хэрэглэгчийн ID заавал байх)-ийг хатуу шалгана.

### 2.3. Just-In-Time (JIT) Auto-Provisioning & Sync Урсгал
- Хэрэглэгч Supabase-аар анх удаа орж ирэхэд `_provision_supabase_family()` функц автоматаар:
  1. `User` бүртгэлийг `id=sub`, `email`, `full_name`-тэйгээр үүсгэнэ.
  2. `Family` нэгжийг `plan_tier="FREE"`, дефолт PIN ("2580"), цагийн бүс ("Asia/Ulaanbaatar")-тайгаар үүсгэнэ.
  3. `FamilyMember` эзэмшигчийн (OWNER) эрхийг олгож database-д баталгаажуулна.
  4. Шинэ болон хуучин хэрэглэгч аль алинд нь `/api/v1/auth/me` саадгүй `AuthResponse` буцаана.
- Нэмэлтээр `POST /api/v1/auth/supabase/sync` endpoint нэмэгдэж, Flutter талаас гэр бүлийн нэр болон PIN-ийг эхний нэвтрэлтээр тохируулах боломжтой болсон.

### 2.4. Flutter Client Сайжруулалт
- `mobile_app/lib/config/env.dart`: `validateProductionSecurity()` функц нэмэгдэж, production горимд cleartext HTTP ашиглахыг хатуу хориглов.
- `mobile_app/lib/services/token_storage.dart`: `refreshToken` болон `expiresAtMs` талбаруудыг нэмж токены амьдралын мөчлөгийг удирдах боломжтой болгов.
- `mobile_app/lib/services/api_client.dart`: `syncSupabaseProfile()` функцийг нэмж Backend-тэй шууд холбов.

---

## 3. Өөрчилсөн Файлууд

1. [`backend/app/security.py`](file:///C:/Users/enhtv/Documents/tv%20control/backend/app/security.py) — `SupabaseJwksManager`, хатуу RS256/HS256 баталгаажуулалт, claims validation.
2. [`backend/app/schemas.py`](file:///C:/Users/enhtv/Documents/tv%20control/backend/app/schemas.py) — `SupabaseSyncRequest` schema.
3. [`backend/app/main.py`](file:///C:/Users/enhtv/Documents/tv%20control/backend/app/main.py) — JIT Provisioning, `/auth/me` сайжруулалт, `POST /auth/supabase/sync` endpoint.
4. [`backend/tests/test_supabase_auth_security.py`](file:///C:/Users/enhtv/Documents/tv%20control/backend/tests/test_supabase_auth_security.py) — Шаардлагатай 12 багц аюулгүй байдлын автомат тест.
5. [`backend/tests/test_familyscreen.py`](file:///C:/Users/enhtv/Documents/tv%20control/backend/tests/test_familyscreen.py) — Регрессийн 5 багц тест.
6. [`mobile_app/lib/config/env.dart`](file:///C:/Users/enhtv/Documents/tv%20control/mobile_app/lib/config/env.dart) — Production HTTPS шалгалт.
7. [`mobile_app/lib/services/token_storage.dart`](file:///C:/Users/enhtv/Documents/tv%20control/mobile_app/lib/services/token_storage.dart) — Token refresh болон session өргөтгөл.
8. [`mobile_app/lib/services/api_client.dart`](file:///C:/Users/enhtv/Documents/tv%20control/mobile_app/lib/services/api_client.dart) — `syncSupabaseProfile` дэмжлэг.
9. [`.github/workflows/backend_ci.yml`](file:///C:/Users/enhtv/Documents/tv%20control/.github/workflows/backend_ci.yml) — `fix/**` дээр ажиллах, 17 тестийг бүрэн ажиллуулах тохиргоо.
10. [`.github/workflows/android_tv_box.yml`](file:///C:/Users/enhtv/Documents/tv%20control/.github/workflows/android_tv_box.yml) — `fix/**` дээр ажиллах тохиргоо.

---

## 4. Заавал Хийх 12 Тестийн Бодит Үр Дүн (100% PASS)

```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.2.0, pluggy-1.7.0
rootdir: C:\Users\enhtv\Documents\tv control
collected 17 items

backend/tests/test_familyscreen.py::test_time_engine_prd_example_transitions PASSED      [  5%]
backend/tests/test_familyscreen.py::test_full_mvp_end_to_end_journey PASSED              [ 11%]
backend/tests/test_familyscreen.py::test_authentication_and_cross_family_isolation PASSED [ 17%]
backend/tests/test_familyscreen.py::test_tv_box_pairing_token_offline_sync_policy_and_instant_lock PASSED [ 23%]
backend/tests/test_familyscreen.py::test_supabase_jwt_auth_and_security_production_checks PASSED [ 29%]

backend/tests/test_supabase_auth_security.py::test_01_valid_rs256_jwt_pass PASSED        [ 35%]
backend/tests/test_supabase_auth_security.py::test_02_valid_hs256_jwt_pass_when_configured PASSED [ 41%]
backend/tests/test_supabase_auth_security.py::test_03_invalid_signature_reject PASSED   [ 47%]
backend/tests/test_supabase_auth_security.py::test_04_expired_jwt_reject PASSED          [ 52%]
backend/tests/test_supabase_auth_security.py::test_05_wrong_issuer_reject PASSED          [ 58%]
backend/tests/test_supabase_auth_security.py::test_06_wrong_audience_reject PASSED        [ 64%]
backend/tests/test_supabase_auth_security.py::test_07_different_supabase_project_token_reject PASSED [ 70%]
backend/tests/test_supabase_auth_security.py::test_08_jwks_key_not_found_safe_reject PASSED [ 76%]
backend/tests/test_supabase_auth_security.py::test_09_jwks_key_rotation_handled_properly PASSED [ 82%]
backend/tests/test_supabase_auth_security.py::test_10_cross_family_access_supabase_reject PASSED [ 88%]
backend/tests/test_supabase_auth_security.py::test_11_supabase_user_jit_provisioning PASSED [ 94%]
backend/tests/test_supabase_auth_security.py::test_12_custom_authentication_regression PASSED [100%]

======================== 17 passed, 1 warning in 2.82s ========================
```

---

## 5. Production Орчинд Шаардлагатай Environment Variables

Production deployment хийхэд дараах хувьсагчдыг серверийн `.env` эсвэл Cloud Run/Docker орчинд тохируулна:

| Хувьсагч | Жишээ утга | Шаардлага | Тайлбар |
|---|---|---|---|
| `ENVIRONMENT` | `production` | Заавал | Production strict аюулгүй байдлыг идэвхжүүлнэ |
| `FAMILYSCREEN_SECRET_KEY` | `min-32-chars-cryptographic-random-secret` | Заавал | Backend-ийн дотоод HMAC токен ба төхөөрөмжийн баталгаажуулалт |
| `FAMILYSCREEN_DATABASE_URL` | `postgresql://user:pass@host:5432/db` | Заавал | Production PostgreSQL өгөгдлийн сангийн холболт |
| `SUPABASE_URL` | `https://your-project.supabase.co` | Заавал (хэрэв Supabase ашиглах бол) | Supabase төслийн URL |
| `SUPABASE_JWKS_URL` | `https://your-project.supabase.co/auth/v1/.well-known/jwks.json` | Сонголттой | Дефолтоор `${SUPABASE_URL}/auth/v1/.well-known/jwks.json` байна |
| `SUPABASE_JWT_ISSUER` | `https://your-project.supabase.co/auth/v1` | Сонголттой | Бусад Supabase project-ийн токеныг хориглоно |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` | Сонголттой | Supabase-ийн хэрэглэгчийн баталгаат эрх |
| `SUPABASE_JWT_SECRET` | `your-supabase-jwt-secret` | Сонголттой (хэрэв HS256 ашиглах бол) | Supabase Dashboard > Settings > API > JWT Secret |
| `FAMILYSCREEN_ALLOWED_ORIGINS` | `https://app.familyscreen.mn,https://familyscreen.mn` | Заавал | CORS зөвшөөрөгдсөн production домэйнууд |

---

## 6. Үлдсэн Эрсдэл ба Зөвлөмж

1. **Supabase Realtime Subscriptions**:
   Одоогоор HTTP REST API-ийн JWT баталгаажуулалт ба JIT provisioning бүрэн шийдэгдсэн. Ирээдүйд WebSocket/Realtime Push хийх үед Supabase Realtime channel эсвэл FastAPI WebSockets-ийн аль нэгийг нэгтгэн сонгох.
2. **Android TV Hardware Testing**:
   Бодит Android TV Box дээр APK суулган D-Pad удирдлага, оффлайн 72 цагийн тааз, болон ТВ асаах үеийн foreground service-ийг бодит төхөөрөмж дээр шалгах шаардлагатай.
