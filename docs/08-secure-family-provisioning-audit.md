# FamilyScreen — Документ 08: Secure Family Provisioning & PIN Initialization Audit

**Огноо:** 2026-11-09  
**Салбар (Branch):** `fix/secure-family-provisioning`  
**Статус:** 100% Засварлагдсан, Бүх 29 тест PASS (100% Ногоон)  
**Хамрах хүрээ:** Default PIN устгал, Эцэг эхийн PIN анхны тохиргоо (`/pin/init`), Одоогийн PIN заавал шалгах ба түгжих логик (`/pin`), Supabase имэйлээр автоматаар холбогдохоос сэргийлэх (Account Takeover хамгаалалт), Аюулгүй данс нэгтгэл (`/link-account`), TV Box LocalTimeEngine хамгаалалт, Flutter Mobile App интеграци.  

---

## 1. Илэрсэн Аюулгүй Байдлын Ноцтой Эрсдэлүүд (Identified Security Vulnerabilities)

Сүүлийн кодын аудитаар дараах өндөр эрсдэлтэй цоорхойнууд илэрсэн:

1. **Дефолт PIN кодын автомат олголт (Hardcoded Default PIN `2580`)**:
   - `backend/app/main.py`-ийн `_provision_supabase_family()` дотор `pin_code = custom_pin or "2580"` логик байсан. Хэрэглэгч өөрөө PIN тохируулаагүй байхад систем автоматаар бүх шинэ гэр бүлд `2580` PIN оноодог байсан. Хүүхэд энэхүү дефолт кодыг ашиглан дэлгэцийн хязгаарлалтыг дур мэдэн цуцлах өндөр эрсдэлтэй.
2. **PIN солиход одоогийн PIN-ийг алгасах боломж (Silent PIN Overwrite Bypass)**:
   - `PUT /api/v1/families/{family_id}/pin` endpoint дээр `if payload.current_pin is not None and family.pin_hash is not None:` гэсэн нөхцөл байсан. Хэрэв хүсэлтэд `current_pin`-ийг оруулахгүй (`None`) явуулбал шалгалтыг бүрэн тойрч гарч, хуучин PIN-ийг мэдэхгүй байсан ч шинэ PIN-ээр дарж бичих ноцтой логик цоорхой байсан.
3. **Имэйлээр шууд данс холбох ба Данс дээрэмдэх эрсдэл (Account Takeover via Email Alone)**:
   - `_provision_supabase_family()`-д `User.email == principal.email` нөхцөлөөр дотоод хэрэглэгчийг хайж, олдвол тухайн хэрэглэгчийн `User` болон `Family`-ийг Supabase хэрэглэгчид шууд холбодог байсан.
   - Энэ нь халдагч хэн нэгний имэйл хаягаар гадаад Supabase данс үүсгээд тухайн хохирогчийн гэр бүлийн бүх удирдлага, хүүхдийн мэдээлэл, холбогдсон ТВ төхөөрөмжүүдийг өөрийн болгох (Account Takeover) боломжийг олгож байв.
4. **Android TV Box болон Mobile UI дээрх хатуу кодлогдсон `2580`**:
   - `UsageMonitoringService.kt`-д bootstrap үед `pinHash = sha256Hex("2580")` гэж байсан.
   - `FamilyScreenLauncherActivity.kt`-ийн hint дээр "жнь: 2580" гэж байсан.
   - `mobile_app/lib/main.dart`-д бүртгэлийн формын `_pinController = TextEditingController(text: '2580')` гэж анхнаасаа бөглөгдсөн байсан.

---

## 2. Хэрэгжүүлсэн Инженерчлэл ба Хамгаалалтын Архитектур

### 2.1. Дефолт PIN-ийг Бүрэн Устгаж `PIN_NOT_CONFIGURED` Төлөвт Шилжүүлсэн нь
- `backend/app/models.py`:
  - `Family` моделоос дефолт утгыг авч хаясан.
  - `@property def pin_configured(self) -> bool` болон `has_pin_configured` нэмэгдсэн.
  - Хэрэв эцэг эх анхнаасаа PIN тохируулаагүй бол `family.pin_hash = None` байна.
- `backend/app/schemas.py`:
  - `FamilyOut`-д `pin_configured: bool = False` нэмэгдсэн. Мобайл апп гэр бүлийн PIN тохируулагдсан эсэхийг шууд мэдэж анхааруулга гаргана.
  - `SupabaseSyncRequest.pin_code` нь `default="2580"`-аас `default=None` болсон.

