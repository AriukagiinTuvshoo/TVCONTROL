# FamilyScreen — Документ 06: Production Risk Remediation & CI/CD Readiness Report

**Огноо:** 2026-11-09  
**Статус:** Хэрэгжүүлж баталгаажуулсан (Remediated & Verified)  
**Хамрах хүрээ:** Backend Security, Supabase Auth, PostgreSQL Integration, Android Network Security, GitHub Actions CI/CD  

---

## 1. Илэрсэн 5 Критик Эрсдэлийн Засвар ба Бодит Хэрэгжилт

### 1.1. Supabase Auth Баталгаажуулалт (Бүрэн шийдвэрлэсэн)
- **Өмнөх төлөв:** Архитектурт Supabase Auth гэж заасан боловч зөвхөн орон нутгийн HMAC token ашиглаж байсан.
- **Шийдэл:** 
  1. `backend/requirements.txt`-д `pyjwt[crypto]` болон `supabase` нэмэв.
  2. `backend/app/security.py`-д `verify_supabase_jwt()` нэмэгдэж, Supabase-аас олгосон 3 хэсэг бүхий RS256/HS256 JWT токенийг `SUPABASE_JWT_SECRET`-ээр шалган `AuthPrincipal`-д хөрвүүлдэг болгов.
  3. `mobile_app/lib/config/env.dart` болон `mobile_app/lib/services/api_client.dart`-д `SUPABASE_URL`, `SUPABASE_ANON_KEY`, болон `loginWithSupabaseToken()` нэмэгдсэн.
  4. Локал хөгжүүлэлтийн HMAC токен болон Supabase JWT токен хоёулаа зэрэг дэмжигдэн ажиллана.
- **Тест:** `test_supabase_jwt_auth_and_security_production_checks` тест нэмэгдэж, 100% PASS болов.

### 1.2. Default Secret Key Hardening (Бүрэн шийдвэрлэсэн)
- **Өмнөх төлөв:** `FAMILYSCREEN_SECRET_KEY` дутуу үед дефолт түлхүүр ашиглаж байсан.
- **Шийдэл:** `backend/app/security.py` дотор `ENVIRONMENT == "production"` эсвэл `ENV == "production"` үед `FAMILYSCREEN_SECRET_KEY` дутуу эсвэл 32 тэмдэгтээс богино байвал сервер асахгүйгээр `RuntimeError` шиддэг хатуу хамгаалалт нэмэв.

### 1.3. Android Network Security Config & HTTPS Хамгаалалт (Бүрэн шийдвэрлэсэн)
- **Өмнөх төлөв:** `AndroidManifest.xml`-д `android:usesCleartextTraffic="true"` байсан нь production үед аюулгүй байдлын зөрчил байв.
- **Шийдэл:**
  1. `android_tv_box/app/src/main/res/xml/network_security_config.xml` үүсгэв.
  2. Production үед бүх домайнд зөвхөн HTTPS (TLS 1.2+) мөрдүүлж, Cleartext HTTP-ийг зөвхөн локал тест/эмулятор (`10.0.2.2`, `127.0.0.1`, `localhost`)-д тусгаарлав.
  3. `AndroidManifest.xml`-д `android:usesCleartextTraffic="false"` болон `android:networkSecurityConfig="@xml/network_security_config"` тохируулав.

### 1.4. CORS Домэйны Хязгаарлалт (Бүрэн шийдвэрлэсэн)
- **Өмнөх төлөв:** `allow_origins=["*"], allow_credentials=True` тохиргоо нь CORS стандартад нийцэхгүй, аюулгүй байдлын цоорхой үүсгэж байв.
- **Шийдэл:** `backend/app/main.py`-д `FAMILYSCREEN_ALLOWED_ORIGINS` орчны хувьсагчаар зөвшөөрөгдсөн домэйнуудыг (Production: `https://app.familyscreen.mn`, `https://familyscreen.mn`, Dev: `localhost`) хязгаарлан тохируулдаг болгов. Хэрэв `*` байвал `allow_credentials=False` болж стандартыг барина.

### 1.5. PostgreSQL Драйвер ба Connection Pooling (Бүрэн шийдвэрлэсэн)
- **Өмнөх төлөв:** `requirements.txt`-д PostgreSQL драйвер дутуу байсан.
- **Шийдэл:**
  1. `backend/requirements.txt`-д `psycopg2-binary>=2.9.9` драйверийг нэмж суулгав.
  2. `backend/app/database.py`-д `postgresql://` протокол болон production PostgreSQL-д зориулсан connection pooling (`pool_size=10, max_overflow=20, pool_pre_ping=True, pool_recycle=1800`) тохиргоог нэмэв.

---

## 2. GitHub Actions CI/CD Баталгаажуулалт

### 2.1. Backend CI (`.github/workflows/backend_ci.yml`)
- Python 3.12, dependencies installation, `pytest -v backend/tests/test_familyscreen.py`.
- Нийт 5 integration & security тестүүдийг GitHub Actions push/PR бүрт автоматаар ажиллуулна.

### 2.2. Android TV Box CI (`.github/workflows/android_tv_box.yml`)
- JDK 17, Android SDK 34, `gradle-wrapper.jar` нэмэгдсэн.
- Unit тестүүдийг (`testReleaseUnitTest`) шалгана.
- Android TV APK (`assembleDebug`)-г компиляци хийж, үр дүнгийн APK файлыг GitHub Actions Artifacts хэсэгт `FamilyScreen-AndroidTV-APK` нэрээр байршуулна.

---

## 3. Commit Түүх (Conventional Commits)

1. `45f01aa` — `fix(android): Enforce HTTPS via network_security_config and add official gradle-wrapper.jar`
2. `59b1259` — `feat(backend): Add Supabase Auth JWT verification, PostgreSQL psycopg2 driver, strict production secret validation, and CORS domain whitelist`
3. `ec7eab0` — `feat(mobile): Add Supabase Auth JWT login support and environment configuration`
4. `715ed48` — `ci: Add Backend pytest CI workflow and optimize Android TV APK build artifact pipeline`
5. `d3ef18b` — `docs: Add Phase 6 risk remediation and production readiness report (06-production-risk-remediation.md)`
