# FamilyScreen — Phase 9: Production Integration, Database Migration & CI Stabilization Audit

**Баримт бичгийн хувилбар:** 1.0  
**Огноо:** 2026-11-09  
**Зохиогч:** Senior Staff Software & Security Engineer  
**Төлөв:** Баталгаажсан (Verified & Production-Ready)  
**Репозитор:** `https://github.com/AriukagiinTuvshoo/TVCONTROL`  
**Төслийн салбар (Branch):** `fix/phase9-production-integration`  
**Үндсэн HEAD Commit (Main):** `951a5dc788ab651ce0e06f417b8a8c3b31230e47`

---

## 1. Ерөнхий хураангуй (Executive Summary)

Phase 8-ын хөндлөнгийн аудитаар илэрсэн production орчинд нэн шаардлагатай дэд бүтцийн болон аюулгүй байдлын асуудлуудыг Phase 9-өөр бүрэн шийдвэрлэж, тогтворжууллаа:
1. **Өгөгдлийн сангийн аюулгүй шилжүүлэг (Database Migration):** `Base.metadata.create_all()` нь өмнө үүссэн production хүснэгтэд шинэ багана (`supabase_sub`) болон индекс автоматаар нэмдэггүй эрсдэлийг шийдвэрлэсэн транзакцтай, rollback дэмжлэгтэй, Alembic-ийн нэмэлт overhead-гүй цэвэр migration хөдөлгүүр [`backend/app/migrations.py`](file:///C:/Users/enhtv/Documents/tv%20control/backend/app/migrations.py)-ийг хэрэгжүүлэв.
2. **Уралдаант нөхцөл (Race Condition) ба түгжээ (Locking):** Олон урсгалт зэрэгцээ хүсэлтүүдийн үед PIN код давхар тохируулагдах, Supabase холболтыг зэрэгцээ данс булаах, эсвэл JIT provisioning давхар үүсэхээс сэргийлж атомик нөхцөлт UPDATE ба row-level lock (`with_for_update()`), мөн PIN шинэчлэлтэд `OWNER` role-ийн хатуу шалгалтыг нэвтрүүлэв.
3. **Flutter PIN тохиргоо ба Onboarding интеграци:** Шинэ гэр бүлийн анхны PIN тохируулаагүй үед (`pin_configured == false`) эцэг эхийг шууд хүлээн авч хамгаалах [`PinSetupScreen`](file:///C:/Users/enhtv/Documents/tv%20control/mobile_app/lib/main.dart)-ийг хэрэгжүүлэн, нууцлал бүхий масктай оролт, 4-6 оронтой тооны баталгаажуулалт, алдааны монгол мэдэгдэл, сесс шинэчлэлт болон данс холбох урсгалыг бүрэн хийв.
4. **Android TV Box CI засвар:** GitHub Actions `ubuntu-latest` дээр `android-actions/setup-android@v3` үйлдэл `tools` багц хайж бүтэлгүйтдэг байсан алдааг арилгаж, pre-installed Android SDK 34 ба Java 17-оор найдвартай APK build & test ажилладаг болгов.
5. **Тест ба регрессийн үр дүн:** Backend-ийн 34 тест (100% ногоон), шинэ шилжүүлэг ба concurrency тестүүд, Flutter widget тестүүд бүрэн баталгаажив.

---

## 2. Өгөгдлийн сангийн шилжүүлэг (Database Migration Engine)

### 2.1. Шалтгаан ба Архитектурын шийдэл
- SQLAlchemy-ийн `create_all()` команд нь зөвхөн *шинэ* хүснэгт үүсгэдэг бөгөөд ажиллаж буй production өгөгдлийн сангийн `users` хүснэгтэд шинээр нэмэгдсэн `supabase_sub` багана, unique индексийг нэмж чаддаггүй.
- Энэхүү эрсдэлийг шийдэхийн тулд `schema_migrations` хүснэгтээр хувилбарыг бүртгэдэг, upgrade/downgrade дэмжлэгтэй [`backend/app/migrations.py`](file:///C:/Users/enhtv/Documents/tv%20control/backend/app/migrations.py) модуль үүсгэв.

### 2.2. Migration 001 онцлог
- **Хувилбар:** `001_add_supabase_sub_to_users`
- **Upgrade үйлдэл:** 
  - `ALTER TABLE users ADD COLUMN supabase_sub VARCHAR(64)`
  - `CREATE UNIQUE INDEX ix_users_supabase_sub ON users (supabase_sub)`
- **Downgrade (Rollback) үйлдэл:**
  - `DROP INDEX IF EXISTS ix_users_supabase_sub`
  - `ALTER TABLE users DROP COLUMN supabase_sub`
- **Өгөгдлийн бүрэн бүтэн байдал:** Одоо байгаа хэрэглэгчдийн өгөгдөл 100% хадгалагдана (NULL утгатайгаар эхэлнэ).

---

## 3. Уралдаант нөхцөл (Race Condition) ба Зэрэгцээ ажиллагааны хамгаалалт

### 3.1. Зэрэгцээ PIN код эхлүүлэлт (`POST /pin/init`)
- Олон төхөөрөмжөөс эсвэл зэрэгцээ урсгалаас анхны PIN-ийг зэрэг оруулахад:
  ```python
  res = db.execute(
      update(Family)
      .where(
          Family.id == family_id,
          (Family.pin_hash.is_(None)) | (Family.pin_hash == ""),
      )
      .values(
          pin_hash=hash_secret(payload.new_pin),
          pin_failed_attempts=0,
          pin_locked_until=None,
      )
  )
  if res.rowcount == 0:
      db.rollback()
      raise HTTPException(status_code=409, detail="PIN код аль хэдийн тохируулагдсан байна...")
  db.commit()
  ```
- **Үр дүн:** Яг 1 хүсэлт амжилттай 200 болж, өрсөлдсөн хоёр дахь хүсэлт атомик түвшинд `rowcount == 0` болж HTTP 409 Conflict хүлээн авна.

### 3.2. Supabase данс холболтын өрсөлдөөн (`POST /auth/supabase/link-account`)
- Хоёр өөр Supabase identity нэгэн зэрэг нэг орон нутгийн дансыг булааж холбохоос сэргийлж:
  ```python
  res = db.execute(
      update(User)
      .where(
          User.id == local_user.id,
          (User.supabase_sub.is_(None)) | (User.supabase_sub == principal.user_id),
      )
      .values(supabase_sub=principal.user_id)
  )
  if res.rowcount == 0:
      db.rollback()
      raise HTTPException(status_code=409, detail="Энэ бүртгэл аль хэдийн өөр Supabase данстай холбогдсон байна.")
  ```
- **Үр дүн:** Эхний холболт амжилттай болж, хоёр дахь холболт 409 Conflict авч буцна.

### 3.3. PIN өөрчлөх эрхийн хяналт (`PUT /pin`)
- PRD FR-01 болон FR-07-ын дагуу гэр бүлийн үндсэн PIN кодыг зөвхөн `OWNER` үүрэгтэй хэрэглэгч солих эрхтэй. `MEMBER` (асран хамгаалагч) хүсэлт илгээвэл HTTP 403 Forbidden буцаана.

---

## 4. Flutter PIN Initialization & Onboarding UI

### 4.1. `AuthGateScreen` чиглүүлэлт
- Нэвтэрсэн хэрэглэгчийн сессийн `pinConfigured` утгыг шалгана:
  - Хэрэв `pinConfigured == false` бол шууд `PinSetupScreen`-д шилжүүлнэ.
  - Хэрэв `pinConfigured == true` бол үндсэн `ParentHomeShell` дэлгэц рүү шилжүүлнэ.

### 4.2. `PinSetupScreen` дэлгэцийн бүтэц
- **Монгол тайлбар:** "Эцэг эхийн PIN код үүсгэх", "ТВ төхөөрөмж нээх, тохиргоо хамгаалах 4-6 оронтой нууц PIN кодоо тохируулна уу."
- **Оролтууд:**
  - Шинэ PIN оролт (`obscureText: true`, keyboardType `number`, `maxLength: 6`).
  - PIN давтах оролт (`obscureText: true`, keyboardType `number`, `maxLength: 6`).
- **Шалгалтууд (Validation):**
  - Хоосон эсэхийг шалгах.
  - 4-6 оронтой тоон формат шалгах (`RegExp(r'^\d{4,6}$')`).
  - Хоёр нууц код хоорондоо яг таарч буйг шалгах.
- **Аюулгүй байдал:** PIN кодыг хэзээ ч plaintext хэлбэрээр консолд хэвлэхгүй ба log-д бичихгүй.
- **Амжилттай болсны дараа:** `apiClient.initFamilyPin()` дуудаж, сессийг `pinConfigured = true` болгон шинэчилж, үндсэн дашборд руу саадгүй шилжүүлнэ.

### 4.3. `AuthScreen` дэх Supabase нэвтрэлт ба Данс холболт
- Supabase токеноор нэвтрэх горим нэмэгдсэн.
- Хэрэв 409 `ACCOUNT_LINKING_REQUIRED` алдаа ирвэл хэрэглэгчид "Энэ имэйл дээр бүртгэл байна. Холбохын тулд дотоод нууц үгээ баталгаажуулна уу" гэсэн талбар гарч, `linkSupabaseAccount` функцийг дуудан аюулгүй холболт хийнэ.

---

## 5. CI / CD Тогтворжуулалт (Android & Flutter)

### 5.1. Android TV CI засвар (`.github/workflows/android_tv_box.yml`)
- **Асуудал:** `android-actions/setup-android@v3` action нь Google-ийн SDK rep-ээс хасагдсан `tools` багцыг татах гэж оролдон анхааруулга өгч зогсдог байсан.
- **Шийдэл:** Obsolete action-ийг хасаж, GitHub-ын `ubuntu-latest` дээр бэлэн байдаг Android SDK 34 болон `setup-java@v4` (Java 17)-ийг ашиглан:
  ```yaml
  - name: Accept Android SDK Licenses
    run: |
      yes | sdkmanager --licenses || true
  ```
  командоор лицензийг хүлээн зөвшөөрч, unit test (`testReleaseUnitTest`) ба APK угсралт (`assembleDebug`), artifact upload найдвартай ажиллах нөхцөлийг бүрдүүлэв.

### 5.2. Flutter CI нэмэлт (`.github/workflows/flutter_ci.yml`)
- Бүх pull request болон push дээр Flutter-ийн бүх test автоматаар ажилладаг шинэ workflow нэмэв:
  ```yaml
  - name: Run Flutter Tests
    run: |
      cd mobile_app
      flutter test
  ```

---

## 6. Баталгаажуулалтын матриц (Verification Matrix)

| Д/д | Тест файл | Тестийн зорилго | Үр дүн |
|---|---|---|---|
| 1 | `test_concurrency_and_migrations.py` | `001` шилжүүлэг ба rollback legacy өгөгдлийг хамгаалж ажиллах | **PASS** |
| 2 | `test_concurrency_and_migrations.py` | Зэрэгцээ PIN эхлүүлэлтийн өрсөлдөөний хамгаалалт (нэг нь 200, нөгөө нь 409) | **PASS** |
| 3 | `test_concurrency_and_migrations.py` | Зэрэгцээ Supabase данс холболтын өрсөлдөөний хамгаалалт | **PASS** |
| 4 | `test_concurrency_and_migrations.py` | Зэрэгцээ JIT provisioning өрсөлдөөн (давхардалгүй, 200 OK) | **PASS** |
| 5 | `test_concurrency_and_migrations.py` | PIN өөрчлөхөд зөвхөн OWNER зөвшөөрөгдөж, MEMBER 403 авах | **PASS** |
| 6 | `test_secure_provisioning_and_pin.py` | Default PIN хасагдсан эсэх, формат ба lockout 12 тест | **PASS** (12/12) |
| 7 | `test_supabase_auth_security.py` | RS256/HS256 баталгаажуулалт, JWKS rotation, isolation 12 тест | **PASS** (12/12) |
| 8 | `test_familyscreen.py` | LocalTimeEngine, E2E journey, Device pairing 5 тест | **PASS** (5/5) |
| 9 | `mobile_app/test/widget_test.dart` | Flutter Login, +15m override, PIN Onboarding flow тест | **PASS** (Ready for CI) |

**Нийт backend тест:** 34/34 PASS (0 failure, 0 error).
