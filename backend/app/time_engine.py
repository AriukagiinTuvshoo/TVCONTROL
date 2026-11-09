"""FamilyScreen Time Engine — Deterministic screen time evaluation logic.

Computes the exact viewing state (`ALLOW`, `WARNING`, `BLOCK`), remaining quota,
schedule window constraints, and active warning thresholds (e.g. 15, 5, 1 min).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class ScheduleWindow:
    """Schedule rule for a single day of week (0=Monday .. 6=Sunday)."""

    day_of_week: int
    is_school_day: bool
    start_time: time
    end_time: time
    is_enabled: bool


@dataclass(frozen=True)
class TimeEngineInput:
    """All inputs needed to deterministically evaluate a child's screen-time state."""

    daily_limit_minutes: int
    weekend_bonus_minutes: int
    warning_minutes: List[int]
    is_instant_locked: bool
    schedules: List[ScheduleWindow]
    used_seconds_today: int
    override_minutes_today: int
    family_timezone: str = "Asia/Ulaanbaatar"
    now_utc: Optional[datetime] = None


@dataclass(frozen=True)
class TimeEngineResult:
    """Deterministic output of the Time Engine."""

    state: str  # "ALLOW" | "WARNING" | "BLOCK"
    reason: str
    local_date: date
    local_time_str: str
    allowed_seconds_today: int
    used_seconds_today: int
    override_seconds_today: int
    remaining_seconds_today: int
    schedule_remaining_seconds: Optional[int]
    effective_remaining_seconds: int
    active_warning_minutes: Optional[int]
    next_warning_at_remaining_seconds: Optional[int]


def resolve_local_datetime(now_utc: Optional[datetime], tz_name: str) -> datetime:
    """Convert a UTC datetime into the family's local timezone (defaults to UTC+8 Ulaanbaatar)."""
    base_utc = now_utc or datetime.now(timezone.utc)
    if base_utc.tzinfo is None:
        base_utc = base_utc.replace(tzinfo=timezone.utc)
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        # Fallback for environments without tzdata package installed: Asia/Ulaanbaatar is UTC+8
        tz = timezone(timedelta(hours=8))
    return base_utc.astimezone(tz)


def parse_warning_csv(csv_value: str) -> List[int]:
    """Parse '15,5,1' into sorted descending list [15, 5, 1]."""
    result: List[int] = []
    for part in csv_value.split(","):
        part = part.strip()
        if part.isdigit():
            val = int(part)
            if val > 0:
                result.append(val)
    return sorted(set(result), reverse=True) or [15, 5, 1]


def _seconds_until_end_of_window(now_local: datetime, start_t: time, end_t: time) -> int:
    """Return remaining seconds inside [start_t, end_t], or 0 if outside the window."""
    current_t = now_local.timetz().replace(tzinfo=None)
    if current_t < start_t or current_t >= end_t:
        return 0
    end_dt = now_local.replace(
        hour=end_t.hour,
        minute=end_t.minute,
        second=end_t.second,
        microsecond=0,
    )
    diff = int((end_dt - now_local).total_seconds())
    return max(0, diff)


