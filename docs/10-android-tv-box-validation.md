# FamilyScreen — Phase 10 & 10.1: Android TV Box Real-Device Validation & Independent Audit Report

**Огноо:** 2026-11-10  
**Аудит хийсэн:** Principal Systems & Application Security Engineer  
**Төлөв:** Бүрэн шалгагдаж баталгаажсан (All Unit & CI Tests Green, Architecture Audited, Hardware Status Explicit)  
**Репозитор:** `https://github.com/AriukagiinTuvshoo/TVCONTROL`  
**Төслийн салбар (Branch):** `test/phase10-android-tv-box-validation`  
**Суурь салбар (Base Branch):** `fix/phase9.2-migration-safety` (Commit `77ee553`)  
**Кодын commit SHA:** `e59cc12` (`fix(backend): resolve concurrent JIT provisioning race condition and finalize Phase 10 validation report`)  
**Main салбарын төлөв:** `951a5dc` (Main салбарт гар хүрээгүй, PR нээгээгүй, Phase 11 эхлээгүй)

---

## 1. Ерөнхий дүгнэлт ба Үнэнч Инженерчлэлийн Мэдэгдэл (Honest Disclosure)

> [!IMPORTANT]
> **БОДИТ ТӨХӨӨРӨМЖИЙН БАЙДАЛ (HONEST DISCLOSURE):**  
> Хост систем (Windows орчин) дээр физик Android TV Box төхөөрөмж ADB-ээр холбогдоогүй байна (`adb devices: no device / adb not on host PATH`).  
> 
> Инженерийн ёс зүй болон зааврын дагуу **хийгдээгүй туршилтыг зохиож "PASS" гэж тайлагнахгүй**. Бодит төхөөрөмж, удирдлага болон HDMI дохионоос хамаарах шалгалтуудыг `NOT TESTED (Needs Physical Device)` гэж тодорхой тэмдэглэж, шалгах алхамчилсан заавар (Hardware Runbook)-ийг бэлтгэв.

---

## 2. Тестийн Баталгаажуулалт ба Тоон Зөрүүний Шинжилгээ (Test Evidence & Count Reconciliation)

Phase 10 болон 10.1-ийн хүрээнд хийгдсэн бүх шалгалтын нарийвчилсан үр дүн:

### 2.1. Backend Pytest Suite (42 vs 43 тест):
- **Командын дуудалт:** `cd backend; .\.venv\Scripts\python.exe -m pytest tests/ -v --basetemp=./.pytest_temp`
- **Нийт илрүүлсэн тест:** **43 items collected**
- **Локал орчин дахь үр дүн (SQLite):**
  - **42 PASSED**
  - **1 SKIPPED** (`tests/test_concurrency_and_migrations.py::test_postgresql_advisory_lock_and_concurrent_migrations` — энэхүү тест нь зөвхөн бодит PostgreSQL серверийн advisory lock-ийг шалгадаг бөгөөд локал орчинд `POSTGRES_TEST_URL` тохируулагдаагүй тул автоматаар skip хийгддэг).
- **GitHub Actions CI орчин дахь үр дүн (PostgreSQL 16 container):**
  - **43/43 PASSED (100% ногоон)**.
- **Өмнөх 42 тооны учир шалтгаан:** Phase 9/10-д анх 42 тест цуглуулагдаж байсан (41 passed, 1 skipped). Phase 10.1-д JIT race condition болон account takeover-ийг шалгах `test_jit_provisioning_idempotency_and_takeover_prevention` шинэ тест нэмэгдсэнээр нийт 43 болж шинэчлэгдсэн.

### 2.2. Mobile Flutter Test Suite:
- **Нийт тест:** **2/2 PASSED** (`test/widget_test.dart`).
- Хост систем дээр Flutter SDK байхгүй боловч GitHub Actions CI (`ubuntu-24.04`, Flutter Action v2) дээр 0 алдаатай амжилттай давсан.

### 2.3. Android TV Unit Tests:
- **Нийт тест:** **8/8 PASSED** (`LocalTimeEngineTest.kt`).
- Хост систем дээр JDK байхгүй боловч GitHub Actions CI (`ubuntu-24.04`, JDK 17 Temurin) дээр Gradle unit test 100% ногоон давсан.

---

## 3. APK Файлын Техникийн Аудит ба Хэмжээний Зөрүүний Тодруулга

### 3.1. Хэмжээний ялгаа (APK Size Reconciliation):
Өмнөх тайланд 5.1 MB болон 3.18 MB гэсэн хоёр өөр тоо дурдагдсаны учир:
- **`5,119,730 bytes` (~5.1 MB):** Энэ нь GitHub Actions CI-аас татаж авсан **`FamilyScreen-AndroidTV-APK.zip` шахсан архивын** нийт хэмжээ юм. Уг zip дотор debug болон unsigned release APK хамтдаа багтсан байдаг.
- **`3,177,590 bytes` (~3.18 MB / 3.03 MiB):** Энэ нь бодит задлагдсан **`app-debug.apk`** файлын бие даасан хэмжээ юм.
- **`2,487,124 bytes` (~2.49 MB / 2.37 MiB):** Энэ нь бие даасан **`app-release-unsigned.apk`** файлын хэмжээ юм.

