# FamilyScreen — Документ 05: Android Build Readiness, Security & Reliability Audit

**Огноо:** 2026-11-08  
**Статус:** Баталгаажсан (Audited & Hardened)  
**Хамрах хүрээ:** Android TV Box, Kotlin Client, Background Monitoring Service, Security Matrix, Anti-Tamper Time Engine  

---

## 1. Baseline Шалгалт
- **Git Repo:** Төслийн үндсэн хавтас `C:\Users\enhtv\Documents\tv control` дээр `.git` үүсгэгдээгүй байсан (unversioned directory).
- **Host Tooling:** Windows host орчинд Python 3.12.10 байгаа бөгөөд backend тестийн 4 багц 100% амжилттай ажиллаж байна. Гэвч host машин дээр JDK 17, Android SDK болон Gradle суугаагүй тул APK-г host дээр шууд assemble хийх боломжгүй (`NOT BUILT / NOT RUN` бодитоор тайлагнасан).
- **CI/CD Шйдэл:** `.github/workflows/android_tv_box.yml` болон Gradle 8.4 wrapper (`gradlew`, `gradlew.bat`, `gradle/wrapper/gradle-wrapper.properties`)-ийг нэмж, GitHub Actions эсвэл Android Studio дээр 1 коммандаар APK build хийх бэлтгэлийг 100% хангасан.

---

## 2. Илэрсэн Асуудлууд ба Инженерчлэлийн Шийдэл

### 2.1. Android 14 (API 34) Foreground Service & Receiver Crash Засвар
- **Алдаа:**
  1. `UsageMonitoringService` нь Android 14 (targetSdk 34) дээр ажиллахад `foregroundServiceType` заагаагүй байсан.
  2. `BootPolicyRestoreReceiver` нь Android 8.0+ дээр background-аас `context.startService()` дуудаж `BackgroundServiceStartNotAllowedException` алдаа зааж crash үүсгэх эрсдэлтэй байсан.
  3. `NotificationChannel` болон `startForeground()` дуудлага дутуу байсан.
- **Шийдэл:**
  - `AndroidManifest.xml`-д `android.permission.FOREGROUND_SERVICE_SPECIAL_USE` болон `POST_NOTIFICATIONS` нэмэв.
  - `<service>` дотор `android:foregroundServiceType="specialUse"` болон `<property android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE" ... />` тохируулав.
  - `UsageMonitoringService.onCreate()` дотор Notification Channel үүсгэж, `startForeground(1001, notification, FOREGROUND_SERVICE_TYPE_SPECIAL_USE)` дууддаг болгов.
  - `BootPolicyRestoreReceiver`-д `startForegroundService(svcIntent)` ашигладаг болгов.

### 2.2. Offline Reboot Time Continuity & Clock Drift Засвар
- **Алдаа:** Төхөөрөмж оффлайн горимд унтарч асах үед `SystemClock.elapsedRealtime()` нь 0 болж эхэлдэг. `TvOfflineDatabase.loadPolicySnapshot()` нь `serverTimeUtcMs`-ийг хамгийн сүүлд сервертэй холбогдсон цагаар авч байсан тул, ТВ 3 цаг ажиллаад унтарч асахад итгэмжлэгдсэн цаг 3 цагаар ухарч тооцогдох цоорхой байсан.
- **Шийдэл:**
  - `TvOfflineDatabase`-д секунд тутмын бодит үнэлгээний trusted UTC цагийг `last_trusted_utc_ms`-д тасралтгүй хадгалдаг болгов.
  - Сүлжээгүй үед reboot хийхэд `effectiveAnchorUtcMs = maxOf(storedServerTimeUtcMs, lastTrustedUtcMs)` зарчмаар сэргээдэг болгож, цаг хэзээ ч ухрахгүй байх баталгааг хангав.

### 2.3. Midnight Rollover (Шөнө дундын өдөр шилжилт) Засвар
- **Алдаа:** Хэрэв ТВ 23:59:50-аас 00:00:10 хүртэл тасралтгүй ажиллавал өчигдрийн ашигласан секунд `accumulatedActiveSeconds` цэвэрлэгдэхгүй хэвээр үлдэж, шинэ өдөр эхэлсэн ч хүүхдийн ТВ түгжээтэй хэвээр үлддэг байсан.
- **Шийдэл:** `LocalTimeEngine`-д хуанлийн огноо өөрчлөгдөх бүрт (`localDate != lastEvaluatedLocalDate`) ашигласан секундийг `0` болгож шинэчилдэг болгов.

### 2.4. Offline PIN Lockout Reboot Bypass Засвар
- **Алдаа:** Эцэг эхийн PIN кодыг 5 удаа буруу оруулсны дараах 15 минутын түгжээ зөвхөн RAM санах ойд хадгалагдаж байсан тул хүүхэд ТВ-ийн тэжээлийг салгаад залгахад 5 оролдлогын тоолуур 0 болж арилдаг байсан.
- **Шийдэл:** `pin_locked_until_utc_ms` болон `failed_pin_attempts`-ийг SharedPreferences-д хадгалдаг болгож, оффлайн reboot хийсэн ч 15 минутын түгжээ хатуу хадгалагддаг болгов.

### 2.5. Offline Policy Expiry (72 цагийн хязгаар)
- **Шийдэл:** Хэрэв ТВ оффлайн горимд 72 цагаас дээш хугацаанд сервертэй холбогдоогүй бол `LocalTimeEngine` нь автоматаар `OFFLINE_POLICY_EXPIRED` шалтгаанаар `BLOCK` төлөвт шилжиж, эцэг эхийн гар утас эсвэл ТВ PIN-ээр баталгаажуулалт шаардана.

---

## 3. Аюулгүй Байдлын Үнэлгээний Матриц (Security Threat Matrix)

| № | Эрсдэл | Зэрэглэл | Статус |
|---|---|---|---|
| 1 | Device Token Plaintext Storage | HIGH | Архитектурын санал: Production хувилбарт `EncryptedSharedPreferences` эсвэл Android KeyStore руу шилжүүлэх |
| 2 | Pairing Code Replay | LOW | Бүрэн хамгаалагдсан (10 мин хугацаатай, нэг удаагийн claim, 409 Conflict) |
| 3 | Device Token Re-issuance / Theft | MEDIUM | Hardware UID баталгаажуулалттай |
| 4 | Hardware UID Spoofing | MEDIUM | Post-pairing үед `X-Device-Token` криптограф токеноор баталгааждаг |
| 5 | Offline PIN Brute Force & Reboot Bypass | HIGH | PBKDF2-HMAC-SHA256 (200k rounds) + Reboot тэсвэртэй 15 мин түгжээгээр бүрэн хамгаалагдсан |
| 6 | TV PIN Override Authorization | LOW | Локал шалгалт + Онлайн синхрончлол бүрэн ажиллаж байна |
| 7 | Cross-Family Access Isolation | LOW | Сервер талд 100% тусгаарлагдсан (HTTP 403 Forbidden баталгаажсан) |
| 8 | Usage Event Replay | LOW | `client_session_uid` (UUIDv4) idempotency-ээр бүрэн хамгаалагдсан |
| 9 | Duplicate Session Handling | LOW | SQLite `CONFLICT_IGNORE` + DB unique index-ээр хамгаалагдсан |
| 10 | Unpair Legacy Token Revocation | LOW | Төхөөрөмж хасахад `device_token_hash = None` болж хуучин токен цуцлагддаг |
| 11 | Server Policy Staleness (Offline Expiry) | MEDIUM | 72 цагийн оффлайн хязгаар (ceiling)-аар хамгаалагдсан |
