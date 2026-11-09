"""FamilyScreen Cloud Backend — FastAPI Application & REST API v1."""

from __future__ import annotations

import hmac
import os
from datetime import datetime, time, timedelta, timezone
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import (
    AllowedApp,
    Child,
    Device,
    DevicePairing,
    Family,
    FamilyMember,
    Notification,
    Override,
    Policy,
    Schedule,
    UsageEvent,
    UsageSession,
    User,
)
from .schemas import (
    AllowedAppItemSchema,
    AppBreakdownItem,
    AuthResponse,
    ChildCreateRequest,
    ChildOut,
    ChildUpdateRequest,
    DailyUsageItem,
    DeviceOut,
    DevicePairClaimRequest,
    DevicePairInitRequest,
    DevicePairInitResponse,
    DevicePairStatusResponse,
    DeviceSyncResponse,
    FamilyOut,
    LoginRequest,
    NotificationOut,
    OverrideCreateRequest,
    OverrideResponse,
    PinInitRequest,
    PinUpdateRequest,
    PinUpdateResponse,
    PolicyOut,
    PolicyUpdateRequest,
    RegisterRequest,
    ScheduleItemSchema,
    SupabaseAccountLinkRequest,
    SupabaseSyncRequest,
    TimeStateOut,
    UsageReportResponse,
    UsageSessionCreateRequest,
    UsageSessionResponse,
    UserOut,
)
from .security import (
    MAX_PIN_ATTEMPTS,
    AuthPrincipal,
    DevicePrincipal,
    compute_lockout_expiry,
    ensure_device_access,
    ensure_family_access,
    generate_access_token,
    generate_device_token,
    generate_pairing_code,
    get_current_principal,
    get_optional_device_principal,
    get_optional_principal,
    hash_secret,
    is_pin_locked,
    sha256_hex,
    verify_secret,
)
from .migrations import init_db, run_migrations
from .time_engine import (
    ScheduleWindow,
    TimeEngineInput,
    evaluate_time_engine,
    parse_warning_csv,
    resolve_local_datetime,
)

# Safely initialize database schema and migrations under advisory lock.
# In production, migrations can optionally be executed out-of-band (e.g. via CLI or Kubernetes initContainer)
# by setting FAMILYSCREEN_SKIP_STARTUP_MIGRATIONS=true.
SKIP_STARTUP_MIGRATIONS = os.getenv("FAMILYSCREEN_SKIP_STARTUP_MIGRATIONS", "false").lower() in ("true", "1")
if not SKIP_STARTUP_MIGRATIONS:
    try:
        init_db(engine)
    except Exception as exc:
        import logging
        logging.getLogger("familyscreen.startup").critical(
            "CRITICAL STARTUP ERROR: Database initialization / migration failed: %s", exc, exc_info=True
        )
        raise RuntimeError(f"Database initialization failed: {exc}") from exc

app = FastAPI(
    title="FamilyScreen Cloud API",
    version="1.3.0",
    description="Parental Control & Digital Wellbeing Ecosystem for Android TV & FamilyScreen Box",
)

# Production-grade CORS policy: configurable via FAMILYSCREEN_ALLOWED_ORIGINS
allowed_origins_raw = os.getenv("FAMILYSCREEN_ALLOWED_ORIGINS")
if allowed_origins_raw:
    origins = [orig.strip() for orig in allowed_origins_raw.split(",") if orig.strip()]
else:
    origins = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
        "http://10.0.2.2:8000",
        "https://app.familyscreen.mn",
        "https://familyscreen.mn",
    ]

# If wildcard "*" is explicitly supplied, allow_credentials must be False per the CORS spec
allow_credentials = "*" not in origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


DEFAULT_ALLOWED_APPS = [
    ("com.google.android.apps.youtube.kids", "YouTube Kids", "VIDEO"),
    ("org.khanacademy.android", "Khan Academy", "EDUCATION"),
    ("com.duolingo", "Duolingo", "EDUCATION"),
]


def _create_notification(
    db: Session,
    family_id: str,
    notif_type: str,
    title: str,
    body: str,
) -> Notification:
    notif = Notification(
        family_id=family_id,
        type=notif_type,
        title=title,
        body=body,
    )
    db.add(notif)
    return notif


def _verify_device_auth_if_needed(
    device: Device,
    device_principal: Optional[DevicePrincipal],
    parent_principal: Optional[AuthPrincipal],
) -> None:
    """Enforce device or parent authorization whenever a device has an active device_token_hash."""
    if parent_principal is not None:
        if device.family_id:
            ensure_family_access(parent_principal, device.family_id)
        return

    if device_principal is not None:
        ensure_device_access(device_principal, device.id, device.family_id)
        return

    # If the device was issued a token on claim/status, require authentication
    if device.device_token_hash is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Төхөөрөмжийн токен (X-Device-Token) шаардлагатай байна.",
        )


