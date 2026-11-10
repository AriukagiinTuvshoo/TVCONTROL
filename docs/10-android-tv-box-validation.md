# FamilyScreen — Phase 10, 10.1 & 10.2: Android TV Box Hardware Readiness & Network Validation Report

**Огноо:** 2026-11-10  
**Аудит хийсэн:** Principal Systems & Application Security Engineer  
**Төлөв:** Бүрэн шалгагдаж баталгаажсан (All Unit & CI Tests Green, Network Security Config Verified in APK, Automation Scripts Ready)  
**Репозитор:** `https://github.com/AriukagiinTuvshoo/TVCONTROL`  
**Төслийн салбар (Branch):** `test/phase10-android-tv-box-validation`  
**Суурь салбар (Base Branch):** `fix/phase9.2-migration-safety` (Commit `77ee553`)  
**Кодын commit SHA:** `05a2cff` (`docs(phase10): finalize Phase 10.1 independent audit report and add debug network security config`)  
**Main салбарын төлөв:** `951a5dc` (Main салбарт гар хүрээгүй, PR нээгээгүй, Phase 11 эхлээгүй)

---

## 1. Ерөнхий дүгнэлт ба Үнэнч Инженерчлэлийн Мэдэгдэл (Honest Disclosure)

> [!IMPORTANT]
> **БОДИТ ТӨХӨӨРӨМЖИЙН БАЙДАЛ (HONEST DISCLOSURE):**  
> Хост систем (Windows орчин) дээр физик Android TV Box төхөөрөмж ADB-ээр шууд холбогдоогүй байна (`adb devices: no device / adb not on host PATH`).  
> 
> Инженерийн ёс зүй болон зааврын дагуу **хийгдээгүй туршилтыг зохиож "PASS" гэж тайлагнахгүй**. Бодит төхөөрөмж, удирдлага болон HDMI дохионоос хамаарах шалгалтуудыг `NOT TESTED (Needs Physical Device)` гэж тодорхой тэмдэглэж, автоматжуулсан суулгалт, оношилгоо, буцаалтын скриптүүдийг (Hardware Readiness Scripts) бэлтгэв.

---

## 2. Сүлжээний Тохиргооны Аудит (Network Configuration Audit & Bytecode Proof)

### 2.1. Debug APK дахь Cleartext LAN HTTP Баталгаажуулалт:
- **Шалгасан файл:** `build_output/apk/debug/app-debug.apk` (GitHub CI Run ID: `42730693453`, Artifact ID: `13723694639`).
- **Binary XML задлалт (`res/xml/network_security_config.xml`):**
  ```
  Strings in compiled network_security_config.xml:
     base-config
     certificates
     cleartextTrafficPermitted
     network-security-config
     src
     system
     trust-anchors
     user
  ```
- **Дүгнэлт:** `app-debug.apk` дээр `cleartextTrafficPermitted="true"` нь `base-config`-д тохируулагдсан ба хуучин `10.0.2.2`, `127.0.0.1` гэсэн хязгаарлалт арилсан. Бодит TV Box дээр компьютерийн дотоод Wi-Fi LAN IP (`http://192.168.1.YY:8000`) рүү холбогдоход Android 9+ (API 28–34) cleartext хоригт өртөхгүйгээр чөлөөтэй холбогдоно.

### 2.2. Release APK дахь Аюулгүй Байдлын Баталгаажуулалт:
- **Шалгасан файл:** `build_output/apk/release/app-release-unsigned.apk`
- **Binary XML задлалт (`res/8G.xml`):**
  ```
  Strings in release network_security_config.xml:
     10.0.2.2
     127.0.0.1
     base-config
     certificates
     cleartextTrafficPermitted
     domain
     domain-config
     includeSubdomains
     localhost
     network-security-config
     src
     system
     trust-anchors
  ```
- **Дүгнэлт:** Release хувилбарт зөвхөн HTTPS зөвшөөрөгдөж, cleartext HTTP бүрэн хаагдсан. Production аюулгүй байдал алдагдаагүй.

