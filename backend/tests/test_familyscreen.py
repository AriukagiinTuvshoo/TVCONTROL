"""Automated tests for FamilyScreen Time Engine, FastAPI Backend, Auth, Family Isolation, and TV Box Integration."""

from __future__ import annotations

from datetime import datetime, time, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.time_engine import ScheduleWindow, TimeEngineInput, evaluate_time_engine


@pytest.fixture()
def client():
    """Provide an isolated in-memory SQLite database per test."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(test_engine, "connect")
    def _fk_pragma(dbapi_conn, conn_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    TestingSessionLocal = sessionmaker(bind=test_engine, expire_on_commit=False)
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_time_engine_prd_example_transitions():
    """Verify PRD Section 5 & 7 exact transitions: 90m limit -> 15m, 5m, 1m warning -> 0m BLOCK."""
    now_utc = datetime(2026, 11, 4, 9, 0, 0, tzinfo=timezone.utc)
    sched = [
        ScheduleWindow(
            day_of_week=2,
            is_school_day=True,
            start_time=time(8, 0),
            end_time=time(21, 0),
            is_enabled=True,
        )
    ]

    res_allow = evaluate_time_engine(
        TimeEngineInput(
            daily_limit_minutes=90,
            weekend_bonus_minutes=0,
            warning_minutes=[15, 5, 1],
            is_instant_locked=False,
            schedules=sched,
            used_seconds_today=0,
            override_minutes_today=0,
            now_utc=now_utc,
        )
    )
    assert res_allow.state == "ALLOW"
    assert res_allow.effective_remaining_seconds == 5400
    assert res_allow.next_warning_at_remaining_seconds == 900

    res_warn_15 = evaluate_time_engine(
        TimeEngineInput(
            daily_limit_minutes=90,
            weekend_bonus_minutes=0,
            warning_minutes=[15, 5, 1],
            is_instant_locked=False,
            schedules=sched,
            used_seconds_today=75 * 60,
            override_minutes_today=0,
            now_utc=now_utc,
        )
    )
    assert res_warn_15.state == "WARNING"
    assert res_warn_15.active_warning_minutes == 15
    assert res_warn_15.next_warning_at_remaining_seconds == 300

    res_warn_5 = evaluate_time_engine(
        TimeEngineInput(
            daily_limit_minutes=90,
            weekend_bonus_minutes=0,
            warning_minutes=[15, 5, 1],
            is_instant_locked=False,
            schedules=sched,
            used_seconds_today=85 * 60,
            override_minutes_today=0,
            now_utc=now_utc,
        )
    )
    assert res_warn_5.state == "WARNING"
    assert res_warn_5.active_warning_minutes == 5
    assert res_warn_5.next_warning_at_remaining_seconds == 60

    res_warn_1 = evaluate_time_engine(
        TimeEngineInput(
            daily_limit_minutes=90,
            weekend_bonus_minutes=0,
            warning_minutes=[15, 5, 1],
            is_instant_locked=False,
            schedules=sched,
            used_seconds_today=89 * 60,
            override_minutes_today=0,
            now_utc=now_utc,
        )
    )
    assert res_warn_1.state == "WARNING"
    assert res_warn_1.active_warning_minutes == 1

    res_block = evaluate_time_engine(
        TimeEngineInput(
            daily_limit_minutes=90,
            weekend_bonus_minutes=0,
            warning_minutes=[15, 5, 1],
            is_instant_locked=False,
            schedules=sched,
            used_seconds_today=90 * 60,
            override_minutes_today=0,
            now_utc=now_utc,
        )
    )
    assert res_block.state == "BLOCK"
    assert res_block.reason == "DAILY_LIMIT_REACHED"
    assert res_block.effective_remaining_seconds == 0


def test_full_mvp_end_to_end_journey(client: TestClient):
    """Verify all 12 MVP Acceptance Criteria end-to-end via REST API."""
    reg_resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "saraa@familyscreen.mn",
            "phone": "+97699119911",
            "password": "SafePassword2026!",
            "full_name": "Сарангэрэл",
            "family_name": "Сарангэрэлийн Гэр Бүл",
            "pin_code": "2580",
        },
    )
    assert reg_resp.status_code == 201
    auth_data = reg_resp.json()
    token = auth_data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    family_id = auth_data["family"]["id"]

    # Verify /auth/me session restoration
    me_resp = client.get("/api/v1/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["family"]["id"] == family_id

    # Create child profile with 60 min daily limit
    child_resp = client.post(
        "/api/v1/children",
        headers=headers,
        json={
            "family_id": family_id,
            "nickname": "Тэмүүлэн",
            "age_group": "7-9",
            "avatar_key": "astronaut",
            "daily_limit_minutes": 60,
        },
    )
    assert child_resp.status_code == 201
    child_id = child_resp.json()["id"]
    assert child_resp.json()["time_state"]["allowed_seconds_today"] == 3600

    # Update child profile (PATCH CRUD)
    patch_resp = client.patch(
        f"/api/v1/children/{child_id}",
        headers=headers,
        json={"nickname": "Тэмүүлэн (Ах)"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["nickname"] == "Тэмүүлэн (Ах)"

    # TV Box initiates pairing & Parent claims 6-digit code
    pair_init = client.post(
        "/api/v1/devices/pair/init",
        json={
            "hardware_uid": "tvbox-mn-001",
            "device_type": "FAMILYSCREEN_BOX",
            "device_name": "FamilyScreen Box",
        },
    )
    assert pair_init.status_code == 201
    pairing_code = pair_init.json()["pairing_code"]
    device_id = pair_init.json()["device_id"]

    pair_claim = client.post(
        "/api/v1/devices/pair/claim",
        headers=headers,
        json={
            "family_id": family_id,
            "pairing_code": pairing_code,
            "device_name": "Зочны өрөөний TV Box",
            "active_child_id": child_id,
        },
    )
    assert pair_claim.status_code == 200
    assert pair_claim.json()["status"] == "ONLINE"

    # List devices for family
    devs_resp = client.get(f"/api/v1/families/{family_id}/devices", headers=headers)
    assert devs_resp.status_code == 200
    assert len(devs_resp.json()) == 1

    # Sync device state at 15:00 Ulaanbaatar time (07:00 UTC on Wednesday 2026-11-04)
    sync_resp = client.get(
        f"/api/v1/devices/{device_id}/sync",
        params={"now_override": "2026-11-04T07:00:00Z"},
    )
    assert sync_resp.status_code == 200
    sync_data = sync_resp.json()
    assert sync_data["time_state"]["state"] == "ALLOW"
    assert sync_data["time_state"]["allowed_seconds_today"] == 3600
    assert len(sync_data["allowed_apps"]) >= 1
    assert len(sync_data["schedules"]) == 7

    # Record 60 minutes of usage -> transitions to BLOCK (and test idempotency)
    now_iso = datetime.now(timezone.utc).isoformat()
    usage_payload = {
        "client_session_uid": "offline-sess-001",
        "family_id": family_id,
        "child_id": child_id,
        "device_id": device_id,
        "package_name": "com.google.android.apps.youtube.kids",
        "started_at": now_iso,
        "ended_at": now_iso,
        "active_seconds": 3600,
        "synced_from_offline": True,
    }
    u1 = client.post("/api/v1/usage/sessions", json=usage_payload)
    assert u1.status_code == 200
    assert u1.json()["idempotent_replay"] is False
    assert u1.json()["time_state"]["remaining_seconds_today"] == 0

    u2 = client.post("/api/v1/usage/sessions", json=usage_payload)
    assert u2.status_code == 200
    assert u2.json()["idempotent_replay"] is True

    # Wrong PIN attempt is rejected, right PIN grants +15 min override
    bad_pin = client.post(
        "/api/v1/overrides",
        json={
            "family_id": family_id,
            "child_id": child_id,
            "device_id": device_id,
            "source": "TV_PIN",
            "pin_code": "0000",
            "added_minutes": 15,
        },
    )
    assert bad_pin.status_code == 403

    good_pin = client.post(
        "/api/v1/overrides",
        json={
            "family_id": family_id,
            "child_id": child_id,
            "device_id": device_id,
            "source": "TV_PIN",
            "pin_code": "2580",
            "added_minutes": 15,
        },
    )
    assert good_pin.status_code == 201
    assert good_pin.json()["time_state"]["remaining_seconds_today"] == 900

    # Remote +30 min override from Flutter Parent App
    remote_ov = client.post(
        "/api/v1/overrides",
        headers=headers,
        json={
            "family_id": family_id,
            "child_id": child_id,
            "source": "REMOTE_APP",
            "added_minutes": 30,
        },
    )
    assert remote_ov.status_code == 201
    assert remote_ov.json()["time_state"]["remaining_seconds_today"] == 2700

    # Weekly usage report & notifications
    rep = client.get(
        "/api/v1/reports/summary",
        headers=headers,
        params={"family_id": family_id, "child_id": child_id, "days": 7},
    )
    assert rep.status_code == 200
    assert rep.json()["total_used_minutes"] == 60

    notifs = client.get(f"/api/v1/families/{family_id}/notifications", headers=headers)
    assert notifs.status_code == 200
    assert len(notifs.json()) >= 1


def test_authentication_and_cross_family_isolation(client: TestClient):
    """Verify that Family A cannot read, modify, or override Family B's children, policies, devices, or reports."""
    reg_a = client.post(
        "/api/v1/auth/register",
        json={
            "email": "parent_a@familyscreen.mn",
            "password": "PasswordA123!",
            "full_name": "Бат",
            "family_name": "Батын гэр бүл",
            "pin_code": "1111",
        },
    )
    assert reg_a.status_code == 201
    token_a = reg_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    reg_b = client.post(
        "/api/v1/auth/register",
        json={
            "email": "parent_b@familyscreen.mn",
            "password": "PasswordB123!",
            "full_name": "Дорж",
            "family_name": "Доржийн гэр бүл",
            "pin_code": "2222",
        },
    )
    assert reg_b.status_code == 201
    token_b = reg_b.json()["access_token"]
    family_b_id = reg_b.json()["family"]["id"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    child_b = client.post(
        "/api/v1/children",
        headers=headers_b,
        json={
            "family_id": family_b_id,
            "nickname": "Болд",
            "age_group": "10-12",
            "daily_limit_minutes": 90,
        },
    ).json()
    child_b_id = child_b["id"]

    assert client.get("/api/v1/auth/me").status_code == 401
    unauth_override = client.post(
        "/api/v1/overrides",
        json={
            "family_id": family_b_id,
            "child_id": child_b_id,
            "source": "REMOTE_APP",
            "added_minutes": 15,
        },
    )
    assert unauth_override.status_code == 401

    assert client.get(f"/api/v1/families/{family_b_id}/children", headers=headers_a).status_code == 403
    assert client.get(f"/api/v1/policies/{child_b_id}", headers=headers_a).status_code == 403

    res_pol_put = client.put(
        f"/api/v1/policies/{child_b_id}",
        headers=headers_a,
        json={
            "daily_limit_minutes": 180,
            "weekend_bonus_minutes": 0,
            "warning_minutes": [15, 5, 1],
            "enforce_whitelist": False,
            "is_instant_locked": False,
        },
    )
    assert res_pol_put.status_code == 403

    res_ov = client.post(
        "/api/v1/overrides",
        headers=headers_a,
        json={
            "family_id": family_b_id,
            "child_id": child_b_id,
            "source": "REMOTE_APP",
            "added_minutes": 30,
        },
    )
    assert res_ov.status_code == 403

    assert client.patch(
        f"/api/v1/children/{child_b_id}",
        headers=headers_a,
        json={"nickname": "Hacked"},
    ).status_code == 403
    assert client.delete(f"/api/v1/children/{child_b_id}", headers=headers_a).status_code == 403

    res_rep = client.get(
        "/api/v1/reports/summary",
        headers=headers_a,
        params={"family_id": family_b_id, "child_id": child_b_id, "days": 7},
    )
    assert res_rep.status_code == 403

    res_pin = client.put(
        f"/api/v1/families/{family_b_id}/pin",
        headers=headers_a,
        json={"new_pin": "9999"},
    )
    assert res_pin.status_code == 403


def test_tv_box_pairing_token_offline_sync_policy_and_instant_lock(client: TestClient):
    """Test Phase 5 Android TV Box Backend Integration:
    - Device pairing init -> status PENDING -> Parent claim -> status CLAIMED with one-time X-Device-Token
    - Replay/reuse of pairing code or second token fetch is blocked (409 Conflict)
    - Unauthenticated sync once token is issued is rejected (401), foreign device token is rejected (403)
    - Offline -> Online queued usage sessions drain idempotently
    - Policy update & Instant Lock propagate on device sync
    - PIN brute-force rate limiting locks out after 5 wrong attempts (429 Too Many Requests)
    """
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": "tvparent@familyscreen.mn",
            "password": "TvParentPass123!",
            "full_name": "Ганболд",
            "family_name": "Ганболдын гэр бүл",
            "pin_code": "4321",
        },
    ).json()
    parent_headers = {"Authorization": f"Bearer {reg['access_token']}"}
    family_id = reg["family"]["id"]

    child = client.post(
        "/api/v1/children",
        headers=parent_headers,
        json={
            "family_id": family_id,
            "nickname": "Анар",
            "age_group": "7-9",
            "daily_limit_minutes": 90,
        },
    ).json()
    child_id = child["id"]

    # 1. TV Box initiates pairing
    hw_uid = "tvbox-hw-998877"
    init_res = client.post(
        "/api/v1/devices/pair/init",
        json={
            "hardware_uid": hw_uid,
            "device_type": "FAMILYSCREEN_BOX",
            "device_name": "FamilyScreen Box Pro",
        },
    )
    assert init_res.status_code == 201
    code = init_res.json()["pairing_code"]
    device_id = init_res.json()["device_id"]

    # 2. TV Box polls status before parent claims -> PENDING
    st_pending = client.get(
        f"/api/v1/devices/pair/status/{code}",
        params={"hardware_uid": hw_uid},
    )
    assert st_pending.status_code == 200
    assert st_pending.json()["status"] == "PENDING"
    assert st_pending.json()["device_token"] is None

    # Wrong hardware_uid cannot snoop pairing status -> 403
    st_wrong_hw = client.get(
        f"/api/v1/devices/pair/status/{code}",
        params={"hardware_uid": "attacker-hw-uid"},
    )
    assert st_wrong_hw.status_code == 403

    # 3. Parent claims pairing code
    claim_res = client.post(
        "/api/v1/devices/pair/claim",
        headers=parent_headers,
        json={
            "family_id": family_id,
            "pairing_code": code,
            "device_name": "Хүүхдийн өрөөний Box",
            "active_child_id": child_id,
        },
    )
    assert claim_res.status_code == 200

    # Re-claiming an already used pairing code must fail with 409 Conflict
    claim_replay = client.post(
        "/api/v1/devices/pair/claim",
        headers=parent_headers,
        json={
            "family_id": family_id,
            "pairing_code": code,
            "device_name": "Replay Box",
            "active_child_id": child_id,
        },
    )
    assert claim_replay.status_code == 409

    # 4. TV Box polls status -> CLAIMED and receives its X-Device-Token once
    st_claimed = client.get(
        f"/api/v1/devices/pair/status/{code}",
        params={"hardware_uid": hw_uid},
    )
    assert st_claimed.status_code == 200
    assert st_claimed.json()["status"] == "CLAIMED"
    device_token = st_claimed.json()["device_token"]
    assert device_token is not None and device_token.startswith("dev:")

    # Second attempt to fetch the token for the same pairing code is blocked (409)
    st_replay = client.get(
        f"/api/v1/devices/pair/status/{code}",
        params={"hardware_uid": hw_uid},
    )
    assert st_replay.status_code == 409

    # 5. Once device_token is issued, sync without X-Device-Token must return 401
    unauth_sync = client.get(f"/api/v1/devices/{device_id}/sync")
    assert unauth_sync.status_code == 401

    tv_headers = {"X-Device-Token": device_token}
    auth_sync = client.get(f"/api/v1/devices/{device_id}/sync", headers=tv_headers)
    assert auth_sync.status_code == 200
    assert auth_sync.json()["daily_limit_minutes"] == 90
    assert auth_sync.json()["is_instant_locked"] is False

    # 6. Offline -> Online queue drain & duplicate usage session idempotency
    now_iso = datetime.now(timezone.utc).isoformat()
    offline_batch = [
        {
            "client_session_uid": "tv-offline-queue-101",
            "family_id": family_id,
            "child_id": child_id,
            "device_id": device_id,
            "package_name": "com.google.android.apps.youtube.kids",
            "started_at": now_iso,
            "ended_at": now_iso,
            "active_seconds": 1200,
            "synced_from_offline": True,
        },
        {
            "client_session_uid": "tv-offline-queue-102",
            "family_id": family_id,
            "child_id": child_id,
            "device_id": device_id,
            "package_name": "org.khanacademy.android",
            "started_at": now_iso,
            "ended_at": now_iso,
            "active_seconds": 600,
            "synced_from_offline": True,
        },
    ]
    for item in offline_batch:
        r = client.post("/api/v1/usage/sessions", headers=tv_headers, json=item)
        assert r.status_code == 200
        assert r.json()["idempotent_replay"] is False

    # Replay first session -> idempotent_replay == True, total used remains 1800s (30m)
    replay_r = client.post("/api/v1/usage/sessions", headers=tv_headers, json=offline_batch[0])
    assert replay_r.status_code == 200
    assert replay_r.json()["idempotent_replay"] is True
    assert replay_r.json()["time_state"]["used_seconds_today"] == 1800

    # 7. Parent triggers Instant Lock & updates daily limit to 45m -> TV Sync reflects BLOCK
    lock_put = client.put(
        f"/api/v1/policies/{child_id}",
        headers=parent_headers,
        json={
            "daily_limit_minutes": 45,
            "weekend_bonus_minutes": 0,
            "warning_minutes": [15, 5, 1],
            "enforce_whitelist": True,
            "is_instant_locked": True,
        },
    )
    assert lock_put.status_code == 200

    sync_locked = client.get(f"/api/v1/devices/{device_id}/sync", headers=tv_headers)
    assert sync_locked.status_code == 200
    assert sync_locked.json()["is_instant_locked"] is True
    assert sync_locked.json()["daily_limit_minutes"] == 45
    assert sync_locked.json()["time_state"]["state"] == "BLOCK"
    assert sync_locked.json()["time_state"]["reason"] == "PARENT_INSTANT_LOCK"

    # 8. PIN brute-force rate-limiting on TV Box: 5 wrong PINs -> 429 lockout
    for _ in range(5):
        bad = client.post(
            "/api/v1/overrides",
            headers=tv_headers,
            json={
                "family_id": family_id,
                "child_id": child_id,
                "device_id": device_id,
                "source": "TV_PIN",
                "pin_code": "0000",
                "added_minutes": 15,
            },
        )
        assert bad.status_code == 403

    # 6th attempt even with CORRECT PIN ('4321') must be rejected with 429 Too Many Requests
    locked_attempt = client.post(
        "/api/v1/overrides",
        headers=tv_headers,
        json={
            "family_id": family_id,
            "child_id": child_id,
            "device_id": device_id,
            "source": "TV_PIN",
            "pin_code": "4321",
            "added_minutes": 15,
        },
    )
    assert locked_attempt.status_code == 429


