"""Pydantic v2 request and response schemas for the FamilyScreen REST API."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    phone: Optional[str] = None
    full_name: str


class FamilyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    timezone: str
    plan_tier: str


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=120)
    family_name: str = Field(..., min_length=1, max_length=120)
    pin_code: str = Field(..., pattern=r"^\d{4,6}$", description="4 to 6 digit parent PIN")
    timezone: str = Field(default="Asia/Ulaanbaatar")


class LoginRequest(BaseModel):
    email: str
    password: str


class SupabaseSyncRequest(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=120)
    family_name: Optional[str] = Field(default=None, max_length=120)
    pin_code: Optional[str] = Field(default="2580", pattern=r"^\d{4,6}$")
    timezone: Optional[str] = Field(default="Asia/Ulaanbaatar")


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    family: FamilyOut


class PinUpdateRequest(BaseModel):
    current_pin: Optional[str] = Field(default=None, pattern=r"^\d{4,6}$")
    new_pin: str = Field(..., pattern=r"^\d{4,6}$")


class PinUpdateResponse(BaseModel):
    family_id: str
    message: str


class ScheduleItemSchema(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)
    is_school_day: bool = True
    start_time: time = Field(default=time(8, 0))
    end_time: time = Field(default=time(21, 0))
    is_enabled: bool = True


class AllowedAppItemSchema(BaseModel):
    package_name: str = Field(..., min_length=3, max_length=255)
    app_label: str = Field(..., min_length=1, max_length=120)
    category: str = Field(default="EDUCATION")
    is_allowed: bool = True


class TimeStateOut(BaseModel):
    state: str
    reason: str
    local_date: date
    local_time_str: str
    allowed_seconds_today: int
    used_seconds_today: int
    override_seconds_today: int
    remaining_seconds_today: int
    schedule_remaining_seconds: Optional[int] = None
    effective_remaining_seconds: int
    active_warning_minutes: Optional[int] = None
    next_warning_at_remaining_seconds: Optional[int] = None


class ChildCreateRequest(BaseModel):
    family_id: str
    nickname: str = Field(..., min_length=1, max_length=80)
    age_group: str = Field(default="7-9")
    avatar_key: str = Field(default="fox")
    daily_limit_minutes: int = Field(default=90, ge=0, le=720)


class ChildUpdateRequest(BaseModel):
    nickname: Optional[str] = Field(default=None, min_length=1, max_length=80)
    age_group: Optional[str] = Field(default=None)
    avatar_key: Optional[str] = Field(default=None)
    daily_limit_minutes: Optional[int] = Field(default=None, ge=0, le=720)


class ChildOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    family_id: str
    nickname: str
    age_group: str
    avatar_key: str
    is_active: bool
    policy_id: Optional[str] = None
    daily_limit_minutes: int = 90
    is_instant_locked: bool = False
    time_state: Optional[TimeStateOut] = None


class PolicyUpdateRequest(BaseModel):
    daily_limit_minutes: int = Field(..., ge=0, le=720)
    weekend_bonus_minutes: int = Field(default=0, ge=0, le=360)
    warning_minutes: List[int] = Field(default_factory=lambda: [15, 5, 1])
    enforce_whitelist: bool = True
    is_instant_locked: bool = False
    schedules: Optional[List[ScheduleItemSchema]] = None
    allowed_apps: Optional[List[AllowedAppItemSchema]] = None


class PolicyOut(BaseModel):
    id: str
    family_id: str
    child_id: str
    daily_limit_minutes: int
    weekend_bonus_minutes: int
    warning_minutes: List[int]
    enforce_whitelist: bool
    is_instant_locked: bool
    version: int
    schedules: List[ScheduleItemSchema]
    allowed_apps: List[AllowedAppItemSchema]
    time_state: Optional[TimeStateOut] = None


class DevicePairInitRequest(BaseModel):
    hardware_uid: str = Field(..., min_length=4, max_length=128)
    device_type: str = Field(default="FAMILYSCREEN_BOX")
    device_name: str = Field(default="FamilyScreen TV Box")
    app_version: str = Field(default="1.0.0")


class DevicePairInitResponse(BaseModel):
    device_id: str
    pairing_code: str
    qr_payload: str
    expires_at: datetime


class DevicePairClaimRequest(BaseModel):
    family_id: str
    pairing_code: str = Field(..., min_length=6, max_length=8)
    device_name: str = Field(..., min_length=1, max_length=120)
    active_child_id: Optional[str] = None


class DevicePairStatusResponse(BaseModel):
    status: str  # PENDING | CLAIMED | EXPIRED
    device_id: str
    family_id: Optional[str] = None
    active_child_id: Optional[str] = None
    device_token: Optional[str] = None


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    family_id: Optional[str]
    active_child_id: Optional[str]
    device_name: str
    device_type: str
    hardware_uid: str
    app_version: str
    status: str
    device_token: Optional[str] = None
    last_seen_at: Optional[datetime] = None


class DeviceSyncResponse(BaseModel):
    server_time_utc: datetime
    family_id: str
    family_timezone: str
    device_id: str
    active_child_id: str
    child_nickname: str
    policy_version: int
    daily_limit_minutes: int
    weekend_bonus_minutes: int
    warning_minutes: List[int]
    enforce_whitelist: bool
    is_instant_locked: bool
    pin_hash: Optional[str] = None
    time_state: TimeStateOut
    schedules: List[ScheduleItemSchema]
    allowed_apps: List[AllowedAppItemSchema]


class UsageEventInput(BaseModel):
    event_type: str
    occurred_at: datetime
    metadata_json: Optional[str] = None


class UsageSessionCreateRequest(BaseModel):
    client_session_uid: str = Field(..., min_length=4, max_length=128)
    family_id: str
    child_id: str
    device_id: str
    package_name: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    active_seconds: int = Field(..., ge=0, le=86400)
    synced_from_offline: bool = False
    events: List[UsageEventInput] = Field(default_factory=list)


class UsageSessionResponse(BaseModel):
    session_id: str
    client_session_uid: str
    idempotent_replay: bool
    time_state: TimeStateOut


class OverrideCreateRequest(BaseModel):
    family_id: str
    child_id: str
    device_id: Optional[str] = None
    source: str = Field(default="TV_PIN", pattern=r"^(TV_PIN|REMOTE_APP)$")
    pin_code: Optional[str] = None
    added_minutes: int = Field(..., description="Must be one of 5, 10, 15, 30, 60")
    reason: Optional[str] = Field(default="Эцэг эхийн зөвшөөрлөөр сунгав")


class OverrideResponse(BaseModel):
    override_id: str
    added_minutes: int
    time_state: TimeStateOut


class DailyUsageItem(BaseModel):
    usage_date: date
    allowed_minutes: int
    used_minutes: int
    override_minutes: int


class AppBreakdownItem(BaseModel):
    package_name: str
    used_minutes: int


class UsageReportResponse(BaseModel):
    family_id: str
    child_id: str
    child_nickname: str
    days: int
    total_used_minutes: int
    daily_items: List[DailyUsageItem]
    app_breakdown: List[AppBreakdownItem]


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    family_id: str
    type: str
    title: str
    body: str
    is_read: bool
    created_at: datetime