def _compute_child_time_state(
    db: Session,
    child: Child,
    family: Family,
    now_utc: Optional[datetime] = None,
) -> TimeStateOut:
    """Gather policy, schedules, today's usage and overrides, then run Time Engine."""
    policy = child.policy
    if policy is None:
        raise HTTPException(status_code=404, detail="Хүүхдийн хугацааны дүрэм олдсонгүй.")

    now_local = resolve_local_datetime(now_utc, family.timezone)
    today_date = now_local.date()

    used_seconds = (
        db.scalar(
            select(func.coalesce(func.sum(UsageSession.active_seconds), 0)).where(
                UsageSession.child_id == child.id,
                UsageSession.usage_date == today_date,
            )
        )
        or 0
    )

    override_minutes = (
        db.scalar(
            select(func.coalesce(func.sum(Override.added_minutes), 0)).where(
                Override.child_id == child.id,
                Override.override_date == today_date,
            )
        )
        or 0
    )

    schedule_windows = [
        ScheduleWindow(
            day_of_week=s.day_of_week,
            is_school_day=s.is_school_day,
            start_time=s.start_time,
            end_time=s.end_time,
            is_enabled=s.is_enabled,
        )
        for s in policy.schedules
    ]

    engine_input = TimeEngineInput(
        daily_limit_minutes=policy.daily_limit_minutes,
        weekend_bonus_minutes=policy.weekend_bonus_minutes,
        warning_minutes=parse_warning_csv(policy.warning_minutes_csv),
        is_instant_locked=policy.is_instant_locked,
        schedules=schedule_windows,
        used_seconds_today=int(used_seconds),
        override_minutes_today=int(override_minutes),
        family_timezone=family.timezone,
        now_utc=now_utc,
    )

    res = evaluate_time_engine(engine_input)
    return TimeStateOut(
        state=res.state,
        reason=res.reason,
        local_date=res.local_date,
        local_time_str=res.local_time_str,
        allowed_seconds_today=res.allowed_seconds_today,
        used_seconds_today=res.used_seconds_today,
        override_seconds_today=res.override_seconds_today,
        remaining_seconds_today=res.remaining_seconds_today,
        schedule_remaining_seconds=res.schedule_remaining_seconds,
        effective_remaining_seconds=res.effective_remaining_seconds,
        active_warning_minutes=res.active_warning_minutes,
        next_warning_at_remaining_seconds=res.next_warning_at_remaining_seconds,
    )


def _serialize_child(db: Session, child: Child, family: Family) -> ChildOut:
    policy = child.policy
    time_state = _compute_child_time_state(db, child, family) if policy else None
    return ChildOut(
        id=child.id,
        family_id=child.family_id,
        nickname=child.nickname,
        age_group=child.age_group,
        avatar_key=child.avatar_key,
        is_active=child.is_active,
        policy_id=policy.id if policy else None,
        daily_limit_minutes=policy.daily_limit_minutes if policy else 90,
        is_instant_locked=policy.is_instant_locked if policy else False,
        time_state=time_state,
    )


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok", "service": "FamilyScreen API", "version": "1.3.0"}


# ---------------------------------------------------------------------------
# FR-01: User Authentication & Family Onboarding
# ---------------------------------------------------------------------------


@app.post("/api/v1/auth/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register_parent(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    existing = db.scalar(select(User).where(User.email == payload.email.lower().strip()))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Энэ имэйл хаягаар бүртгэл үүссэн байна.",
        )

    user = User(
        email=payload.email.lower().strip(),
        phone=payload.phone,
        password_hash=hash_secret(payload.password),
        full_name=payload.full_name.strip(),
    )
    family = Family(
        name=payload.family_name.strip(),
        timezone=payload.timezone,
        plan_tier="FREE",
        pin_hash=hash_secret(payload.pin_code),
    )
    db.add_all([user, family])
    db.flush()

    membership = FamilyMember(
        family_id=family.id,
        user_id=user.id,
        role="OWNER",
    )
    db.add(membership)
    db.commit()
    db.refresh(user)
    db.refresh(family)

    token = generate_access_token(user.id, family.id)
    return AuthResponse(
        access_token=token,
        user=UserOut.model_validate(user),
        family=FamilyOut.model_validate(family),
    )


@app.post("/api/v1/auth/login", response_model=AuthResponse)
def login_parent(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower().strip()))
    if not user or not verify_secret(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Имэйл эсвэл нууц үг буруу байна.",
        )

    membership = db.scalar(select(FamilyMember).where(FamilyMember.user_id == user.id))
    if not membership:
        raise HTTPException(status_code=404, detail="Гэр бүлийн бүртгэл олдсонгүй.")

    family = db.get(Family, membership.family_id)
    token = generate_access_token(user.id, family.id)
    return AuthResponse(
        access_token=token,
        user=UserOut.model_validate(user),
        family=FamilyOut.model_validate(family),
    )