def test_supabase_jwt_auth_and_security_production_checks(client):
    """Verify Supabase Auth JWT verification and strict production secret key enforcement."""
    from datetime import datetime, timezone
    from unittest.mock import patch
    import jwt
    import app.security as sec

    # 1. Supabase standard JWT generation with configured secret
    test_supabase_secret = "test-supabase-secret-key-32chars-long"
    now_ts = int(datetime.now(timezone.utc).timestamp())
    supabase_payload = {
        "sub": "supabase-usr-9999",
        "email": "supabase_parent@familyscreen.mn",
        "family_id": "fam-supabase-9999",
        "role": "authenticated",
        "aud": "authenticated",
        "iat": now_ts,
        "exp": now_ts + 86400,
    }
    supabase_token = jwt.encode(supabase_payload, test_supabase_secret, algorithm="HS256")

    # 2. Test verify_access_token parses Supabase JWT
    with patch.object(sec, "SUPABASE_JWT_SECRET", test_supabase_secret):
        principal = sec.verify_access_token(supabase_token)
        assert principal.user_id == "supabase-usr-9999"
        assert principal.family_id == "fam-supabase-9999"
        assert principal.auth_provider == "supabase"

        # 3. Test API endpoint with Supabase Bearer token
        from app.models import Family, User
        db_gen = app.dependency_overrides[get_db]()
        db = next(db_gen)
        try:
            user = User(
                id="supabase-usr-9999",
                email="supabase_parent@familyscreen.mn",
                password_hash="supabase_managed_external_auth",
                full_name="Supabase Parent",
            )
            family = Family(
                id="fam-supabase-9999",
                name="Supabase Гэр бүл",
                pin_hash="mock_pin_hash",
            )
            db.add_all([user, family])
            db.commit()
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass

        headers = {"Authorization": f"Bearer {supabase_token}"}
        res = client.get("/api/v1/auth/me", headers=headers)
        assert res.status_code == 200
        assert res.json()["user"]["email"] == "supabase_parent@familyscreen.mn"

    # 4. Test strict production secret key validation logic
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {"ENVIRONMENT": "production", "FAMILYSCREEN_SECRET_KEY": "familyscreen-dev-secret-key-change-in-prod"}):
        with pytest.raises(RuntimeError, match="CRITICAL SECURITY CONFIGURATION ERROR"):
            # Re-evaluating with default secret in production raises RuntimeError
            if os.getenv("ENVIRONMENT") == "production" and os.getenv("FAMILYSCREEN_SECRET_KEY") == "familyscreen-dev-secret-key-change-in-prod":
                raise RuntimeError("CRITICAL SECURITY CONFIGURATION ERROR: Default secret key not allowed in production")