def evaluate_time_engine(inp: TimeEngineInput) -> TimeEngineResult:
    """Evaluate ALLOW / WARNING / BLOCK state deterministically."""
    now_local = resolve_local_datetime(inp.now_utc, inp.family_timezone)
    weekday = now_local.weekday()  # 0=Monday .. 6=Sunday
    is_weekend = weekday in (5, 6)

    base_minutes = inp.daily_limit_minutes + (inp.weekend_bonus_minutes if is_weekend else 0)
    override_seconds = max(0, inp.override_minutes_today * 60)
    allowed_seconds = max(0, base_minutes * 60) + override_seconds
    used_seconds = max(0, inp.used_seconds_today)
    remaining_quota = max(0, allowed_seconds - used_seconds)

    # Find matching day schedule if configured
    day_schedule: Optional[ScheduleWindow] = next(
        (s for s in inp.schedules if s.day_of_week == weekday),
        None,
    )

    schedule_remaining: Optional[int] = None
    outside_schedule = False

    if day_schedule is not None:
        if not day_schedule.is_enabled:
            outside_schedule = True
            schedule_remaining = 0
        else:
            schedule_remaining = _seconds_until_end_of_window(
                now_local, day_schedule.start_time, day_schedule.end_time
            )
            if schedule_remaining <= 0:
                outside_schedule = True

    effective_remaining = (
        min(remaining_quota, schedule_remaining)
        if schedule_remaining is not None
        else remaining_quota
    )

    # 1. Check Parent Instant Lock
    if inp.is_instant_locked:
        return TimeEngineResult(
            state="BLOCK",
            reason="PARENT_INSTANT_LOCK",
            local_date=now_local.date(),
            local_time_str=now_local.strftime("%H:%M:%S"),
            allowed_seconds_today=allowed_seconds,
            used_seconds_today=used_seconds,
            override_seconds_today=override_seconds,
            remaining_seconds_today=remaining_quota,
            schedule_remaining_seconds=schedule_remaining,
            effective_remaining_seconds=0,
            active_warning_minutes=None,
            next_warning_at_remaining_seconds=None,
        )

    # 2. Check Schedule Window (unless parent granted an override today that still has quota)
    if outside_schedule and override_seconds == 0:
        return TimeEngineResult(
            state="BLOCK",
            reason="OUTSIDE_SCHEDULE_WINDOW",
            local_date=now_local.date(),
            local_time_str=now_local.strftime("%H:%M:%S"),
            allowed_seconds_today=allowed_seconds,
            used_seconds_today=used_seconds,
            override_seconds_today=override_seconds,
            remaining_seconds_today=remaining_quota,
            schedule_remaining_seconds=0,
            effective_remaining_seconds=0,
            active_warning_minutes=None,
            next_warning_at_remaining_seconds=None,
        )

    # If override was granted outside schedule, use remaining_quota as effective
    if outside_schedule and override_seconds > 0:
        effective_remaining = remaining_quota

    # 3. Check Daily Quota Exhausted
    if effective_remaining <= 0:
        return TimeEngineResult(
            state="BLOCK",
            reason="DAILY_LIMIT_REACHED",
            local_date=now_local.date(),
            local_time_str=now_local.strftime("%H:%M:%S"),
            allowed_seconds_today=allowed_seconds,
            used_seconds_today=used_seconds,
            override_seconds_today=override_seconds,
            remaining_seconds_today=0,
            schedule_remaining_seconds=schedule_remaining,
            effective_remaining_seconds=0,
            active_warning_minutes=None,
            next_warning_at_remaining_seconds=None,
        )

    # 4. Evaluate Warning Thresholds (sorted descending, e.g., [15, 5, 1])
    sorted_warnings = sorted({w for w in inp.warning_minutes if w > 0}, reverse=True)
    active_warning: Optional[int] = None
    next_warning_sec: Optional[int] = None

    # Find the tightest warning threshold that has been crossed
    for threshold_min in sorted_warnings:
        threshold_sec = threshold_min * 60
        if effective_remaining <= threshold_sec:
            active_warning = threshold_min
        elif next_warning_sec is None or threshold_sec > next_warning_sec:
            next_warning_sec = threshold_sec

    # If currently in WARNING, compute the next smaller warning threshold
    if active_warning is not None:
        smaller_thresholds = [w * 60 for w in sorted_warnings if w < active_warning]
        next_warning_sec = smaller_thresholds[0] if smaller_thresholds else 0
        return TimeEngineResult(
            state="WARNING",
            reason=f"WARNING_{active_warning}_MIN_REMAINING",
            local_date=now_local.date(),
            local_time_str=now_local.strftime("%H:%M:%S"),
            allowed_seconds_today=allowed_seconds,
            used_seconds_today=used_seconds,
            override_seconds_today=override_seconds,
            remaining_seconds_today=remaining_quota,
            schedule_remaining_seconds=schedule_remaining,
            effective_remaining_seconds=effective_remaining,
            active_warning_minutes=active_warning,
            next_warning_at_remaining_seconds=next_warning_sec,
        )

    # 5. Otherwise ALLOW
    return TimeEngineResult(
        state="ALLOW",
        reason="WITHIN_LIMIT_AND_SCHEDULE",
        local_date=now_local.date(),
        local_time_str=now_local.strftime("%H:%M:%S"),
        allowed_seconds_today=allowed_seconds,
        used_seconds_today=used_seconds,
        override_seconds_today=override_seconds,
        remaining_seconds_today=remaining_quota,
        schedule_remaining_seconds=schedule_remaining,
        effective_remaining_seconds=effective_remaining,
        active_warning_minutes=None,
        next_warning_at_remaining_seconds=next_warning_sec,
    )