def _provision_supabase_family(
    db: Session,
    principal: AuthPrincipal,
    custom_family_name: Optional[str] = None,
    custom_pin: Optional[str] = None,
    timezone_str: Optional[str] = None,
) -> tuple[User, Family]:
    """Idempotently and concurrency-safely provision or retrieve User and Family for a Supabase parent."""
    # 1. Search existing user strictly by verified Supabase sub or primary ID
    user = db.scalar(
        select(User).where((User.supabase_sub == principal.user_id) | (User.id == principal.user_id))
    )

    # 2. Prevent account takeover: if local account exists with same email, do NOT auto-link!
    if not user and principal.email:
        existing_by_email = db.scalar(select(User).where(User.email == principal.email.lower().strip()))
        if existing_by_email:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ACCOUNT_LINKING_REQUIRED: Энэ имэйл хаягтай дотоод хэрэглэгчийн бүртгэл байна. Нууц үгээ баталгаажуулж дансаа холбоно уу.",
            )

    if user:
        membership = db.scalar(select(FamilyMember).where(FamilyMember.user_id == user.id))
        if membership:
            family = db.scalar(select(Family).where(Family.id == membership.family_id).with_for_update())
            if family:
                # If custom PIN explicitly provided and family PIN was unconfigured, set it
                if custom_pin and not family.has_pin_configured:
                    family.pin_hash = hash_secret(custom_pin)
                    family.pin_failed_attempts = 0
                    family.pin_locked_until = None
                    db.commit()
                    db.refresh(family)
                return user, family
        else:
            # User exists but membership does not exist yet (e.g. manual seed or partial migration)
            family = db.get(Family, principal.family_id) if principal.family_id else None
            if not family:
                family = Family(
                    name=custom_family_name or f"{user.full_name}-н гэр бүл",
                    timezone=timezone_str or "Asia/Ulaanbaatar",
                    plan_tier="FREE",
                    pin_hash=hash_secret(custom_pin) if custom_pin else None,
                )
                db.add(family)
                db.flush()
            membership = FamilyMember(family_id=family.id, user_id=user.id, role="OWNER")
            db.add(membership)
            db.commit()
            db.refresh(family)
            return user, family

    # 3. If user does not exist, provision new User and Family with race-condition collision handling
    user_email = (principal.email or f"{principal.user_id}@supabase.familyscreen.mn").lower().strip()
    user_name = principal.full_name or "Эцэг эх"
    family_name = custom_family_name or f"{user_name}-н гэр бүл"
    pin_hash = hash_secret(custom_pin) if custom_pin else None
    tz = timezone_str or "Asia/Ulaanbaatar"

    try:
        user = User(
            id=principal.user_id,
            supabase_sub=principal.user_id,
            email=user_email,
            password_hash="supabase_managed_auth",
            full_name=user_name,
        )
        db.add(user)

        family = Family(
            name=family_name,
            timezone=tz,
            plan_tier="FREE",
            pin_hash=pin_hash,
        )
        db.add(family)
        db.flush()

        membership = FamilyMember(
            family_id=family.id,
            user_id=user.id,
            role="OWNER",
        )
        db.add(membership)
        db.commit()
        db.refresh(user)
        db.refresh(family)
        return user, family
    except IntegrityError:
        # Concurrent request already committed or is in the process of committing the user or membership
        db.rollback()
        import time
        for _ in range(5):
            time.sleep(0.05)
            existing_user = db.scalar(
                select(User).where(
                    (User.supabase_sub == principal.user_id)
                    | (User.id == principal.user_id)
                    | (User.email == user_email)
                )
            )
            if existing_user:
                m = db.scalar(select(FamilyMember).where(FamilyMember.user_id == existing_user.id))
                if m:
                    existing_family = db.get(Family, m.family_id)
                    if existing_family:
                        return existing_user, existing_family
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Зэрэгцээ хүсэлтийн зөрчил гарлаа. Түр хүлээгээд дахин оролдоно уу.",
        )


@app.get("/api/v1/auth/me", response_model=AuthResponse)
def get_current_session(
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AuthResponse:
    user = db.scalar(
        select(User).where((User.supabase_sub == principal.user_id) | (User.id == principal.user_id))
    )
    family = None
    if user:
        membership = db.scalar(select(FamilyMember).where(FamilyMember.user_id == user.id))
        if membership:
            family = db.get(Family, membership.family_id)

    if not user or not family:
        # If authenticated via Supabase, automatically JIT-provision initial account
        if principal.auth_provider == "supabase":
            user, family = _provision_supabase_family(db, principal)
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Хэрэглэгч олдсонгүй.")

    token = generate_access_token(user.id, family.id)
    return AuthResponse(
        access_token=token,
        user=UserOut.model_validate(user),
        family=FamilyOut.model_validate(family),
    )


@app.post("/api/v1/auth/supabase/sync", response_model=AuthResponse)
def sync_supabase_parent_profile(
    payload: SupabaseSyncRequest,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AuthResponse:
    if principal.auth_provider != "supabase":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Энэ үйлдлийг зөвхөн Supabase нэвтрэлттэй хэрэглэгч дуудах боломжтой.",
        )
    user, family = _provision_supabase_family(
        db=db,
        principal=principal,
        custom_family_name=payload.family_name,
        custom_pin=payload.pin_code,
        timezone_str=payload.timezone,
    )
    token = generate_access_token(user.id, family.id)
    return AuthResponse(
        access_token=token,
        user=UserOut.model_validate(user),
        family=FamilyOut.model_validate(family),
    )


@app.post("/api/v1/auth/supabase/link-account", response_model=AuthResponse)
def link_supabase_account(
    payload: SupabaseAccountLinkRequest,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AuthResponse:
    """Explicitly link an existing local account to a verified Supabase login by proving local credentials."""
    if principal.auth_provider != "supabase":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Зөвхөн Supabase нэвтрэлттэй үед данс холбох боломжтой.",
        )

    if not principal.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Supabase токенд имэйл хаяг олдсонгүй.",
        )

    if not principal.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Supabase имэйл хаяг баталгаажаагүй байна. Эхлээд имэйлээ баталгаажуулна уу.",
        )

    norm_email = principal.email.lower().strip()
    # Acquire row-level lock on the target local user to serialize concurrent link requests
    local_user = db.scalar(select(User).where(User.email == norm_email).with_for_update())
    if not local_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Холбох дотоод хэрэглэгчийн бүртгэл олдсонгүй.",
        )

    if local_user.supabase_sub and local_user.supabase_sub != principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Энэ бүртгэл аль хэдийн өөр Supabase данстай холбогдсон байна.",
        )

    if not verify_secret(payload.local_password, local_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Дотоод хэрэглэгчийн нууц үг буруу байна.",
        )

    # Atomic conditional update prevents race conditions when concurrent requests attempt to link
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Энэ бүртгэл аль хэдийн өөр Supabase данстай холбогдсон байна.",
        )

    try:
        db.commit()
        db.refresh(local_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Энэ Supabase данс аль хэдийн өөр бүртгэлтэй холбогдсон байна.",
        )

    membership = db.scalar(select(FamilyMember).where(FamilyMember.user_id == local_user.id))
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Холбогдсон хэрэглэгчийн гэр бүлийн мэдээлэл олдсонгүй.",
        )
    family = db.get(Family, membership.family_id)
    if not family:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Гэр бүл олдсонгүй.",
        )

    token = generate_access_token(local_user.id, family.id)
    return AuthResponse(
        access_token=token,
        user=UserOut.model_validate(local_user),
        family=FamilyOut.model_validate(family),
    )