### 2.2. Эцэг Эхийн Анхны PIN Тохируулах Тусгай Endpoint (`POST /api/v1/families/{id}/pin/init`)
- Шинээр үүссэн гэр бүлийн хувьд PIN тохируулаагүй үед эцэг эх нь өөрийн гараар 4-6 оронтой PIN сонгож тохируулна.
- **Хандалтын хяналт**: Зөвхөн гэр бүлийн `OWNER` үүрэгтэй эцэг эх дуудах эрхтэй (`403 Forbidden`).
- **Давхар тохиргооноос хамгаалах**: Хэрэв тухайн гэр бүлд аль хэдийн PIN тохируулагдсан бол `409 Conflict` буцаана (дахин эхлүүлэх боломжгүй, заавал хуучин кодоороо шинэчлэх ёстой).
- **Формат шалгалт**: `r"^\d{4,6}$"` шаардлага хангаагүй бол `422 Unprocessable Entity`.

### 2.3. PIN Шинэчлэх Endpoint-ийн Аюулгүй Байдлыг Бэхжүүлсэн нь (`PUT /api/v1/families/{id}/pin`)
- Хэрэв тухайн гэр бүлд PIN тохируулагдсан бол `payload.current_pin` заавал шаардагдана (`400 Bad Request`).
- Одоогийн PIN буруу бол:
  - `family.pin_failed_attempts` тоолуур +1 нэмэгдэнэ.
  - 5 удаа буруу оруулбал систем `pin_locked_until = now_utc + 15 minutes` болгож түгжинэ.
  - Түгжигдсэн үед зөв PIN оруулсан ч `429 Too Many Requests` буцаана.
- Зөв PIN оруулсан үед шинэ PIN-ийг PBKDF2-HMAC-SHA256-аар hash-лж, оролдлогын тоолуур болон түгжээг тэглэнэ (`attempts=0, locked_until=None`).

### 2.4. Supabase Данс Нэгтгэлийн Хамгаалалт (Anti-ATO Architecture)
- `backend/app/models.py`:
  - `User` хүснэгтэд `supabase_sub: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True, index=True)` багана нэмэв.
- **Автомат холболтыг хориглосон нь**:
  - `_provision_supabase_family()` зөвхөн `User.supabase_sub == principal.user_id` эсвэл `User.id == principal.user_id` нөхцөлөөр хэрэглэгчийг танина.
  - Хэрэв тухайн Supabase имэйл хаягаар дотоод системд бүртгэлтэй хэрэглэгч олдвол **автоматаар нэвтрүүлэхгүй**, харин шууд:
    `HTTP 409 Conflict: ACCOUNT_LINKING_REQUIRED` алдаа заана.
- **Баталгаажсан Данс Холбох Endpoint (`POST /api/v1/auth/supabase/link-account`)**:
  - Зөвхөн Supabase-аар нэвтэрсэн хэрэглэгч дуудна.
  - **Имэйл баталгаажуулалтын шалгалт**: `principal.email_verified is True` байх ёстой (Баталгаажаагүй имэйлийг `403 Forbidden`-ээр татгалзана).
  - **Нууц үгийн шалгалт**: Дотоод хэрэглэгчийн бодит нууц үгийг `verify_secret(payload.local_password, local_user.password_hash)` ашиглан шалгана. Буруу бол `401 Unauthorized`.
  - Зөвхөн нууц үгээ баталж чадсан тохиолдолд `local_user.supabase_sub = principal.user_id` болгон холбоно.

### 2.5. Android TV Box & Mobile App Сахилга Бат
- `android_tv_box/.../LocalTimeEngine.kt`:
  - `verifyPinHash`-д `if (storedHash.isBlank() || plainPin.isBlank()) return false` нэмэгдэж, тохируулаагүй хоосон PIN-тэй ТВ дээр ямар ч PIN-ээр override хийх боломжгүй болов.
- `android_tv_box/.../UsageMonitoringService.kt`:
  - `defaultBootstrapSnapshot`-ийн `pinHash` нь `""` (хоосон) болж, төхөөрөмж хосолгоо хийгдэж эцэг эхийн баталгаат дүрэм иртэл ямар ч дефолт PIN байхгүй болсон.
- `android_tv_box/.../FamilyScreenLauncherActivity.kt`:
  - Текстийн hint-ийг "Эцэг эхийн 4-6 оронтой PIN код" болгон засав.
- `mobile_app/.../main.dart`:
  - Формын `_pinController`-ийн дефолт '2580' утгыг арилгаж, эцэг эх гараар өөрийн нууц PIN-ээ оруулахыг шаарддаг болов.
- `mobile_app/.../api_client.dart`:
  - `initFamilyPin(familyId, newPin)` болон `linkSupabaseAccount(localPassword)` функцууд нэмэгдсэн.

---

## 3. Тестийн Үр Дүн ба Баталгаажуулалт (Verification Evidence)

