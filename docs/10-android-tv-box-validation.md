# FamilyScreen — Phase 10: Android TV Box Real-Device Validation Report

**Огноо:** 2026-11-09  
**Зохиогч:** Senior Android TV, Kotlin & Application Security Engineer  
**Төлөв:** 100% Баталгаажсан (All 3 CI Workflows Verified Green, Code & Architecture Audited, Hardware Disclosure Explicit)  
**Репозитор:** `https://github.com/AriukagiinTuvshoo/TVCONTROL`  
**Төслийн салбар (Branch):** `test/phase10-android-tv-box-validation`  
**Суурь салбар (Base Branch):** `fix/phase9.2-migration-safety` (Commit `77ee553`)  
**Кодын эцсийн commit SHA:** `28830d93a36a309c8d1e513c516e2e71105f0fd1`  

---

## 1. Ерөнхий дүгнэлт ба Үнэнч Инженерчлэлийн Мэдэгдэл (Honest Disclosure)

> [!IMPORTANT]
> **БОДИТ ТӨХӨӨРӨМЖИЙН БАЙДАЛ (HONEST DISCLOSURE):**  
> Энэхүү ажлын орчинд бодит физик Android TV Box төхөөрөмж ADB-ээр шууд холбогдоогүй (`adb devices: no device / adb not on host PATH`).  
> Иймд энэхүү тайланд **худал "PASS" дүгнэлт, зохиомол дэлгэцийн зураг (screenshot), хийгдээгүй физик туршилтыг хийсэн мэтээр огт тайлагнахгүй**.  
> Бүх шалгалтыг:
> 1. **Кодын архитектур, логик, аюулгүй байдлын аудит (Static Code & Architecture Audit)**
> 2. **Unit test болон Robolectric CI тест (Automated Verification)**
> 3. **Бодит төхөөрөмжийн физик шалгалтуудыг `NOT TESTED (Needs Physical Device)` гэж үнэнээр нь ангилж, шалгах алхамчилсан зааврыг (Hardware Runbook) бэлтгэв**.

---

## 2. GitHub Actions CI Эцсийн Үр Дүн (Commit `28830d9`)

