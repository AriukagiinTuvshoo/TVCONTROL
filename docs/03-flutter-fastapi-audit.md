# FAMILYSCREEN — Phase 1: Flutter ↔ FastAPI Интеграцийн Аудитын Тайлан

| Талбар | Утга |
|---|---|
| **Огноо** | 2026-11-08 |
| **Зорилго** | Flutter Parent App болон FastAPI Backend-ийн одоогийн байдлыг PRD v1.1 болон Архитектурын баримт бичигтэй тулган шалгах |
| **Төлөв** | Код өөрчлөхөөс өмнөх бүрэн аудит |

---

# 1. PRD v1.1 болон Архитектурын шаардлагын тойм

[01-prd.md](file:///c:/Users/enhtv/Documents/tv%20control/docs/01-prd.md) болон [02-architecture-and-database.md](file:///c:/Users/enhtv/Documents/tv%20control/docs/02-architecture-and-database.md)-д зааснаар Parent Mobile App болон Cloud Backend нь дараах үндсэн урсгалуудыг бодитоор гүйцэтгэх ёстой:
- **FR-01 Authentication:** Эцэг эх бүртгүүлэх (`/auth/register`), нэвтрэх (`/auth/login`), JWT/HMAC токен хадгалах, гарах.
- **FR-02 Child Profile:** Хүүхдийн профайл үүсгэх, жагсаалт харах, шинэчлэх/устгах (CRUD).
- **FR-03 Device Management:** QR / 6 оронтой кодоор ТВ холбох (`/devices/pair/init`, `/devices/pair/claim`), гэр бүлийн төхөөрөмжүүдийн жагсаалт харах, салгах.
- **FR-04 & FR-05 Daily Limit & Schedule:** Хүүхэд бүрийн өдрийн лимит, амралтын өдрийн бонус, гараг бүрийн цагийн хуваарь (`schedules`), шууд түгжих (`is_instant_locked`) тохиргоог унших ба хадгалах (`GET/PUT /policies/{child_id}`).
- **FR-07 PIN Override:** Алсаас (`REMOTE_APP`) +15, +30 минут нэмэх (`POST /overrides`) болон эцэг эхийн PIN код шинэчлэх.
- **FR-08 Usage Report:** 7 хоногийн болон өдрийн хэрэглээний тайлан, апп задаргааг серверээс татах (`GET /reports/summary`).
- **FR-10 Whitelist:** Зөвшөөрөгдсөн аппуудын (`allowed_apps`) жагсаалтыг серверээс унших, нэмэх/хасах, идэвхжүүлэх.
- **NFR-03 Security:** API дуудлага бүр `Authorization: Bearer <token>` шалгах ба нэг гэр бүлийн хэрэглэгч өөр гэр бүлийн өгөгдөлд (хүүхэд, дүрэм, төхөөрөмж, тайлан, override) хандах боломжгүй байх (**Tenant / Family Isolation**).

---

# 2. Backend (`backend/app/`) Аудит

Одоогийн [main.py](file:///c:/Users/enhtv/Documents/tv%20control/backend/app/main.py), [schemas.py](file:///c:/Users/enhtv/Documents/tv%20control/backend/app/schemas.py), [security.py](file:///c:/Users/enhtv/Documents/tv%20control/backend/app/security.py) файлуудыг шалгахад дараах endpoint-ууд байна:

| Endpoint | Одоогийн төлөв | Илэрсэн дутагдал / Зөрүү |
|---|---|---|
| `POST /api/v1/auth/register` | Ажиллаж байгаа | Хэвийн. Токен болон `user`, `family` буцаадаг. |
| `POST /api/v1/auth/login` | Ажиллаж байгаа | Хэвийн. |
| `GET /api/v1/auth/me` | **Байхгүй** | Апп дахин асах үед хадгалсан токеноор хэрэглэгч/гэр бүлийн мэдээллийг сэргээх endpoint хэрэгтэй. |
| `POST /api/v1/children` | Ажиллаж байгаа | **Auth/Authorization шалгалт байхгүй.** |
| `GET /api/v1/families/{family_id}/children` | Ажиллаж байгаа | **Auth шалгалт байхгүй**; мөн Dashboard дээр хүүхдийн өнөөдрийн `time_state` (үлдсэн хугацаа, зарцуулсан хугацаа, төлөв)-ийг хамт авах эсвэл тусдаа endpoint-оор авах шаардлагатай. |
| `PATCH /api/v1/children/{child_id}` & `DELETE /api/v1/children/{child_id}` | **Байхгүй** | Child CRUD бүрэн байхын тулд хүүхдийн нэр/нас/зураг/лимит засах болон профайл устгах endpoint дутуу байна. |
| `GET /api/v1/policies/{child_id}` & `PUT /api/v1/policies/{child_id}` | Ажиллаж байгаа | **Auth/Family isolation шалгалт байхгүй.** |
| `POST /api/v1/devices/pair/init` & `POST /api/v1/devices/pair/claim` | Ажиллаж байгаа | `claim` дээр Auth болон `active_child_id` нь тухайн гэр бүлийн хүүхэд мөн эсэхийг шалгах шаардлагатай. |
| `GET /api/v1/families/{family_id}/devices` & `DELETE /api/v1/devices/{device_id}` | **Байхгүй** | PRD FR-03 болон 6.4-т заасан төхөөрөмжийн жагсаалт харах, төхөөрөмж салгах (unpair/delete) endpoint дутуу байна. |
| `POST /api/v1/overrides` | Ажиллаж байгаа | `REMOTE_APP` үед Bearer token-оор тухайн гэр бүлийн эцэг эх мөн эсэхийг заавал шалгах ёстой. |
| `PUT /api/v1/families/{family_id}/pin` | **Байхгүй** | Flutter аппын "PIN Settings" дэлгэцээс эцэг эхийн PIN кодыг шинэчлэх endpoint дутуу байна. |
| `GET /api/v1/reports/summary` & `GET /api/v1/families/{family_id}/notifications` | Ажиллаж байгаа | **Auth/Family isolation шалгалт байхгүй.** |

### Backend-ийн Аюулгүй байдлын гол зөрүү (Critical Security Gap):
1. [security.py](file:///c:/Users/enhtv/Documents/tv%20control/backend/app/security.py) дотор `generate_access_token(user_id, family_id)` функц байгаа боловч токены гарын үсгийг (HMAC-SHA256) буцааж шалгадаг `verify_access_token(token)` функц болон FastAPI-ийн `Depends(get_current_principal)` dependency огт бичигдээгүй байна.
2. Үүний улмаас одоогоор нэг гэр бүлийн хэрэглэгч өөр гэр бүлийн `family_id` эсвэл `child_id`-г URL-д дамжуулахад **403 Forbidden** буцаахгүй, шууд уншиж/засах эрсдэлтэй байна.

---

# 3. Flutter Mobile App (`mobile_app/`) Аудит

Одоогийн [mobile_app/lib/main.dart](file:///c:/Users/enhtv/Documents/tv%20control/mobile_app/lib/main.dart) болон [pubspec.yaml](file:///c:/Users/enhtv/Documents/tv%20control/mobile_app/pubspec.yaml)-ийг шалгахад:

1. **API Client байхгүй:** `pubspec.yaml` дотор `http: ^1.2.1` багц зарлагдсан боловч `lib/` дотор HTTP хүсэлт илгээдэг ямар ч сервис эсвэл API client байхгүй.
2. **Бүх өгөгдөл Hardcoded (Mock):** `_children` (`Тэмүүлэн`, `Мишээл`), `_apps`, `_parentPin = '2580'`, `_pairedDeviceName`, болон 7 хоногийн тайлангийн тоонууд бүгд санах ой дахь тогтмол (in-memory mock) утгууд байна.
3. **Authentication UI болон Token хадгалалт байхгүй:** Апп шууд `ParentHomeShell` рүү ордог; Login / Register дэлгэц болон токен хадгалах (`TokenStorage`) механизм байхгүй.
4. **Environment Configuration байхгүй:** `--dart-define=API_BASE_URL=...` эсвэл локал/эмулятор орчны Base URL тохиргоо байхгүй.
5. **Loading / Error / Empty State байхгүй:** Сүлжээний хүсэлт явах үеийн унших төлөв, алдаа гарсан үед Монгол хэлээр харуулах болон дахин оролдох (`Retry`), эсвэл хүүхэд/төхөөрөмж нэмээгүй үеийн хоосон төлөв (`Empty State`) байхгүй.

---

# 4. Backend ба Flutter хоорондын зөрүүг арилгах шийдэл (Phase 2 Төлөвлөгөө)

1. **Backend (`backend/app/`):**
   - `security.py`: `verify_access_token` болон FastAPI `HTTPBearer` суурьтай `get_current_auth` dependency нэмэх.
   - Бүх эцэг эхийн endpoint-ууд дээр **Authentication (`401 Unauthorized`)** болон **Family Isolation (`403 Forbidden`)** шалгалтыг хатуу хэрэгжүүлэх.
   - Дутуу байсан endpoint-уудыг нэмэх:
     - `GET /api/v1/auth/me`
     - `PATCH /api/v1/children/{child_id}` ба `DELETE /api/v1/children/{child_id}` (мөн `ChildOut` дотор өнөөдрийн `time_state`-ийг хавсаргах)
     - `GET /api/v1/families/{family_id}/devices` ба `DELETE /api/v1/devices/{device_id}`
     - `PUT /api/v1/families/{family_id}/pin`
2. **Flutter (`mobile_app/lib/`):**
   - `lib/config/env.dart` — `String.fromEnvironment('API_BASE_URL', defaultValue: 'http://127.0.0.1:8000')` тохиргоо.
   - `lib/models/api_models.dart` — Backend-ийн Pydantic схемтэй 1:1 таарах Dart моделууд.
   - `lib/services/token_storage.dart` — Аюулгүй токен хадгалах давхарга.
   - `lib/services/api_client.dart` — Бүх REST endpoint-уудтай холбогдох, Монгол хэлээрх алдааны мессеж задлах (`ApiException`) бүрэн HTTP клиент.
   - `lib/main.dart` — Бодит Login/Register дэлгэц, Child CRUD (нэмэх, засах, устгах), Device Pairing (`init` симуляци болон `claim`, жагсаалт, салгах), Policy & Schedule серверт хадгалах, Whitelist удирдах, Remote `+15`/`+30` мин Override, Бодит Usage Report болон Loading/Empty/Error төлөвүүд.