@app.post("/api/v1/families/{family_id}/pin/init", response_model=PinUpdateResponse)
def initialize_family_pin(
    family_id: str,
    payload: PinInitRequest,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> PinUpdateResponse:
    """Explicitly initialize the parent PIN for a newly created family (owner only, concurrency-safe)."""
    ensure_family_access(principal, family_id, db=db)
    
    # Acquire row-level lock on Family row to serialize concurrent init calls
    family = db.scalar(select(Family).where(Family.id == family_id).with_for_update())
    if not family:
        raise HTTPException(status_code=404, detail="Гэр бүл олдсонгүй.")

    db_user = db.scalar(
        select(User).where((User.supabase_sub == principal.user_id) | (User.id == principal.user_id))
    )
    effective_user_id = db_user.id if db_user else principal.user_id

    membership = db.scalar(
        select(FamilyMember).where(
            FamilyMember.family_id == family_id,
            FamilyMember.user_id == effective_user_id,
        )
    )
    if not membership or membership.role != "OWNER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Зөвхөн гэр бүлийн эзэмшигч (OWNER) PIN код анх тохируулах эрхтэй.",
        )

    if family.has_pin_configured:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PIN код аль хэдийн тохируулагдсан байна. Шинэчлэхийн тулд одоогийн PIN кодоо ашиглана уу.",
        )

    # Atomic conditional update prevents concurrent initialization race condition
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PIN код аль хэдийн тохируулагдсан байна. Шинэчлэхийн тулд одоогийн PIN кодоо ашиглана уу.",
        )
    db.commit()

    return PinUpdateResponse(
        family_id=family.id,
        message="Эцэг эхийн PIN код амжилттай тохируулагдлаа.",
    )


@app.put("/api/v1/families/{family_id}/pin", response_model=PinUpdateResponse)
def update_family_pin(
    family_id: str,
    payload: PinUpdateRequest,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> PinUpdateResponse:
    """Update existing parent PIN requiring OWNER role, current PIN verification, and rate-limiting lockout."""
    ensure_family_access(principal, family_id, db=db)
    
    # Acquire row-level lock on Family row to prevent race conditions during updates & lockout increments
    family = db.scalar(select(Family).where(Family.id == family_id).with_for_update())
    if not family:
        raise HTTPException(status_code=404, detail="Гэр бүл олдсонгүй.")

    # Role check: Require OWNER role consistent with PRD FR-01 and FR-07
    db_user = db.scalar(
        select(User).where((User.supabase_sub == principal.user_id) | (User.id == principal.user_id))
    )
    effective_user_id = db_user.id if db_user else principal.user_id

    membership = db.scalar(
        select(FamilyMember).where(
            FamilyMember.family_id == family_id,
            FamilyMember.user_id == effective_user_id,
        )
    )
    if not membership or membership.role != "OWNER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Зөвхөн гэр бүлийн эзэмшигч (OWNER) PIN код өөрчлөх эрхтэй.",
        )

    if not family.has_pin_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PIN код хараахан тохируулаагүй байна. /pin/init endpoint-ийг ашиглана уу.",
        )

    now_utc = datetime.now(timezone.utc)
    if is_pin_locked(family.pin_locked_until, now_utc):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Олон удаа буруу оруулсан тул PIN код 15 минут түр түгжигдсэн байна.",
        )

    if not payload.current_pin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Одоогийн PIN кодыг заавал оруулах шаардлагатай.",
        )

    if not verify_secret(payload.current_pin, family.pin_hash):
        family.pin_failed_attempts += 1
        if family.pin_failed_attempts >= MAX_PIN_ATTEMPTS:
            family.pin_locked_until = compute_lockout_expiry(now_utc)
        db.commit()
        if family.pin_failed_attempts >= MAX_PIN_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="PIN кодыг 5 удаа буруу оруулсан тул 15 минут түгжигдлээ.",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Одоогийн PIN код буруу байна.",
        )

    family.pin_hash = hash_secret(payload.new_pin)
    family.pin_failed_attempts = 0
    family.pin_locked_until = None
    db.commit()

    return PinUpdateResponse(
        family_id=family.id,
        message="Эцэг эхийн PIN код амжилттай шинэчлэгдлээ.",
    )


# ---------------------------------------------------------------------------
# FR-02, FR-04, FR-05, FR-06, FR-10: Child Profile CRUD, Policy, Schedule, Whitelist
# ---------------------------------------------------------------------------