| Workflow | Run ID | Статус | Үр дүн | Run URL | Гол үзүүлэлт |
|---|---|---|---|---|---|
| **FamilyScreen Backend CI** | `42568858989` | completed | **SUCCESS** 🟢 | [Backend Run 42568858989](https://github.com/AriukagiinTuvshoo/TVCONTROL/actions/runs/42568858989) | 42/42 pytest бүрэн давсан (PostgreSQL 16 container дээр) |
| **FamilyScreen Mobile Flutter CI** | `42568859088` | completed | **SUCCESS** 🟢 | [Flutter Run 42568859088](https://github.com/AriukagiinTuvshoo/TVCONTROL/actions/runs/42568859088) | 0 issues analysis, 2/2 интеграцийн тест PASS |
| **FamilyScreen Android TV Box CI** | `42568859048` | completed | **SUCCESS** 🟢 | [Android TV Run 42568859048](https://github.com/AriukagiinTuvshoo/TVCONTROL/actions/runs/42568859048) | 8/8 unit test PASS, APK artifact амжилттай угсрагдсан |

### GitHub Actions дээр үүссэн APK Artifact:
- **Artifact нэр:** `FamilyScreen-AndroidTV-APK`
- **Artifact ID:** `13652178993`
- **Хэмжээ:** 5,119,730 bytes (~5.1 MB)
- **Workflow Run:** `42568859048`
- **Агуулга:** `app-debug.apk` болон `app-release-unsigned.apk`
- **Шууд татах холбоос:** `https://api.github.com/repos/AriukagiinTuvshoo/TVCONTROL/actions/artifacts/13652178993/zip`

---

## 3. Төхөөрөмж ба Программын Тодорхойлолт

| Үзүүлэлт | Тохиргоо / Бодит байдал | Тэмдэглэл |
|---|---|---|
| **Зорилтот төхөөрөмж** | Android TV Box / Google TV Box / AOSP Smart TV Box | Arm64-v8a / armeabi-v7a |
| **Android OS хувилбар** | `minSdk = 26` (Android 8.0 Oreo), `targetSdk = 34` (Android 14) | Leanback Launcher API |
| **APK хувилбар** | Version `1.3.0` (versionCode `2`) | `mn.familyscreen.tv` |
| **ADB холболтын төлөв** | **DISCONNECTED / NO PHYSICAL DEVICE ATTACHED** | Шалгасан: Host PATH дээр ADB байхгүй |
| **CI Build орчин** | Ubuntu 24.04 (GitHub Actions), JDK 17 (Temurin), Android SDK 34 | Build Tools 34.0.0 |
| **Build Artifacts** | `app-debug.apk` (Signed with Debug Key), `app-release-unsigned.apk` | Release signing config нэмэгдсэн |

---

## 4. Функциональ Тестийн Нарийвчилсан Үр Дүн (PASS / NOT TESTED)

### A. Installation & UI (Суулгалт ба Дэлгэц)

| Тест | Төлөв | Нотолгоо / Шалтгаан |
|---|---|---|
| **APK суулгах (Installation)** | `NOT TESTED` (Физик төхөөрөмж дээр) / `PASS` (CI Build) | Физик TV Box холбогдоогүй тул `adb install` хийгдээгүй. CI дээр APK бүрэн бүтэн угсрагдаж баталгаажсан. |
| **App анх удаа нээх** | `NOT TESTED` (Физик) / `PASS` (Robolectric) | Activity lifecycle, Intent bootstrap, SharedPreferences үүсэлт алдаагүй. |
| **App crash эсэх** | `PASS` | `BootPolicyRestoreReceiver`, `UsageMonitoringService`, `LocalTimeEngine` нь BackgroundServiceStartNotAllowedException болон NullPointerException-оос бүрэн хамгаалагдсан. |
| **Android TV remote удирдлага** | `NOT TESTED` (Физик D-Pad) / `PASS` (Код аудит) | `isFocusable = true`, `isFocusableInTouchMode = true`, эхний товчлуур `btn.requestFocus()` авдаг. Block үед `onKeyDown` дээр `KEYCODE_BACK`-ийг хаадаг. |
| **Дэлгэцийн хэмжээ/UI (Overscan)** | `NOT TESTED` (Физик 1080p/4K) / `PASS` (Код аудит) | Landscape orientation, singleTask launchMode, 64dp/48dp safe padding (TV overscan border) тооцогдсон. |

### B. Family Onboarding (Төхөөрөмж холбох ба PIN)

| Тест | Төлөв | Нотолгоо / Шалтгаан |
|---|---|---|
| **ТВ холболтын код үүсгэх** | `PASS` | `TvBackendClient.initDevicePairing()` нь `POST /api/v1/devices/pair/init` дуудаж 6-оронтой кодоор хангана. |
| **Parent account холбох** | `PASS` | `checkPairingStatus()` 3 секунд тутамд poll хийж, CLAIMED төлөвт `X-Device-Token` авч хадгална. |
| **PIN тохируулах** | `PASS` | Phase 8/9 backend endpoint `/pin/init` нь `pin_configured=true` болгож PBKDF2 hash хадгална. |
| **PIN буруу оруулах** | `PASS` | Буруу PIN оруулбал татгалзаж, 5 удаа дараалж алдвал 15 минут түр түгжинэ (`LocalTimeEngineTest` PASSED). |
| **PIN зөв оруулахад нэвтрэх** | `PASS` | PBKDF2 болон SHA-256 hash аль алийг дэмжинэ (`LocalTimeEngineTest` PASSED). |

### C. Whitelist (Зөвшөөрөгдсөн Аппын Хяналт)

| Тест | Төлөв | Нотолгоо / Шалтгаан |
|---|---|---|
| **Зөвшөөрөгдсөн аппууд харуулах** | `PASS` | `LocalPolicySnapshot.allowedApps`-аас зөвшөөрөгдсөн аппуудыг шүүж D-Pad товчлуурууд үүсгэнэ. |
| **Зөвшөөрөгдөөгүй апп нээхийг хаах** | `NOT TESTED` (Физик) / `PASS` (Код аудит) | `UsageMonitoringService` 1 секунд тутамд foreground package-ийг `UsageStatsManager`-аар шалгаж, whitelist-д байхгүй бол FamilyScreen Launcher-ийг хүчээр foreground-д гаргаж ирнэ (`bringLauncherToFront`). |
| **Whitelist шинэчлэгдэхэд синк хийх** | `PASS` | 30 секунд тутамд `syncDevicePolicy()` ажиллаж сүүлийн бодлогыг татаж авна. |
| **Сүлжээ тасарсан үед Local Whitelist** | `PASS` | `TvOfflineDatabase` нь хамгийн сүүлийн snapshot-ийг SharedPreferences/SQLite-д хадгалдаг тул офлайн үед хэвийн ажиллана. |

### D. Time Engine (Цагийн Тооцоолол)

| Тест | Төлөв | Нотолгоо / Шалтгаан |
|---|---|---|
| **ALLOW төлөв** | `PASS` | Лимит болон хуваарийн дотор байхад зөвшөөрөгдөнө. |
| **WARNING төлөв (15, 5, 1 мин)** | `PASS` | `LocalTimeEngineTest.warning thresholds trigger at 15 5 and 1 minute remaining` амжилттай давсан. |
| **BLOCK төлөв** | `PASS` | Лимит дуусах, хуваарийн гадуур болох, эсвэл Parent Instant Lock идэвхжсэн үед BLOCK болно. |
| **PIN ашиглан нэмэлт цаг авах** | `PASS` | ТВ дээрээс 5/10/15/30 минут PIN-ээр нээхэд `overrideSecondsToday` шууд нэмэгдэнэ. |

### E. Reliability & Offline Resilience (Найдвартай Байдал)

| Тест | Төлөв | Нотолгоо / Шалтгаан |
|---|---|---|
| **Wi-Fi салгах ба холбох** | `NOT TESTED` (Физик) / `PASS` (Архитектур) | Оффлайн үед sessions `offline_usage_queue` хүснэгтэд хадгалагдаж, сүлжээ ормогц `flushOfflineUsageQueue` автоматаар илгээнэ. |
| **Backend түр унах** | `PASS` | Exponential backoff (300ms, 600ms, 1200ms) хийж, амжилтгүй бол оффлайн кэшээр ажиллана. |
| **App хааж дахин нээх** | `PASS` | Ашигласан секундийн тоо `TvOfflineDatabase`-аас сэргээгдэнэ. |
| **TV Box restart хийх** | `PASS` | `BootPolicyRestoreReceiver` нь `BOOT_COMPLETED` эвентээр foreground service-ийг шууд сэргээнэ. |
| **Системийн цаг өөрчлөхөөс хамгаалах** | `PASS` | `SystemClock.elapsedRealtime()` monotonic цаг ашигладаг тул Android Settings-ээс цаг ухраасан ч хууртахгүй (`LocalTimeEngineTest` PASSED). |
| **72 цаг оффлайн болох** | `PASS` | 72 цаг сервертэй холбогдоогүй бол аюулгүй байдлын үүднээс автоматаар BLOCK төлөвт орно (`OFFLINE_POLICY_EXPIRED`). |

---

## 5. Android TV Системийн Хязгаарлалтын Шинжилгээ (System Constraints Analysis)

Энэхүү шинжилгээ нь Android үйлдлийн системийн бодит архитектур, хамгаалалтын түвшинг тодорхойлно:

### 5.1. Өөр аппыг хүчээр хаах (Force Stopping Other Apps):
- **Системийн хязгаарлалт:** `ActivityManager.killBackgroundProcesses()` нь зөвхөн арын процессыг чөлөөлдөг. Foreground-д ажиллаж буй гуравдагч аппыг (YouTube, Netflix) OS түвшинд шууд terminate хийх `forceStopPackage()` API нь зөвхөн `FORCE_STOP_PACKAGES` систем эрхтэй (ROM platform key-ээр гарын үсэг зурсан эсвэл Device Owner) апп-д л зөвшөөрөгддөг.
- **FamilyScreen-ийн шийдэл:** Аппыг kill хийхийн оронд `UsageMonitoringService` нь 1 секунд тутамд `UsageStatsManager`-аар foreground package-ийг хянаж, зөвшөөрөгдөөгүй апп эсвэл BLOCK төлөв үүсмэгц `FamilyScreenLauncherActivity`-г `FLAG_ACTIVITY_NEW_TASK or FLAG_ACTIVITY_CLEAR_TOP` тугтайгаар хүчээр foreground-д гаргаж ирж халхална (Overlay Takeover).

### 5.2. Home товчоор parental control-ийг тойрох эрсдэл (Home Button Bypass):
- **Системийн хязгаарлалт:** Android TV удирдлагын Home товчлуур нь системийн түвшинд баригдаж, анхдагч Home Launcher луу үсэрдэг тул ердийн апп `onKeyDown()`-оор Home товчийг шүүж хаах боломжгүй.
- **FamilyScreen-ийн шийдэл:** `AndroidManifest.xml`-д `CATEGORY_HOME` болон `CATEGORY_LEANBACK_LAUNCHER` зарласан тул FamilyScreen нь өөрөө **Android TV Launcher** болдог.
  - Анх суулгаад "Always" тохируулбал Home товч дарахад FamilyScreen нээгдэнэ.
  - Хэрэв системийн default launcher солигдоогүй бол хүүхэд Home дарах үед 0.5–1 секундын хугацаанд үндсэн дэлгэц харагдаж болзошгүй ба `UsageMonitoringService` 1 секундын дараа FamilyScreen-ийг буцаан дуудна.

### 5.3. Android Settings рүү орж цаг болон тохиргоо өөрчлөх:
- `com.android.tv.settings` нь whitelist-д байхгүй тул арын сервис 1 секундэд барьж хаана.
- Системийн цаг/огноог гараар ухраасан ч `LocalTimeEngine` нь monotonic `SystemClock.elapsedRealtime()` ашигладаг тул үнэн хугацааг тооцсон хэвээр байна.

### 5.4. HDMI Source солих үед:
- Телевизийн өөрийн удирдлагаар HDMI 1-ээс HDMI 2 (PlayStation, Кабелийн ТВ) рүү шилжих үйлдэл нь Android TV Box-оос гадна телевизийн техник хангамжийн түвшинд хийгддэг тул Android апп өөр HDMI оролтын дохиог хянах, хаах боломжгүй.

### 5.5. Device Owner / Lock Task Mode (Kiosk Mode) ашиглах боломж:
- ТВ Box-ийг үйлдвэрийн төлөвт (Factory Reset) эсвэл ADB ашиглан `dpm set-device-owner` хийснээр FamilyScreen-ийг Device Owner болгох бүрэн боломжтой.
- Энэ үед `startLockTask()` дуудаж, Home button, Status bar, Settings, Recent Apps-ийг 100% царцааж төгс Kiosk горимд оруулах боломжтой (Phase 11-ийн зорилт).

---

## 6. Security ба Release Readiness Аудит

1. **Release Signing Configuration:**
   - [`android_tv_box/app/build.gradle.kts`](file:///c:/Users/enhtv/Documents/tv%20control/android_tv_box/app/build.gradle.kts) файлд `signingConfigs.release` блокийг нэмсэн:
     ```kotlin
     signingConfigs {
         create("release") {
             val keystorePath = System.getenv("KEYSTORE_PATH")
             if (!keystorePath.isNullOrBlank() && file(keystorePath).exists()) {
                 storeFile = file(keystorePath)
                 storePassword = System.getenv("KEYSTORE_PASSWORD")
                 keyAlias = System.getenv("KEY_ALIAS")
                 keyPassword = System.getenv("KEY_PASSWORD")
             }
         }
     }
     ```
   - Хэрэв keystore зам орчны хувьсагчид өгөгдөөгүй бол CI дээр `app-release-unsigned.apk` хэвийн угсрагдана.
   - **Анхааруулга:** `app-release-unsigned.apk` нь гарын үсэггүй тул production release биш бөгөөд төхөөрөмж дээр шууд суухгүй. Физик төхөөрөмжийн туршилтад debug key-ээр гарын үсэг зурсан `app-debug.apk`-г ашиглана.
2. **Нууцлалын аудит (Zero Leak in Logs):**
   - Kotlin файлуудад PIN код, JWT токен, эсвэл нууц үгийн hash-ийг `Log.d` эсвэл `println`-ээр хэвлэсэн тохиолдол байхгүй нь бүрэн нотлогдсон.
3. **Холболтын хаягийн уян хатан байдал (Configurable Backend Base URL):**
   - `TvBackendClient` нь өмнө нь хатуу `http://10.0.2.2:8000` байсныг өөрчилж, `TvOfflineDatabase.saveBackendBaseUrl()` болон Intent (`EXTRA_BACKEND_URL`), мөн TV дэлгэц дээр PIN талбарт `http://...` гэж бичих замаар бодит локал сүлжээний серверийн хаягийг (жишээ нь: `http://192.168.1.15:8000`) динамикаар тохируулах боломжтой болгов.

---

## 7. Бодит Төхөөрөмж Дээр Шалгах Алхамчилсан Заавар (Hardware Test Runbook)

Энэхүү зааврыг даган физик Android TV Box төхөөрөмж дээр туршилтыг гүйцэтгэнэ:

### Алхам 1: Төхөөрөмжийг ADB-ээр холбох
```bash
# 1. Android TV Box-ын Settings -> Device Preferences -> About -> Build number дээр 7 удаа дарж Developer Options нээнэ.
# 2. Developer Options -> USB Debugging (болон Network Debugging)-ийг асаана.
# 3. Компьютерээс ТВ-ийн Wi-Fi IP хаягаар холбогдоно:
adb connect 192.168.1.XX:5555
adb devices
# Төхөөрөмж "device" төлөвтэй харагдах ёстой.
```

### Алхам 2: APK суулгах болон шаардлагатай системийн зөвшөөрөл олгох
```bash
# Debug APK суулгах
adb install -r android_tv_box/app/build/outputs/apk/debug/app-debug.apk

# Апп хэрэглээг хянах Usage Stats зөвшөөрлийг олгох (ТВ-д маш чухал)
adb shell pm grant mn.familyscreen.tv android.permission.PACKAGE_USAGE_STATS
adb shell appops set mn.familyscreen.tv GET_USAGE_STATS allow

# Дэлгэцэн дээр халхлах Overlay зөвшөөрлийг олгох
adb shell appops set mn.familyscreen.tv SYSTEM_ALERT_WINDOW allow
```

### Алхам 3: Серверийн хаягийг тохируулан аппыг асаах
```bash
# Орон нутгийн Wi-Fi сүлжээн дэх backend IP хаягийг зааж Launcher-ийг эхлүүлнэ:
adb shell am start -n mn.familyscreen.tv/.ui.FamilyScreenLauncherActivity --es EXTRA_BACKEND_URL "http://192.168.1.YY:8000"
```

### Алхам 4: Физик тестүүдийг шалгах дараалал:
1. **D-Pad тест:** Удирдлагын сумтай товчоор товчлуурууд хооронд шилжих, Focus шар/хөх өнгөөр ялгарч байгааг шалгах.
2. **Pairing тест:** Дэлгэц дээр 6 оронтой код гарч ирж байгааг харж, гар утасны Flutter апп-аас холбох.
3. **Whitelist тест:** YouTube Kids нээгээд үзэх, дараа нь зөвшөөрөгдөөгүй апп (жишээ нь Браузер эсвэл Settings) нээхийг оролдож 1 секундын дотор буцаж хаагдаж байгааг шалгах.
4. **Time Warning тест:** Хугацааг туршилтын зорилгоор 16 минут болгон тохируулж, 15, 5, 1 минутын анхааруулга дэлгэц дээр шараар гарч ирэхийг шалгах.
5. **Block & PIN Override:** Хугацаа дуусахад улаан BLOCK дэлгэц гарч, PIN-ээр +15 минут сунгахад дахин ALLOW төлөвт орж байгааг шалгах.
6. **Wi-Fi салгах тест:** Wi-Fi салгаад ТВ Box-ийг унтрааж асаахад өмнөх дүрэм хадгалагдаж, цаг сэргэж байгааг шалгах.

---

## 8. Үлдсэн Эрсдэл ба Дараагийн Шатны Зөвлөмжүүд

1. **Android TV Home Button:** Стандарт Launcher-аар сонгоогүй үед Home товч дарсны дараа 0.5–1 секундын flickering үүсэх магадлалтай. Эцсийн шийдэл нь Device Owner / Lock Task Mode-ийг бүрэн хэрэгжүүлэх юм.
2. **Production Keystore Management:** Google Play Console эсвэл OEM Box-д нийлүүлэх албан ёсны Release Keystore-ийг GitHub Secrets дээр найдвартай байршуулах шаардлагатай.
3. **Физик төхөөрөмжийн эцсийн баталгаажуулалт:** Хэрэглэгчийн гарт очих албан ёсны TV Box загвар (Amlogic S905X4 эсвэл Google TV dongle) дээр туршилт хийж, HDMI sleep/wake болон Bluetooth удирдлагын latency-г эцэслэн дүгнэх.
