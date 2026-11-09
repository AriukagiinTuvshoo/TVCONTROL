"""SQLAlchemy ORM models for the 13 core FamilyScreen database tables."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid_str() -> str:
    return str(uuid.uuid4())


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """1. users — Parent user account."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc, onupdate=_now_utc, nullable=False
    )

    memberships: Mapped[List["FamilyMember"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Family(Base):
    """2. families — Family unit and shared PIN settings."""

    __tablename__ = "families"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Ulaanbaatar", nullable=False)
    plan_tier: Mapped[str] = mapped_column(String(20), default="FREE", nullable=False)
    pin_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pin_failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pin_locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now_utc, nullable=False)

    members: Mapped[List["FamilyMember"]] = relationship(back_populates="family", cascade="all, delete-orphan")
    children: Mapped[List["Child"]] = relationship(back_populates="family", cascade="all, delete-orphan")
    devices: Mapped[List["Device"]] = relationship(back_populates="family", cascade="all, delete-orphan")
    notifications: Mapped[List["Notification"]] = relationship(back_populates="family", cascade="all, delete-orphan")


class FamilyMember(Base):
    """3. family_members — Parent/caregiver membership within a family."""

    __tablename__ = "family_members"
    __table_args__ = (UniqueConstraint("family_id", "user_id", name="uq_family_member"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    family_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="OWNER", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now_utc, nullable=False)

    family: Mapped["Family"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")


class Child(Base):
    """4. children — Child profile (minimal data collection for privacy)."""

    __tablename__ = "children"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    family_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nickname: Mapped[str] = mapped_column(String(80), nullable=False)
    age_group: Mapped[str] = mapped_column(String(20), nullable=False)
    avatar_key: Mapped[str] = mapped_column(String(64), default="fox", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now_utc, nullable=False)

    family: Mapped["Family"] = relationship(back_populates="children")
    policy: Mapped[Optional["Policy"]] = relationship(
        back_populates="child", uselist=False, cascade="all, delete-orphan"
    )
    usage_sessions: Mapped[List["UsageSession"]] = relationship(
        back_populates="child", cascade="all, delete-orphan"
    )
    overrides: Mapped[List["Override"]] = relationship(back_populates="child", cascade="all, delete-orphan")


class Device(Base):
    """5. devices — Smart TV or FamilyScreen Box hardware registered in the system."""

    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    family_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("families.id", ondelete="CASCADE"), nullable=True, index=True
    )
    active_child_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("children.id", ondelete="SET NULL"), nullable=True
    )
    device_name: Mapped[str] = mapped_column(String(120), nullable=False)
    device_type: Mapped[str] = mapped_column(String(30), nullable=False)  # ANDROID_TV, FAMILYSCREEN_BOX, TIZEN, WEBOS
    hardware_uid: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    device_token_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    app_version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="UNPAIRED", nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now_utc, nullable=False)

    family: Mapped[Optional["Family"]] = relationship(back_populates="devices")
    pairings: Mapped[List["DevicePairing"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )


class DevicePairing(Base):
    """6. device_pairings — Short code / QR pairing handshakes."""

    __tablename__ = "device_pairings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pairing_code: Mapped[str] = mapped_column(String(8), unique=True, nullable=False, index=True)
    qr_payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    claimed_by_family_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("families.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now_utc, nullable=False)

    device: Mapped["Device"] = relationship(back_populates="pairings")


class Policy(Base):
    """7. policies — Daily limit, warning thresholds, and lock state per child."""

    __tablename__ = "policies"
    __table_args__ = (
        CheckConstraint("daily_limit_minutes >= 0 AND daily_limit_minutes <= 720", name="ck_daily_limit_range"),
        CheckConstraint("weekend_bonus_minutes >= 0 AND weekend_bonus_minutes <= 360", name="ck_weekend_bonus_range"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    family_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    child_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("children.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    daily_limit_minutes: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    weekend_bonus_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warning_minutes_csv: Mapped[str] = mapped_column(String(64), default="15,5,1", nullable=False)
    enforce_whitelist: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_instant_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc, onupdate=_now_utc, nullable=False
    )

    child: Mapped["Child"] = relationship(back_populates="policy")
    schedules: Mapped[List["Schedule"]] = relationship(back_populates="policy", cascade="all, delete-orphan")
    allowed_apps: Mapped[List["AllowedApp"]] = relationship(back_populates="policy", cascade="all, delete-orphan")


class Schedule(Base):
    """8. schedules — Allowed viewing time windows per day of week."""

    __tablename__ = "schedules"
    __table_args__ = (
        CheckConstraint("day_of_week >= 0 AND day_of_week <= 6", name="ck_day_of_week_range"),
        UniqueConstraint("policy_id", "day_of_week", name="uq_policy_day"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    policy_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0=Monday .. 6=Sunday
    is_school_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, default=time(8, 0), nullable=False)
    end_time: Mapped[time] = mapped_column(Time, default=time(21, 0), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    policy: Mapped["Policy"] = relationship(back_populates="schedules")


class AllowedApp(Base):
    """9. allowed_apps — App Whitelist entries per child policy."""

    __tablename__ = "allowed_apps"
    __table_args__ = (UniqueConstraint("policy_id", "package_name", name="uq_policy_package"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    policy_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    app_label: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(40), default="EDUCATION", nullable=False)
    is_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    policy: Mapped["Policy"] = relationship(back_populates="allowed_apps")


class UsageSession(Base):
    """10. usage_sessions — Active viewing sessions (supports idempotent offline sync)."""

    __tablename__ = "usage_sessions"
    __table_args__ = (
        CheckConstraint("active_seconds >= 0", name="ck_active_seconds_non_negative"),
        Index("idx_usage_sessions_child_date", "child_id", "usage_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    client_session_uid: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    family_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("families.id", ondelete="CASCADE"), nullable=False
    )
    child_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("children.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    active_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    synced_from_offline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now_utc, nullable=False)

    child: Mapped["Child"] = relationship(back_populates="usage_sessions")
    events: Mapped[List["UsageEvent"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class UsageEvent(Base):
    """11. usage_events — Granular session lifecycle events (START, PAUSE, WARNING, BLOCKED)."""

    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("usage_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    session: Mapped["UsageSession"] = relationship(back_populates="events")


class Override(Base):
    """12. overrides — Extra time granted via PIN on TV or Remote Mobile App."""

    __tablename__ = "overrides"
    __table_args__ = (
        CheckConstraint("added_minutes IN (5, 10, 15, 30, 60)", name="ck_override_minutes_valid"),
        Index("idx_overrides_child_date", "child_id", "override_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    family_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("families.id", ondelete="CASCADE"), nullable=False
    )
    child_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("children.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    granted_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # TV_PIN or REMOTE_APP
    added_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    override_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now_utc, nullable=False)

    child: Mapped["Child"] = relationship(back_populates="overrides")


class Notification(Base):
    """13. notifications — Alerts delivered to parents."""

    __tablename__ = "notifications"
    __table_args__ = (Index("idx_notifications_family_created", "family_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    family_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("families.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now_utc, nullable=False)

    family: Mapped["Family"] = relationship(back_populates="notifications")