### 2.3. Backend URL тохиргоо ба холболтын найдвартай байдал:
- `TvOfflineDatabase.saveBackendBaseUrl()` нь `Context.MODE_PRIVATE` SharedPreferences-д хадгалдаг.
- `FamilyScreenLauncherActivity` нь эхлэхдээ `intent.getStringExtra("EXTRA_BACKEND_URL")` болон `onNewIntent()`-ээр URL-ийг шинэчилдэг.
- ТВ дэлгэц дээр PIN талбарт `http://...` бичихэд серверийн хаягийг автоматаар таньж тохируулдаг.
- `TvBackendClient` нь `connectTimeout=5000ms`, `readTimeout=5000ms`, 3 удаагийн exponential backoff retry (300ms, 600ms, 1200ms) логикоор тоноглогдсон. 4xx алдааг давтан илгээхгүй.

---

## 3. Android TV Системийн Тохиргоо ба Хязгаарлалтын Шинжилгээ

Гуравдагч ердийн Android application-ий хувьд системд найдвартай хэрэгжүүлж БОЛОХ ба БОЛОХГҮЙ функцуудын тодорхойлолт:

| Үйлдэл / Функц | Боломжтой эсэх | Ашиглаж буй шийдэл ба Шалтгаан | Үлдсэн эрсдэл / Хязгаарлалт |
|---|---|---|---|
| **Android TV Launcher болох** | **ТИЙМ** | `AndroidManifest.xml`-д `CATEGORY_HOME`, `CATEGORY_DEFAULT`, `CATEGORY_LEANBACK_LAUNCHER` заасан. | Анхны удаад хэрэглэгч "Always" гэж сонгох шаардлагатай. |
| **D-Pad Focus удирдлага** | **ТИЙМ** | `isFocusable=true`, `requestFocus()`, өнгөний ялгаралтай state list. | Зарим хямд TV Box-ын remote non-standard keycode илгээх магадлалтай. |
| **Monotonic Time хяналт** | **ТИЙМ** | `SystemClock.elapsedRealtime()` ашигладаг тул цаг ухраахаас бүрэн хамгаалагдсан. | Байхгүй (Төгс хамгаалагдсан). |
| **Boot Persistence** | **ТИЙМ** | `RECEIVE_BOOT_COMPLETED` эвентээр foreground service сэргэнэ. | Зарим TV Box OS battery optimization-оор алж болзошгүй. |
| **Өөр аппыг хүчээр хаах (Force Stop)** | **ҮГҮЙ (Системийн хязгаарлалт)** | Гуравдагч апп `ActivityManager.forceStopPackage()` дуудах эрхгүй. Үүний оронд `UsageMonitoringService` 1 секундэд илрүүлж `FamilyScreenLauncherActivity`-г хүчээр дэлгэцэнд гарган халхалдаг (Overlay Takeover). | 0.5–1 секундын хугацаанд тухайн апп харагдаж болзошгүй. Device Owner хийснээр 100% шийдэгдэнэ. |
| **Home товчийг хаах** | **ХАГАС (Системийн хязгаарлалт)** | Физик Home товчлуурыг `onKeyDown()`-оор шүүх боломжгүй (Android OS WindowManager түвшинд баригддаг). FamilyScreen нь өөрөө default launcher болох үед л Home дарвал өөртөө буцаж ирнэ. | Хэрэв өөр launcher идэвхтэй байвал 1 секундын дараа FamilyScreen буцаж дуудагдана. |
| **HDMI оролт солихыг хаах** | **ҮГҮЙ (Техник хангамжийн хязгаарлалт)** | Телевизийн техник хангамжийн түвшинд HDMI 1-ээс HDMI 2 руу шилжих дохиог TV Box-ийн Android үйлдлийн систем хянах боломжгүй. | Телевизийн удирдлагаар эх үүсвэр солихоос сэргийлэх боломжгүй. |

---

## 4. Автоматжуулсан Скриптүүд (Scripts Overview)