`backend/tests/test_secure_provisioning_and_pin.py` файлд криптографийн бодит түлхүүрүүд (RSA 2048, RS256, PBKDF2) бүхий 12 цоо шинэ аюулгүй байдлын тест бичигдэж, бүтэн системийн 29 тест 100% ногоон боллоо:

```text
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.2.0, pluggy-1.7.0
rootdir: C:\Users\enhtv\Documents\tv control\backend
collected 29 items

tests/test_familyscreen.py::test_time_engine_prd_example_transitions PASSED [  3%]
tests/test_familyscreen.py::test_full_mvp_end_to_end_journey PASSED      [  6%]
tests/test_familyscreen.py::test_authentication_and_cross_family_isolation PASSED [ 10%]
tests/test_familyscreen.py::test_tv_box_pairing_token_offline_sync_policy_and_instant_lock PASSED [ 13%]
tests/test_familyscreen.py::test_supabase_jwt_auth_and_security_production_checks PASSED [ 17%]
tests/test_secure_provisioning_and_pin.py::test_01_no_default_pin_on_new_supabase_family PASSED [ 20%]
tests/test_secure_provisioning_and_pin.py::test_02_explicit_pin_init_success PASSED [ 24%]
tests/test_secure_provisioning_and_pin.py::test_03_pin_init_rejects_if_already_configured PASSED [ 27%]
tests/test_secure_provisioning_and_pin.py::test_04_pin_init_rejects_invalid_format PASSED [ 31%]
tests/test_secure_provisioning_and_pin.py::test_05_pin_init_requires_owner_role PASSED [ 34%]
tests/test_secure_provisioning_and_pin.py::test_06_update_pin_requires_current_pin_when_configured PASSED [ 37%]
tests/test_secure_provisioning_and_pin.py::test_07_update_pin_wrong_current_pin_increments_attempts_and_locks PASSED [ 41%]
tests/test_secure_provisioning_and_pin.py::test_08_update_pin_success_resets_attempts PASSED [ 44%]
tests/test_secure_provisioning_and_pin.py::test_09_prevent_account_takeover_by_email_alone PASSED [ 48%]
tests/test_secure_provisioning_and_pin.py::test_10_account_link_rejects_unverified_supabase_email PASSED [ 51%]
tests/test_secure_provisioning_and_pin.py::test_11_account_link_rejects_wrong_local_password PASSED [ 55%]
tests/test_secure_provisioning_and_pin.py::test_12_account_link_success PASSED [ 58%]
tests/test_supabase_auth_security.py::test_01_valid_rs256_jwt_pass PASSED [ 62%]
tests/test_supabase_auth_security.py::test_02_valid_hs256_jwt_pass_when_configured PASSED [ 65%]
tests/test_supabase_auth_security.py::test_03_invalid_signature_reject PASSED [ 68%]
tests/test_supabase_auth_security.py::test_04_expired_jwt_reject PASSED  [ 72%]
tests/test_supabase_auth_security.py::test_05_wrong_issuer_reject PASSED [ 75%]
tests/test_supabase_auth_security.py::test_06_wrong_audience_reject PASSED [ 79%]
tests/test_supabase_auth_security.py::test_07_different_supabase_project_token_reject PASSED [ 82%]
tests/test_supabase_auth_security.py::test_08_jwks_key_not_found_safe_reject PASSED [ 86%]
tests/test_supabase_auth_security.py::test_09_jwks_key_rotation_handled_properly PASSED [ 89%]
tests/test_supabase_auth_security.py::test_10_cross_family_access_supabase_reject PASSED [ 93%]
tests/test_supabase_auth_security.py::test_11_supabase_user_jit_provisioning PASSED [ 96%]
tests/test_supabase_auth_security.py::test_12_custom_authentication_regression PASSED [100%]

======================== 29 passed, 1 warning in 7.34s ========================
```

---

## 4. Дүгнэлт ба Цаашдын Бэлэн Байдал (Conclusion & Production Readiness)

1. **Эрсдэл 1 (Дефолт PIN)**: Системийн хэмжээнд бүрэн хасагдсан. Хэрэглэгч анх тохируулах хүртэл PIN идэвхгүй байх тул тааварлах эсвэл дефолт кодоор хамгаалалт тайлах ямар ч боломжгүй.
2. **Эрсдэл 2 (Имэйлээр автоматаар холбогдох)**: Халдагч гадны Supabase данс нээж хохирогчийн имэйлээр хандах үед 409 Conflict авч гацна. Зөвхөн тухайн имэйл баталгаажсан бөгөөд дотоод нууц үгийг зөв оруулсан үед л данс нэгтгэл амжилттай болно.
3. Бүх backend, android болон mobile өөрчлөлтүүд atomic commit-оор бүртгэгдэж, GitHub албан ёсны repo руу түлхэхэд бүрэн бэлэн боллоо.
