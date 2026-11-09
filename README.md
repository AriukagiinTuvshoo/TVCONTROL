# FamilyScreen — Хүүхдийн ТВ Хэрэглээний Ухаалаг Хяналтын Систем

> **Protect children's time, support healthy habits, empower parents.**  
> *Хүүхдийн цагийг хамгаалж, эрүүл дадлыг дэмжиж, эцэг эхэд хяналт өгнө.*

Энэхүү монорепо нь **FamilyScreen** бүтээгдэхүүний бүх бүрэлдэхүүн хэсгүүдийг багтаасан нэгдсэн эх код юм.

## Төслийн бүтэц (Monorepo Structure)

```text
tv control/
├── docs/
│   ├── 01-prd.md                        # Батлагдсан PRD v1.1 (01-р үе шат)
│   └── 02-architecture-and-database.md  # Системийн архитектур, DB & API загвар (02-р үе шат)
├── backend/                             # Cloud Backend & Authoritative Time Engine (Python FastAPI)
│   ├── app/
│   │   ├── main.py                      # FastAPI үндсэн сервер ба REST API endpoints
│   │   ├── models.py                    # SQLAlchemy ORM 13 хүснэгтийн загвар
│   │   ├── schemas.py                   # Pydantic v2 Request/Response валидацийн схемүүд
│   │   ├── time_engine.py               # Детерминистик Time Engine (ALLOW / WARNING / BLOCK)
│   │   ├── security.py                  # Password, PIN hash, Rate-limit хамгаалалт
│   │   └── database.py                  # PostgreSQL / SQLite өгөгдлийн сангийн тохиргоо
│   ├── tests/
│   │   └── test_familyscreen.py         # End-to-End болон Time Engine-ийн автомат тестүүд
│   └── requirements.txt
├── mobile_app/                          # Эцэг эхийн удирдлагын апп (Flutter — iOS / Android)
│   ├── pubspec.yaml
│   └── lib/
│       └── main.dart                    # Монгол хэл дээрх Parent Dashboard, Pairing, Whitelist, Override UI
└── android_tv_box/                      # Android TV App & FamilyScreen Box Launcher (Kotlin)
    └── app/src/main/
        ├── AndroidManifest.xml          # HOME Launcher, UsageStats, Overlay тохиргоо
        └── java/mn/familyscreen/tv/
            ├── engine/LocalTimeEngine.kt       # Offline-first Monotonic Time Engine
            └── ui/FamilyScreenLauncherActivity.kt # TV Launcher, Warning Banner, PIN Override Dialog
```

## Хөгжүүлэлтийн үе шатны явц

- [x] **01. PRD (v1.1)** — `docs/01-prd.md`
- [x] **02. Architecture & Database Design** — `docs/02-architecture-and-database.md`
- [x] **03. Development Environment & Monorepo** — Нэгдсэн бүтэц бэлэн
- [x] **04. Backend (FastAPI + 13 Tables)** — `backend/app/`
- [x] **05. Time Engine (`ALLOW` / `WARNING` / `BLOCK`)** — `backend/app/time_engine.py` ба `LocalTimeEngine.kt`
- [x] **06. Parent Mobile App (Flutter)** — `mobile_app/lib/main.dart`
- [x] **07 & 08. Android TV App & FamilyScreen Box Prototype (Kotlin)** — `android_tv_box/`
- [x] **09. Testing & Security** — Автомат тестүүд (`pytest`) болон PIN rate-limiting