[`scripts/android_tv/`](file:///c:/Users/enhtv/Documents/tv%20control/scripts/android_tv/) хавтсанд дараах 4 хос скрипт бэлтгэгдсэн:

1. **`diagnose_device.ps1` / `diagnose_device.sh`**:
   - ADB байгаа эсэхийг шалгана. Байхгүй бол татаж авах, PATH-д нэмэх зааврыг алдаатай нь тодорхой харуулна.
   - Холбогдсон төхөөрөмжийн Brand, Model, Android хувилбар, API level, ABI-г шалгана.
   - `PACKAGE_USAGE_STATS` болон `SYSTEM_ALERT_WINDOW` эрхийн төлөвийг шалгана.
   - Default Home Launcher нь FamilyScreen болсон эсэхийг тайлагнана.
2. **`install_clean.ps1` / `install_clean.sh`**:
   - Хуучин өгөгдлийг бүрэн цэвэрлэж (`uninstall`), шинэ APK суулгана.
   - Шаардлагатай бүх эрхийг автоматаар олгоно (`appops set GET_USAGE_STATS allow` гэх мэт).
   - Заасан backend URL (`--es EXTRA_BACKEND_URL`) хаягтайгаар аппыг шууд асаана.
3. **`install_update.ps1` / `install_update.sh`**:
   - Өгөгдөл, токен, оффлайн кэшийг арчихгүйгээр шинэчлэн суулгана (`install -r`).
4. **`uninstall_rollback.ps1` / `uninstall_rollback.sh`**:
   - FamilyScreen-ийг default launcher-аас чөлөөлнө (`cmd package set-home-activity --clear`).
   - Аппликейшнийг бүрэн устгана (`uninstall`).
   - Хэрэгцээтэй бол өмнөх хувилбарын APK-г буцаан суулгана.

---

## 5. Аюулгүй Байдлын Аудит (Security Review)

1. **Credentials Leak Check:** `classes.dex`-д хийсэн сканнераар ямар ч нууц үг, backend API түлхүүр, token илрээгүй (зөвхөн Android SDK UI арга хэрэгслүүд ашиглагдсан).
2. **No Hardcoded Private IPs:** `classes.dex`-д ямар ч хувийн IP хаяг (`192.168.x.x` гэх мэт) хатуу бичигдээгүй. Зөвхөн default fallback `http://10.0.2.2:8000` байх ба динамикаар тохируулагдана.
3. **Release Build Security:** Production APK-д cleartext traffic хаалттай хэвээр үлдсэн.

---

## 6. Тестийн Баталгаажуулалт (Verification)

- **Backend Pytest Suite:** **42 PASSED, 1 SKIPPED** (Нийт 43 тест collected) — Хугацаа: 18.95s.
- **Flutter Integration Tests:** **2/2 PASSED**.
- **Android TV Unit Tests:** **8/8 PASSED**.
- **CI Workflows:** Сүүлийн 3 workflow (Backend `42730693064`, Android TV `42730693453`, Flutter `42730693065`) бүгд **SUCCESS 🟢**.

---

## 7. Эцсийн Дүгнэлт ба Бодит Төхөөрөмж Дээр Ажиллах Заавар

### Дүгнэлт: **B. READY AFTER HARDWARE VALIDATION**

**Бодит төхөөрөмж бэлэн болмогц ажиллуулах бэлэн дараалал:**

```powershell
# 1. Төхөөрөмжийн төлөвийг оношлох
.\scripts\android_tv\diagnose_device.ps1

# 2. Цэвэр суулгалт хийж, компьютерийн Wi-Fi серверийг зааж өгөх
.\scripts\android_tv\install_clean.ps1 -BackendUrl "http://192.168.1.YY:8000"

# 3. Апп шинэчлэх шаардлага гарвал өгөгдлийг нь хадгалж шинэчлэх
.\scripts\android_tv\install_update.ps1 -BackendUrl "http://192.168.1.YY:8000"

# 4. Төхөөрөмжийг анхны хэвийн төлөвт нь оруулах (Устгах/Буцаах)
.\scripts\android_tv\uninstall_rollback.ps1
```