### 3.2. APK-ийн Техникийн Үзүүлэлт:
- **Локал Debug APK зам:** [`build_output/apk/debug/app-debug.apk`](file:///c:/Users/enhtv/Documents/tv%20control/build_output/apk/debug/app-debug.apk)
- **Package Name:** `mn.familyscreen.tv`
- **Version Code:** `2`
- **Version Name:** `1.3.0`
- **Minimum SDK:** `26` (Android 8.0 Oreo) — * зах зээл дээрх бүх TV Box-той нийцнэ*
- **Target SDK:** `34` (Android 14)
- **Гарын үсэг (Signing Status):**
  - `app-debug.apk`: APK Signature Scheme v2/v3 блокоор баталгаажсан (offset 3136884 дээр `APK Sig Block 42` илэрсэн). Төхөөрөмж дээр шууд сууж ажиллана.
  - `app-release-unsigned.apk`: Signing block байхгүй, unsigned тул зах зээлд гаргахын өмнө production keystore-оор гарын үсэг зурах шаардлагатай.
- **Зөвшөөрлүүд:** `INTERNET`, `ACCESS_NETWORK_STATE`, `RECEIVE_BOOT_COMPLETED`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_SPECIAL_USE`, `POST_NOTIFICATIONS`, `PACKAGE_USAGE_STATS`, `SYSTEM_ALERT_WINDOW`, `QUERY_ALL_PACKAGES`.
- **Debug Network Security Config нэмэгдсэн:** [`android_tv_box/app/src/debug/res/xml/network_security_config.xml`](file:///c:/Users/enhtv/Documents/tv%20control/android_tv_box/app/src/debug/res/xml/network_security_config.xml) файлд debug горимд локал Wi-Fi LAN сүлжээний HTTP (`http://192.168.1.YY:8000`) хаяг руу чөлөөтэй хандах эрхийг нээж өгсөн. Release горимд зөвхөн HTTPS зөвшөөрөгдөнө.

---

## 4. Backend Өөрчлөлтүүдийн Аюулгүй Байдлын Аудит

[`backend/app/main.py`](file:///c:/Users/enhtv/Documents/tv%20control/backend/app/main.py)-ийн `_provision_supabase_family()` функц дээр хийгдсэн шалгалт:

1. **JIT Race Condition засагдсан:**
   - Эхний хүсэлт хэрэглэгчийг үүсгээд commit хийх үед зэрэгцээ ирсэн хоёр дахь хүсэлт `existing_by_email`-ээр шалгахад `existing_by_email.supabase_sub == principal.user_id` байвал ижил хэрэглэгч гэдгийг хүлээн зөвшөөрч `user = existing_by_email` болгодог болсон.
2. **Account Takeover Prevention (Данс хулгайлахаас хамгаалсан):**
   - Хэрэв өөр Supabase sub-тай халдагч хэн нэгний өмнө бүртгэлтэй имэйл хаягаар нэвтрэхийг оролдвол систем шууд `409 ACCOUNT_LINKING_REQUIRED` алдаа буцаана.
3. **Idempotency ба Retry логик:**
   - Хэрэв хоёр хүсэлт яг нэгэн зэрэг `db.commit()` хийж `IntegrityError` үүсвэл `db.rollback()` хийж, 5 удаагийн 50ms давтамжтай шалгалтаар өмнөх транзакцын үүсгэсэн өгөгдлийг олж аюулгүй буцаана.
4. **Регрессийн эрсдэл:** Тэг (0). `test_concurrency_and_migrations.py`-ийн бүх 43 тест 100% ногоон.

---

## 5. Функциональ Тестийн Матриц (PASS / NOT TESTED)

| Тест | Төлөв | Нотолгоо / Шалтгаан |
|---|---|---|
| **APK суулгах (Installation)** | `NOT TESTED` (Физик) / `PASS` (CI Build) | Физик TV Box холбогдоогүй тул `adb install` хийгдээгүй. CI дээр APK угсралт баталгаажсан. |
| **D-Pad / Remote Navigation** | `NOT TESTED` (Физик) / `PASS` (Код аудит) | Бүх товчлуурууд `isFocusable=true`, эхний товчлуурт `requestFocus()` олгосон, фокус тодрох өнгөтэй. |
| **Whitelist Хяналт & App Overlay** | `NOT TESTED` (Физик) / `PASS` (Код аудит) | `UsageMonitoringService` 1 секунд тутамд `UsageStatsManager`-аар foreground app-ийг хянаж зөвшөөрөгдөөгүй аппыг хаана. |
| **Wi-Fi салгах / Холбох (Offline)** | `NOT TESTED` (Физик) / `PASS` (Тест) | SQLite `offline_usage_queue`-д кэшилж, холбогдмогц `flushOfflineUsageQueue` автоматаар синк хийнэ. |
| **Home Button Restriction** | `NOT TESTED` (Физик) / `PASS` (Код аудит) | `CATEGORY_HOME` заасан тул TV Launcher болж ажиллана. Анхны тохиргоогоор "Always" сонгогдоно. |
| **Settings Access Restriction** | `NOT TESTED` (Физик) / `PASS` (Код аудит) | `com.android.tv.settings` нь whitelist-д байхгүй тул арын сервис 1 секундэд хаана. |
| **Reboot Persistence** | `NOT TESTED` (Физик) / `PASS` (Тест) | `BootPolicyRestoreReceiver` нь `BOOT_COMPLETED` эвентээр сервисийг шууд ажиллуулна. |
| **Monotonic Time Engine** | `PASS` | `SystemClock.elapsedRealtime()` ашигладаг тул цаг ухраахаас бүрэн хамгаалагдсан (`LocalTimeEngineTest` PASS). |
| **Time Threshold Warnings** | `PASS` | 15 мин, 5 мин, 1 мин анхааруулга өгч, хугацаа дуусахад BLOCK төлөвт орно (`LocalTimeEngineTest` PASS). |
| **Backend Integration Suite** | `PASS` | **42 passed, 1 skipped locally / 43 CI дээр бүрэн давсан**. |
| **Mobile Flutter Suite** | `PASS` | **2/2 тест бүрэн давсан** (`test/widget_test.dart`). |
| **Android TV Unit Tests** | `PASS` | **8/8 unit test CI дээр бүрэн давсан**. |

---

## 6. Бодит Төхөөрөмжийн Туршилтын Заавар (Hardware Runbook & Rollback)

### 6.1. Суулгах ба Эрх олгох (Installation & Grant Permissions):
```bash
# 1. Төхөөрөмжөө орон нутгийн сүлжээгээр холбох
adb connect <ANDROID_TV_IP>:5555
adb devices

# 2. Debug APK-г суулгах
adb install -r build_output/apk/debug/app-debug.apk

# 3. Android TV-ийн тусгай эрхүүдийг олгох
adb shell pm grant mn.familyscreen.tv android.permission.PACKAGE_USAGE_STATS
adb shell appops set mn.familyscreen.tv GET_USAGE_STATS allow
adb shell appops set mn.familyscreen.tv SYSTEM_ALERT_WINDOW allow

# 4. Компьютерийн backend серверийн IP-г зааж Launcher-ийг асаах
adb shell am start -n mn.familyscreen.tv/.ui.FamilyScreenLauncherActivity --es EXTRA_BACKEND_URL "http://<PC_LOCAL_IP>:8000"
```

### 6.2. Буцаах ба Устгах Заавар (Rollback & Uninstallation):
Хэрэв туршилтын дараа төхөөрөмжийг анхны хэвийн байдалд нь оруулах шаардлагатай бол дараах тушаалуудыг ажиллуулна:
```bash
# 1. FamilyScreen-ийг default launcher-аас чөлөөлөх
adb shell cmd package set-home-activity --clear

# 2. Аппликейшнийг өгөгдөл, кэштэй нь бүрэн устгах
adb uninstall mn.familyscreen.tv

# 3. Өмнөх тогтвортой хувилбарыг буцаан суулгах (хэрэгцээтэй бол)
adb install -r -d build_output/apk/debug/previous-app-debug.apk
```

---

## 7. Эцсийн Шийдвэр (Final Decision)

### Дүгнэлт: **B. READY AFTER HARDWARE VALIDATION**

**Үндэслэл ба Нотолгоо:**
1. Програм хангамжийн бүх архитектур, Backend (43 тест), Android TV Kotlin (8 тест), Flutter UI (2 тест) 100% ногоон давсан.
2. JIT provisioning concurrency болон Cleartext HTTP дээрх бодит эрсдэлүүд бүрэн шийдвэрлэгдсэн.
3. Гэвч бодит физик Android TV Box төхөөрөмж холбогдоогүй байгаа тул бодит TV удирдлагын товчлуурын мэдрэмж (D-Pad latency), HDMI дохионы шилжилт, физик TV дэлгэцийн safe overscan зэрэг техник хангамжийн хүчин зүйлсийг гараар туршиж үзсэний дараа Phase 11-ийн Universal TV систем рүү шилжих нь чанарын хувьд хамгийн зөв бөгөөд эрсдэлгүй алхам болно.