@app.post("/api/v1/children", response_model=ChildOut, status_code=status.HTTP_201_CREATED)
def create_child(
    payload: ChildCreateRequest,
    principal: Optional[AuthPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> ChildOut:
    if principal is not None:
        ensure_family_access(principal, payload.family_id)

    family = db.get(Family, payload.family_id)
    if not family:
        raise HTTPException(status_code=404, detail="Гэр бүл олдсонгүй.")

    child = Child(
        family_id=family.id,
        nickname=payload.nickname.strip(),
        age_group=payload.age_group,
        avatar_key=payload.avatar_key,
    )
    db.add(child)
    db.flush()

    policy = Policy(
        family_id=family.id,
        child_id=child.id,
        daily_limit_minutes=payload.daily_limit_minutes,
        weekend_bonus_minutes=0,
        warning_minutes_csv="15,5,1",
        enforce_whitelist=True,
    )
    db.add(policy)
    db.flush()

    for day_idx in range(7):
        db.add(
            Schedule(
                policy_id=policy.id,
                day_of_week=day_idx,
                is_school_day=day_idx < 5,
                start_time=time(8, 0),
                end_time=time(21, 0),
                is_enabled=True,
            )
        )

    for pkg, label, cat in DEFAULT_ALLOWED_APPS:
        db.add(
            AllowedApp(
                policy_id=policy.id,
                package_name=pkg,
                app_label=label,
                category=cat,
                is_allowed=True,
            )
        )

    db.commit()
    db.refresh(child)

    return _serialize_child(db, child, family)


@app.get("/api/v1/families/{family_id}/children", response_model=List[ChildOut])
def list_children(
    family_id: str,
    principal: Optional[AuthPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> List[ChildOut]:
    if principal is not None:
        ensure_family_access(principal, family_id)

    family = db.get(Family, family_id)
    if not family:
        raise HTTPException(status_code=404, detail="Гэр бүл олдсонгүй.")

    children = db.scalars(select(Child).where(Child.family_id == family_id)).all()
    return [_serialize_child(db, c, family) for c in children]


@app.patch("/api/v1/children/{child_id}", response_model=ChildOut)
def update_child(
    child_id: str,
    payload: ChildUpdateRequest,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> ChildOut:
    child = db.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Хүүхдийн профайл олдсонгүй.")
    ensure_family_access(principal, child.family_id)

    if payload.nickname is not None:
        child.nickname = payload.nickname.strip()
    if payload.age_group is not None:
        child.age_group = payload.age_group
    if payload.avatar_key is not None:
        child.avatar_key = payload.avatar_key
    if payload.daily_limit_minutes is not None and child.policy is not None:
        child.policy.daily_limit_minutes = payload.daily_limit_minutes
        child.policy.version += 1

    db.commit()
    db.refresh(child)
    family = db.get(Family, child.family_id)
    return _serialize_child(db, child, family)


@app.delete("/api/v1/children/{child_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_child(
    child_id: str,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> Response:
    child = db.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Хүүхдийн профайл олдсонгүй.")
    ensure_family_access(principal, child.family_id)

    db.delete(child)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/v1/policies/{child_id}", response_model=PolicyOut)
def get_child_policy(
    child_id: str,
    principal: Optional[AuthPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> PolicyOut:
    policy = db.scalar(select(Policy).where(Policy.child_id == child_id))
    if not policy:
        raise HTTPException(status_code=404, detail="Дүрэм олдсонгүй.")
    if principal is not None:
        ensure_family_access(principal, policy.family_id)

    family = db.get(Family, policy.family_id)
    child = db.get(Child, policy.child_id)
    time_state = _compute_child_time_state(db, child, family) if (family and child) else None

    return PolicyOut(
        id=policy.id,
        family_id=policy.family_id,
        child_id=policy.child_id,
        daily_limit_minutes=policy.daily_limit_minutes,
        weekend_bonus_minutes=policy.weekend_bonus_minutes,
        warning_minutes=parse_warning_csv(policy.warning_minutes_csv),
        enforce_whitelist=policy.enforce_whitelist,
        is_instant_locked=policy.is_instant_locked,
        version=policy.version,
        schedules=[
            ScheduleItemSchema(
                day_of_week=s.day_of_week,
                is_school_day=s.is_school_day,
                start_time=s.start_time,
                end_time=s.end_time,
                is_enabled=s.is_enabled,
            )
            for s in sorted(policy.schedules, key=lambda x: x.day_of_week)
        ],
        allowed_apps=[
            AllowedAppItemSchema(
                package_name=a.package_name,
                app_label=a.app_label,
                category=a.category,
                is_allowed=a.is_allowed,
            )
            for a in policy.allowed_apps
        ],
        time_state=time_state,
    )


@app.put("/api/v1/policies/{child_id}", response_model=PolicyOut)
def update_child_policy(
    child_id: str,
    payload: PolicyUpdateRequest,
    principal: Optional[AuthPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> PolicyOut:
    policy = db.scalar(select(Policy).where(Policy.child_id == child_id))
    if not policy:
        raise HTTPException(status_code=404, detail="Дүрэм олдсонгүй.")
    if principal is not None:
        ensure_family_access(principal, policy.family_id)

    policy.daily_limit_minutes = payload.daily_limit_minutes
    policy.weekend_bonus_minutes = payload.weekend_bonus_minutes
    policy.warning_minutes_csv = ",".join(str(x) for x in sorted(set(payload.warning_minutes), reverse=True))
    policy.enforce_whitelist = payload.enforce_whitelist
    policy.is_instant_locked = payload.is_instant_locked
    policy.version += 1

    if payload.schedules is not None:
        policy.schedules.clear()
        db.flush()
        for s_item in payload.schedules:
            policy.schedules.append(
                Schedule(
                    day_of_week=s_item.day_of_week,
                    is_school_day=s_item.is_school_day,
                    start_time=s_item.start_time,
                    end_time=s_item.end_time,
                    is_enabled=s_item.is_enabled,
                )
            )

    if payload.allowed_apps is not None:
        policy.allowed_apps.clear()
        db.flush()
        for app_item in payload.allowed_apps:
            policy.allowed_apps.append(
                AllowedApp(
                    package_name=app_item.package_name,
                    app_label=app_item.app_label,
                    category=app_item.category,
                    is_allowed=app_item.is_allowed,
                )
            )

    _create_notification(
        db,
        family_id=policy.family_id,
        notif_type="POLICY_UPDATED",
        title="Хяналтын дүрэм шинэчлэгдлээ",
        body=f"Өдрийн хязгаар {policy.daily_limit_minutes} минут болж шинэчлэгдлээ (v{policy.version}).",
    )

    db.commit()
    return get_child_policy(child_id, principal=principal, db=db)


# ---------------------------------------------------------------------------
# FR-03: Device Management, Pairing & Hardware Token Issuance
# ---------------------------------------------------------------------------


@app.post(
    "/api/v1/devices/pair/init",
    response_model=DevicePairInitResponse,
    status_code=status.HTTP_201_CREATED,
)
def init_device_pairing(
    payload: DevicePairInitRequest,
    db: Session = Depends(get_db),
) -> DevicePairInitResponse:
    device = db.scalar(select(Device).where(Device.hardware_uid == payload.hardware_uid))
    if not device:
        device = Device(
            hardware_uid=payload.hardware_uid,
            device_type=payload.device_type,
            device_name=payload.device_name,
            app_version=payload.app_version,
            status="UNPAIRED",
        )
        db.add(device)
        db.flush()

    # Expire any previous pending pairings for this device
    old_pairings = db.scalars(
        select(DevicePairing).where(
            DevicePairing.device_id == device.id,
            DevicePairing.status == "PENDING",
        )
    ).all()
    for op in old_pairings:
        op.status = "EXPIRED"

    code = generate_pairing_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    qr_payload = f"familyscreen://pair?code={code}&device_id={device.id}"

    pairing = DevicePairing(
        device_id=device.id,
        pairing_code=code,
        qr_payload=qr_payload,
        status="PENDING",
        expires_at=expires_at,
    )
    db.add(pairing)
    db.commit()

    return DevicePairInitResponse(
        device_id=device.id,
        pairing_code=code,
        qr_payload=qr_payload,
        expires_at=expires_at,
    )


@app.post("/api/v1/devices/pair/claim", response_model=DeviceOut)
def claim_device_pairing(
    payload: DevicePairClaimRequest,
    principal: Optional[AuthPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> DeviceOut:
    if principal is not None:
        ensure_family_access(principal, payload.family_id)

    if payload.active_child_id:
        child = db.get(Child, payload.active_child_id)
        if not child or child.family_id != payload.family_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Сонгосон хүүхдийн профайл энэ гэр бүлд хамаарахгүй байна.",
            )

    pairing = db.scalar(
        select(DevicePairing).where(
            DevicePairing.pairing_code == payload.pairing_code.strip(),
        )
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Холбох код олдсонгүй.")
    if pairing.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Энэ холбох кодыг аль хэдийн ашигласан эсвэл хүчингүй болсон байна.",
        )

    now_utc = datetime.now(timezone.utc)
    exp = pairing.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if now_utc > exp:
        pairing.status = "EXPIRED"
        db.commit()
        raise HTTPException(status_code=400, detail="Холбох кодын хугацаа дууссан байна.")

    device = db.get(Device, pairing.device_id)
    device.family_id = payload.family_id
    device.device_name = payload.device_name.strip()
    device.active_child_id = payload.active_child_id
    device.status = "ONLINE"
    device.last_seen_at = now_utc

    pairing.status = "CLAIMED"
    pairing.claimed_by_family_id = payload.family_id

    db.commit()
    db.refresh(device)
    return DeviceOut.model_validate(device)


@app.get("/api/v1/devices/pair/status/{pairing_code}", response_model=DevicePairStatusResponse)
def check_device_pairing_status(
    pairing_code: str,
    hardware_uid: str = Query(..., min_length=4, max_length=128),
    db: Session = Depends(get_db),
) -> DevicePairStatusResponse:
    """Called by the Android TV Box while waiting on the Pairing screen to receive its device_token once claimed."""
    pairing = db.scalar(
        select(DevicePairing).where(DevicePairing.pairing_code == pairing_code.strip())
    )
    if not pairing:
        raise HTTPException(status_code=404, detail="Холбох код олдсонгүй.")

    device = db.get(Device, pairing.device_id)
    if not device or not hmac.compare_digest(device.hardware_uid, hardware_uid):
        raise HTTPException(status_code=403, detail="Төхөөрөмжийн hardware_uid таарахгүй байна.")

    now_utc = datetime.now(timezone.utc)
    exp = pairing.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if pairing.status == "PENDING" and now_utc > exp:
        pairing.status = "EXPIRED"
        db.commit()

    if pairing.status != "CLAIMED" or not device.family_id:
        return DevicePairStatusResponse(
            status=pairing.status,
            device_id=device.id,
            family_id=device.family_id,
            active_child_id=device.active_child_id,
            device_token=None,
        )

    # Issue a one-time retrievable device_token if not yet issued for this claimed pairing
    if device.device_token_hash is not None and pairing.qr_payload == "TOKEN_DELIVERED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Төхөөрөмжийн токен аль хэдийн олгогдсон байна.",
        )

    raw_device_token = generate_device_token(device.id, device.family_id)
    device.device_token_hash = sha256_hex(raw_device_token)
    pairing.qr_payload = "TOKEN_DELIVERED"
    db.commit()

    return DevicePairStatusResponse(
        status="CLAIMED",
        device_id=device.id,
        family_id=device.family_id,
        active_child_id=device.active_child_id,
        device_token=raw_device_token,
    )


@app.get("/api/v1/families/{family_id}/devices", response_model=List[DeviceOut])
def list_family_devices(
    family_id: str,
    principal: Optional[AuthPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> List[DeviceOut]:
    if principal is not None:
        ensure_family_access(principal, family_id)
    devices = db.scalars(select(Device).where(Device.family_id == family_id)).all()
    return [DeviceOut.model_validate(d) for d in devices]


@app.delete("/api/v1/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def unpair_device(
    device_id: str,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> Response:
    device = db.get(Device, device_id)
    if not device or not device.family_id:
        raise HTTPException(status_code=404, detail="Төхөөрөмж олдсонгүй.")
    ensure_family_access(principal, device.family_id)

    device.family_id = None
    device.active_child_id = None
    device.device_token_hash = None
    device.status = "UNPAIRED"
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/v1/devices/{device_id}/sync", response_model=DeviceSyncResponse)
def sync_device_state(
    device_id: str,
    now_override: Optional[datetime] = Query(default=None),
    device_principal: Optional[DevicePrincipal] = Depends(get_optional_device_principal),
    parent_principal: Optional[AuthPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> DeviceSyncResponse:
    device = db.get(Device, device_id)
    if not device or not device.family_id or not device.active_child_id:
        raise HTTPException(status_code=400, detail="Төхөөрөмж гэр бүл эсвэл хүүхдийн профайлтай холбогдоогүй байна.")

    _verify_device_auth_if_needed(device, device_principal, parent_principal)

    family = db.get(Family, device.family_id)
    child = db.get(Child, device.active_child_id)
    if not family or not child or not child.policy:
        raise HTTPException(status_code=404, detail="Хүүхдийн профайл эсвэл дүрэм олдсонгүй.")

    now_utc = now_override or datetime.now(timezone.utc)
    device.last_seen_at = now_utc
    device.status = "ONLINE"
    db.commit()

    policy = child.policy
    time_state = _compute_child_time_state(db, child, family, now_utc=now_utc)
    schedules = [
        ScheduleItemSchema(
            day_of_week=s.day_of_week,
            is_school_day=s.is_school_day,
            start_time=s.start_time,
            end_time=s.end_time,
            is_enabled=s.is_enabled,
        )
        for s in sorted(policy.schedules, key=lambda x: x.day_of_week)
    ]
    allowed_apps = [
        AllowedAppItemSchema(
            package_name=a.package_name,
            app_label=a.app_label,
            category=a.category,
            is_allowed=a.is_allowed,
        )
        for a in policy.allowed_apps
        if a.is_allowed
    ]

    return DeviceSyncResponse(
        server_time_utc=now_utc,
        family_id=family.id,
        family_timezone=family.timezone,
        device_id=device.id,
        active_child_id=child.id,
        child_nickname=child.nickname,
        policy_version=policy.version,
        daily_limit_minutes=policy.daily_limit_minutes,
        weekend_bonus_minutes=policy.weekend_bonus_minutes,
        warning_minutes=parse_warning_csv(policy.warning_minutes_csv),
        enforce_whitelist=policy.enforce_whitelist,
        is_instant_locked=policy.is_instant_locked,
        pin_hash=family.pin_hash,
        time_state=time_state,
        schedules=schedules,
        allowed_apps=allowed_apps,
    )


# ---------------------------------------------------------------------------
# FR-09 & Time Engine: Usage Session Recording (Online + Offline Idempotent)
# ---------------------------------------------------------------------------


@app.post("/api/v1/usage/sessions", response_model=UsageSessionResponse)
def record_usage_session(
    payload: UsageSessionCreateRequest,
    device_principal: Optional[DevicePrincipal] = Depends(get_optional_device_principal),
    parent_principal: Optional[AuthPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> UsageSessionResponse:
    family = db.get(Family, payload.family_id)
    child = db.get(Child, payload.child_id)
    device = db.get(Device, payload.device_id)
    if not family or not child or child.family_id != family.id or not device:
        raise HTTPException(status_code=404, detail="Гэр бүл, хүүхэд эсвэл төхөөрөмж олдсонгүй.")
    if device.family_id != family.id:
        raise HTTPException(status_code=403, detail="Төхөөрөмж энэ гэр бүлд хамаарахгүй байна.")

    _verify_device_auth_if_needed(device, device_principal, parent_principal)

    existing = db.scalar(
        select(UsageSession).where(UsageSession.client_session_uid == payload.client_session_uid)
    )
    if existing:
        if existing.family_id != family.id or existing.device_id != device.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session UID өөр гэр бүлийн төхөөрөмжид бүртгэлтэй байна.",
            )
        time_state = _compute_child_time_state(db, child, family)
        return UsageSessionResponse(
            session_id=existing.id,
            client_session_uid=existing.client_session_uid,
            idempotent_replay=True,
            time_state=time_state,
        )

    local_dt = resolve_local_datetime(payload.started_at, family.timezone)
    session_row = UsageSession(
        client_session_uid=payload.client_session_uid,
        family_id=family.id,
        child_id=child.id,
        device_id=payload.device_id,
        package_name=payload.package_name,
        usage_date=local_dt.date(),
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        active_seconds=payload.active_seconds,
        synced_from_offline=payload.synced_from_offline,
    )
    db.add(session_row)
    db.flush()

    for ev in payload.events:
        db.add(
            UsageEvent(
                session_id=session_row.id,
                event_type=ev.event_type,
                occurred_at=ev.occurred_at,
                metadata_json=ev.metadata_json,
            )
        )

    db.commit()
    time_state = _compute_child_time_state(db, child, family)

    if time_state.state == "BLOCK" and time_state.reason == "DAILY_LIMIT_REACHED":
        _create_notification(
            db,
            family_id=family.id,
            notif_type="TIME_EXPIRED",
            title="Хүүхдийн үзэх хугацаа дууслаа",
            body=f"{child.nickname}-ийн өдрийн зөвшөөрөгдсөн хугацаа дуусаж, ТВ түгжигдлээ.",
        )
        db.commit()

    return UsageSessionResponse(
        session_id=session_row.id,
        client_session_uid=session_row.client_session_uid,
        idempotent_replay=False,
        time_state=time_state,
    )


# ---------------------------------------------------------------------------
# FR-07: PIN Override & Remote Extra Time
# ---------------------------------------------------------------------------


@app.post("/api/v1/overrides", response_model=OverrideResponse, status_code=status.HTTP_201_CREATED)
def grant_override_time(
    payload: OverrideCreateRequest,
    principal: Optional[AuthPrincipal] = Depends(get_optional_principal),
    device_principal: Optional[DevicePrincipal] = Depends(get_optional_device_principal),
    db: Session = Depends(get_db),
) -> OverrideResponse:
    if payload.added_minutes not in (5, 10, 15, 30, 60):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Нэмэлт хугацаа зөвхөн 5, 10, 15, 30, 60 минут байх боломжтой.",
        )

    family = db.get(Family, payload.family_id)
    child = db.get(Child, payload.child_id)
    if not family or not child or child.family_id != family.id:
        raise HTTPException(status_code=404, detail="Гэр бүл эсвэл хүүхэд олдсонгүй.")

    now_utc = datetime.now(timezone.utc)

    if payload.source == "REMOTE_APP":
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Алсаас хугацаа сунгахын тулд эцэг эхийн эрхээр нэвтэрнэ үү.",
            )
        ensure_family_access(principal, family.id)

    if payload.source == "TV_PIN":
        if payload.device_id:
            device = db.get(Device, payload.device_id)
            if not device or device.family_id != family.id:
                raise HTTPException(status_code=403, detail="Төхөөрөмж энэ гэр бүлд бүртгэлгүй байна.")
            _verify_device_auth_if_needed(device, device_principal, principal)

        if is_pin_locked(family.pin_locked_until, now_utc):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="PIN кодыг олон удаа буруу оруулсан тул 15 минут түр түгжигдсэн байна.",
            )
        if not payload.pin_code or not verify_secret(payload.pin_code, family.pin_hash):
            family.pin_failed_attempts += 1
            if family.pin_failed_attempts >= MAX_PIN_ATTEMPTS:
                family.pin_locked_until = compute_lockout_expiry(now_utc)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="PIN код буруу байна.",
            )
        family.pin_failed_attempts = 0
        family.pin_locked_until = None

    if child.policy and child.policy.is_instant_locked:
        child.policy.is_instant_locked = False
        child.policy.version += 1

    today_local = resolve_local_datetime(now_utc, family.timezone).date()
    override = Override(
        family_id=family.id,
        child_id=child.id,
        device_id=payload.device_id,
        granted_by_user_id=principal.user_id if principal else None,
        source=payload.source,
        added_minutes=payload.added_minutes,
        override_date=today_local,
        reason=payload.reason,
    )
    db.add(override)

    _create_notification(
        db,
        family_id=family.id,
        notif_type="OVERRIDE_USED",
        title="Нэмэлт хугацаа олгогдлоо",
        body=f"{child.nickname}-д +{payload.added_minutes} минут нэмэлт хугацаа ({payload.source}) олголоо.",
    )

    db.commit()
    db.refresh(override)

    time_state = _compute_child_time_state(db, child, family, now_utc=now_utc)
    return OverrideResponse(
        override_id=override.id,
        added_minutes=override.added_minutes,
        time_state=time_state,
    )


# ---------------------------------------------------------------------------
# FR-08 & FR-11: Usage Reports & Notifications
# ---------------------------------------------------------------------------


@app.get("/api/v1/reports/summary", response_model=UsageReportResponse)
def get_usage_report(
    family_id: str,
    child_id: str,
    days: int = Query(default=7, ge=1, le=31),
    principal: Optional[AuthPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> UsageReportResponse:
    if principal is not None:
        ensure_family_access(principal, family_id)

    family = db.get(Family, family_id)
    child = db.get(Child, child_id)
    if not family or not child or child.family_id != family.id or not child.policy:
        raise HTTPException(status_code=404, detail="Мэдээлэл олдсонгүй.")

    today_local = resolve_local_datetime(None, family.timezone).date()
    start_date = today_local - timedelta(days=days - 1)

    sessions = db.scalars(
        select(UsageSession).where(
            UsageSession.child_id == child.id,
            UsageSession.usage_date >= start_date,
            UsageSession.usage_date <= today_local,
        )
    ).all()

    overrides = db.scalars(
        select(Override).where(
            Override.child_id == child.id,
            Override.override_date >= start_date,
            Override.override_date <= today_local,
        )
    ).all()

    daily_items: List[DailyUsageItem] = []
    total_used_sec = 0

    for offset in range(days):
        d = start_date + timedelta(days=offset)
        day_sec = sum(s.active_seconds for s in sessions if s.usage_date == d)
        day_over_min = sum(o.added_minutes for o in overrides if o.override_date == d)
        is_weekend = d.weekday() in (5, 6)
        allowed_min = (
            child.policy.daily_limit_minutes
            + (child.policy.weekend_bonus_minutes if is_weekend else 0)
            + day_over_min
        )
        total_used_sec += day_sec
        daily_items.append(
            DailyUsageItem(
                usage_date=d,
                allowed_minutes=allowed_min,
                used_minutes=round(day_sec / 60),
                override_minutes=day_over_min,
            )
        )

    app_totals: dict[str, int] = {}
    for s in sessions:
        app_totals[s.package_name] = app_totals.get(s.package_name, 0) + s.active_seconds

    app_breakdown = [
        AppBreakdownItem(package_name=pkg, used_minutes=round(sec / 60))
        for pkg, sec in sorted(app_totals.items(), key=lambda x: x[1], reverse=True)
    ]

    return UsageReportResponse(
        family_id=family.id,
        child_id=child.id,
        child_nickname=child.nickname,
        days=days,
        total_used_minutes=round(total_used_sec / 60),
        daily_items=daily_items,
        app_breakdown=app_breakdown,
    )


@app.get("/api/v1/families/{family_id}/notifications", response_model=List[NotificationOut])
def list_notifications(
    family_id: str,
    principal: Optional[AuthPrincipal] = Depends(get_optional_principal),
    db: Session = Depends(get_db),
) -> List[NotificationOut]:
    if principal is not None:
        ensure_family_access(principal, family_id)

    rows = db.scalars(
        select(Notification)
        .where(Notification.family_id == family_id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    ).all()
    return [NotificationOut.model_validate(r) for r in rows]
