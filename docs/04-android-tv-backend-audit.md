# FAMILYSCREEN — Phase 5: Android TV Box ↔ FastAPI Интеграцийн Аудитын Тайлан

| Талбар | Утга |
|---|---|
| **Огноо** | 2026-11-08 |
| **Зорилго** | Android TV Box (Kotlin) болон FastAPI Backend-ийн одоогийн байдлыг PRD v1.1 болон Архитектурын баримт бичигтэй тулган шалгах |
| **Төлөв** | Код өөрчлөхөөс өмнөх бүрэн аудит |

---

# 1. Шалгасан файлууд

- [01-prd.md](file:///c:/Users/enhtv/Documents/tv%20control/docs/01-prd.md)
- [02-architecture-and-database.md](file:///c:/Users/enhtv/Documents/tv%20control/docs/02-architecture-and-database.md)
- [03-flutter-fastapi-audit.md](file:///c:/Users/enhtv/Documents/tv%20control/docs/03-flutter-fastapi-audit.md)
- [main.py](file:///c:/Users/enhtv/Documents/tv%20control/backend/app/main.py)
- [models.py](file:///c:/Users/enhtv/Documents/tv%20control/backend/app/models.py)
- [schemas.py](file:///c:/Users/enhtv/Documents/tv%20control/backend/app/schemas.py)
- [AndroidManifest.xml](file:///c:/Users/enhtv/Documents/tv%20control/android_tv_box/app/src/main/AndroidManifest.xml)
- [LocalTimeEngine.kt](file:///c:/Users/enhtv/Documents/tv%20control/android_tv_box/app/src/main/java/mn/familyscreen/tv/engine/LocalTimeEngine.kt)
- [FamilyScreenLauncherActivity.kt](file:///c:/Users/enhtv/Documents/tv%20control/android_tv_box/app/src/main/java/mn/familyscreen/tv/ui/FamilyScreenLauncherActivity.kt)

---

# 2. Илэрсэн Архитектурын болон Хэрэгжилтийн Зөрүүнүүд

## 2.1. Device Pairing & Device Authentication Зөрүү (Critical)
1. **Төхөөрөмжийн токен (`device_token`):**
   - `devices` хүснэгтэд ([models.py](file:///c:/Users/enhtv/Documents/tv%20control/backend/app/models.py#L135)) `device_token_hash` талбар байгаа боловч `POST /api/v1/devices/pair/init` болон `POST /api/v1/devices/pair/claim` дээр төхөөрөмжийн токен үүсгэдэггүй, мөн ТВ төхөөрөмж эцэг эх кодыг `claim` хийсэн эсэхийг шалгаж токеноо хүлээж авах endpoint эсвэл механизм дутуу байна.
   - Үүний улмаас `GET /api/v1/devices/{device_id}/sync`, `POST /api/v1/usage/sessions`, `POST /api/v1/overrides` (`source="TV_PIN"`) endpoint-ууд дээр төхөөрөмжийн (`X-Device-Token` эсвэл `Bearer <device_token>`) баталгаажуулалт хийгдэхгүй байна. Өөрөөр хэлбэл өөр гэр бүлийн эсвэл гаднын этгээд `device_id` мэдэж байвал sync эсвэл хуурамч usage илгээх эрсдэлтэй.

## 2.2. Policy Sync (`GET /api/v1/devices/{device_id}/sync`) Зөрүү
1. Одоогийн [`DeviceSyncResponse`](file:///c:/Users/enhtv/Documents/tv%20control/backend/app/schemas.py#L168-L178) нь `time_state` болон `allowed_apps` буцаадаг боловч дараах талбарууд дутуу байна:
   - `family_id` (ТВ төхөөрөмж офлайн үед `UsageSessionCreateRequest` болон `OverrideCreateRequest` үүсгэхэд `family_id` зайлшгүй шаардлагатай).
   - `daily_limit_minutes`, `weekend_bonus_minutes`, `warning_minutes`, `is_instant_locked`.
   - `schedules` (`List[ScheduleItemSchema]`) — ТВ төхөөрөмж интернэт тасарсан үед гараг болон цагийн цонхыг (`start_time` – `end_time`) локал тооцоолоход хэрэгтэй.

## 2.3. `FamilyScreenLauncherActivity.kt` дахь `onPause()` Логикийн Алдаа (Critical Bug)
1. Одоогийн [FamilyScreenLauncherActivity.kt](file:///c:/Users/enhtv/Documents/tv%20control/android_tv_box/app/src/main/java/mn/familyscreen/tv/ui/FamilyScreenLauncherActivity.kt#L132-L137) дээр:
   ```kotlin
   override fun onPause() {
       super.onPause()
       isPausedBySystem = true
       handler.removeCallbacks(tickerRunnable)
   }
   ```
   гэж бичигдсэн байна.
2. **Асуудал:** Хүүхэд Launcher дээрээс зөвшөөрөгдсөн апп (жишээ нь `YouTube Kids` эсвэл `Khan Academy`) нээх үед `FamilyScreenLauncherActivity` нь background руу орж `onPause()` дуудагдана. Яг энэ үед хүүхэд контент үзэж эхэлж байхад тоолуур зогсчихдог! Харин Launcher дээрээ юу ч үзээгүй зогсож байхад (`onResume()`) тоолуур явж байсан нь PRD-ийн 5-р бүлгийн *"Хугацаа тооцохдоо зөвхөн төхөөрөмжийн асаалттай байсан хугацааг хэрэглээ гэж тооцохгүй. Харин бодитоор хяналттай орчинд контент идэвхтэй ашигласан хугацааг бүртгэнэ"* гэсэн шаардлагатай зөрчилдөж байна.
3. **Зөв шийдэл:**
   - Тоолуур болон Whitelist/Block хяналт нь `Activity`-ийн `onPause()`-аас хамаарахгүйгээр `UsageMonitoringService` (Foreground Service + `UsageStatsManager` / `PowerManager.isInteractive`) дотор ажиллах ёстой.
   - Зөвхөн дэлгэц асаалттай (`isInteractive == true`) бөгөөд зөвшөөрөгдсөн контентын апп foreground-д идэвхтэй ажиллаж байх үед хэрэглээний секундийг тоолно. Төхөөрөмж унтарсан/standby (`SCREEN_OFF`) эсвэл зөвшөөрөгдсөн апп хаагдсан үед тоолуур зогсоно.
   - Хэрэв хүүхэд зөвшөөрөлгүй апп руу шилжих эсвэл хугацаа дуусах (`BLOCK`) үед `FamilyScreenLauncherActivity`-г `FLAG_ACTIVITY_NEW_TASK | FLAG_ACTIVITY_CLEAR_TOP` тугтайгаар шууд дэлгэцийн өмнө гаргаж блоклоно.

## 2.4. Offline Storage, Queue & Reboot Restoration Зөрүү
1. Одоогийн Android TV Box кодод SQLite (`SQLiteOpenHelper`), SharedPreferences кэш, сүлжээний клиент (`HttpURLConnection` + Exponential Backoff), болон `BOOT_COMPLETED` BroadcastReceiver огт байхгүй байна.
2. Төхөөрөмж унтарч асах (`ACTION_BOOT_COMPLETED`) үед хамгийн сүүлд хадгалсан `LocalPolicySnapshot` болон өнөөдрийн зарцуулсан хугацааг SQLite/SharedPreferences-ээс сэргээж ачаалах ёстой.

## 2.5. Системийн цаг өөрчлөх (Time Manipulation) Эрсдэлийн Шалгалт
1. Хэрэв хүүхэд Android TV-ийн системийн цагийг (wall-clock `System.currentTimeMillis()`) ухраавал (жишээ нь 20:00 цагийг 15:00 болгох эсвэл огноог өчигдөр болгох):
   - Одоогийн `LocalTimeEngine` нь зөвхөн `withinScheduleWindow: Boolean` тогтмол утга авч байсан.
   - **Шийдэл:** Сервертэй синхрончлох үед серверийн UTC цаг (`serverTimeUtcMs`) болон тухайн мөчийн төхөөрөмжийн monotonic цаг (`syncElapsedRealtimeMs = SystemClock.elapsedRealtime()`)-ийг хослуулан хадгална. Ингэснээр интернэтгүй байсан ч одоогийн жинхэнэ цагийг:
     $$\text{TrustedNowUtcMs} = \text{serverTimeUtcMs} + (\text{currentElapsedRealtimeMs} - \text{syncElapsedRealtimeMs})$$
     томьёогоор бодож гаргана. Хэрэглэгч ТВ-ийн системийн цагийг өөрчилсөн ч `TrustedNowUtcMs` өөрчлөгдөхгүй тул цагийн хуваарь болон өдрийн лимитийг тойрч гарах ямар ч боломжгүй болно.
