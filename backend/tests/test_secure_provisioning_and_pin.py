"""Comprehensive security test suite for Phase 8: Secure Family Provisioning & PIN Initialization.

Validates:
1. Complete removal of default PIN ("2580") across provisioning and sync flows.
2. Mandatory parent PIN initialization via POST /api/v1/families/{id}/pin/init.
3. Strict current_pin verification and rate-limiting lockout on PUT /api/v1/families/{id}/pin.
4. Prevention of account takeover (ATO) by email alone when Supabase user signs in.
5. Explicit, cryptographically verified account linking via POST /api/v1/auth/supabase/link-account.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.security as sec
from app.database import Base, get_db
from app.main import app
from app.models import Family, User


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

    TestingSession = sessionmaker(bind=test_engine, expire_on_commit=False)
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        c.TestingSession = TestingSession
        yield c
    app.dependency_overrides.clear()
    sec.jwks_manager.clear_test_jwks()


def _generate_rsa_pair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv, priv.public_key()


def _rsa_to_jwk_dict(public_key, kid: str = "phase8-key") -> dict:
    pub_numbers = public_key.public_numbers()

    def _to_b64(num: int) -> str:
        b = num.to_bytes((num.bit_length() + 7) // 8, byteorder="big")
        return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")

    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _to_b64(pub_numbers.n),
        "e": _to_b64(pub_numbers.e),
    }


# ---------------------------------------------------------------------------
# Test 1: No default PIN on newly provisioned Supabase family
# ---------------------------------------------------------------------------
def test_01_no_default_pin_on_new_supabase_family(client: TestClient):
    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-01")]})

    now_ts = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode(
        {
            "sub": "sup-user-clean-01",
            "email": "clean_user@familyscreen.mn",
            "user_metadata": {"full_name": "Шинэ Хэрэглэгч"},
            "aud": "authenticated",
            "exp": now_ts + 3600,
        },
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-01"},
    )

    headers = {"Authorization": f"Bearer {token}"}
    res = client.get("/api/v1/auth/me", headers=headers)
    assert res.status_code == 200
    data = res.json()

    # Family must report pin_configured == False
    assert data["family"]["pin_configured"] is False
    fam_id = data["family"]["id"]

    # Verify directly in SQLite that pin_hash is None (no default '2580')
    db = client.TestingSession()
    family = db.get(Family, fam_id)
    assert family is not None
    assert family.pin_hash is None
    assert family.pin_configured is False
    db.close()


# ---------------------------------------------------------------------------
# Test 2: Explicit PIN Initialization Success
# ---------------------------------------------------------------------------
def test_02_explicit_pin_init_success(client: TestClient):
    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-02")]})

    now_ts = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode(
        {
            "sub": "sup-user-init-02",
            "email": "init_user@familyscreen.mn",
            "user_metadata": {"full_name": "Эцэг эх"},
            "aud": "authenticated",
            "exp": now_ts + 3600,
        },
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-02"},
    )
    headers = {"Authorization": f"Bearer {token}"}
    me_res = client.get("/api/v1/auth/me", headers=headers)
    fam_id = me_res.json()["family"]["id"]
    local_token = me_res.json()["access_token"]
    authed_headers = {"Authorization": f"Bearer {local_token}"}

    # Initialize PIN to '6543'
    init_res = client.post(
        f"/api/v1/families/{fam_id}/pin/init",
        headers=authed_headers,
        json={"new_pin": "6543"},
    )
    assert init_res.status_code == 200
    assert "амжилттай" in init_res.json()["message"]

    # Now /auth/me must report pin_configured == True
    me_after = client.get("/api/v1/auth/me", headers=authed_headers)
    assert me_after.json()["family"]["pin_configured"] is True


# ---------------------------------------------------------------------------
# Test 3: PIN Init Rejects If Already Configured
# ---------------------------------------------------------------------------
def test_03_pin_init_rejects_if_already_configured(client: TestClient):
    # Register local family with PIN '1234'
    reg_res = client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner@familyscreen.mn",
            "password": "Password123!",
            "full_name": "Бат",
            "family_name": "Батын гэр",
            "pin_code": "1234",
        },
    )
    assert reg_res.status_code == 201
    fam_id = reg_res.json()["family"]["id"]
    token = reg_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Attempting to re-init must return 409 Conflict
    init_res = client.post(
        f"/api/v1/families/{fam_id}/pin/init",
        headers=headers,
        json={"new_pin": "9999"},
    )
    assert init_res.status_code == 409
    assert "аль хэдийн тохируулагдсан" in init_res.json()["detail"]


# ---------------------------------------------------------------------------
# Test 4: PIN Init Rejects Invalid Format
# ---------------------------------------------------------------------------
def test_04_pin_init_rejects_invalid_format(client: TestClient):
    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-04")]})

    now_ts = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode(
        {"sub": "user-fmt-04", "email": "fmt@familyscreen.mn", "aud": "authenticated", "exp": now_ts + 3600},
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-04"},
    )
    me_res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    fam_id = me_res.json()["family"]["id"]
    local_token = me_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {local_token}"}

    # Too short (2 digits)
    res_short = client.post(f"/api/v1/families/{fam_id}/pin/init", headers=headers, json={"new_pin": "12"})
    assert res_short.status_code == 422

    # Non-numeric
    res_chars = client.post(f"/api/v1/families/{fam_id}/pin/init", headers=headers, json={"new_pin": "abcd"})
    assert res_chars.status_code == 422

    # Too long (7 digits)
    res_long = client.post(f"/api/v1/families/{fam_id}/pin/init", headers=headers, json={"new_pin": "1234567"})
    assert res_long.status_code == 422


# ---------------------------------------------------------------------------
# Test 5: PIN Init Requires Owner Role & Correct Family Access
# ---------------------------------------------------------------------------
def test_05_pin_init_requires_owner_role(client: TestClient):
    # Create family A
    reg_a = client.post(
        "/api/v1/auth/register",
        json={
            "email": "user_a@familyscreen.mn",
            "password": "Password123!",
            "full_name": "User A",
            "family_name": "Family A",
            "pin_code": "1111",
        },
    )
    fam_a_id = reg_a.json()["family"]["id"]

    # Create family B (unconfigured PIN)
    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-05")]})
    now_ts = int(datetime.now(timezone.utc).timestamp())
    token_b = jwt.encode(
        {"sub": "user-b-05", "email": "user_b@familyscreen.mn", "aud": "authenticated", "exp": now_ts + 3600},
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-05"},
    )
    me_b = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"})
    token_b_local = me_b.json()["access_token"]

    # User B attempts to initialize Family A's PIN -> 403 Forbidden
    cross_res = client.post(
        f"/api/v1/families/{fam_a_id}/pin/init",
        headers={"Authorization": f"Bearer {token_b_local}"},
        json={"new_pin": "8888"},
    )
    assert cross_res.status_code == 403


# ---------------------------------------------------------------------------
# Test 6: Update PIN Requires Current PIN When Configured
# ---------------------------------------------------------------------------
def test_06_update_pin_requires_current_pin_when_configured(client: TestClient):
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": "pin_req@familyscreen.mn",
            "password": "Password123!",
            "full_name": "Bold",
            "family_name": "Bold Family",
            "pin_code": "3333",
        },
    )
    fam_id = reg.json()["family"]["id"]
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

    # Attempt update WITHOUT current_pin
    res = client.put(
        f"/api/v1/families/{fam_id}/pin",
        headers=headers,
        json={"new_pin": "4444"},
    )
    assert res.status_code == 400
    assert "заавал" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Test 7: Update PIN Wrong Current PIN Increments Attempts & Locks Out
# ---------------------------------------------------------------------------
def test_07_update_pin_wrong_current_pin_increments_attempts_and_locks(client: TestClient):
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": "lockout@familyscreen.mn",
            "password": "Password123!",
            "full_name": "Naraa",
            "family_name": "Naraa Family",
            "pin_code": "1234",
        },
    )
    fam_id = reg.json()["family"]["id"]
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

    # 4 failed attempts -> 403
    for _ in range(4):
        res = client.put(
            f"/api/v1/families/{fam_id}/pin",
            headers=headers,
            json={"current_pin": "0000", "new_pin": "5555"},
        )
        assert res.status_code == 403

    # 5th failed attempt -> 429 Too Many Requests (Lockout)
    res5 = client.put(
        f"/api/v1/families/{fam_id}/pin",
        headers=headers,
        json={"current_pin": "0000", "new_pin": "5555"},
    )
    assert res5.status_code == 429
    assert "түгжигдлээ" in res5.json()["detail"] or "15 минут" in res5.json()["detail"]

    # Even with the CORRECT PIN, during lockout period, request is blocked (429)
    res_during_lockout = client.put(
        f"/api/v1/families/{fam_id}/pin",
        headers=headers,
        json={"current_pin": "1234", "new_pin": "5555"},
    )
    assert res_during_lockout.status_code == 429


# ---------------------------------------------------------------------------
# Test 8: Update PIN Success Resets Attempts
# ---------------------------------------------------------------------------
def test_08_update_pin_success_resets_attempts(client: TestClient):
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": "reset@familyscreen.mn",
            "password": "Password123!",
            "full_name": "Zaya",
            "family_name": "Zaya Family",
            "pin_code": "7777",
        },
    )
    fam_id = reg.json()["family"]["id"]
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}

    # 2 failed attempts
    client.put(f"/api/v1/families/{fam_id}/pin", headers=headers, json={"current_pin": "0000", "new_pin": "8888"})
    client.put(f"/api/v1/families/{fam_id}/pin", headers=headers, json={"current_pin": "0000", "new_pin": "8888"})

    # Correct update
    res_ok = client.put(
        f"/api/v1/families/{fam_id}/pin",
        headers=headers,
        json={"current_pin": "7777", "new_pin": "8888"},
    )
    assert res_ok.status_code == 200

    # Direct DB inspection: failed attempts reset to 0
    db = client.TestingSession()
    family = db.get(Family, fam_id)
    assert family.pin_failed_attempts == 0
    assert family.pin_locked_until is None
    db.close()


# ---------------------------------------------------------------------------
# Test 9: Prevent Account Takeover by Email Alone
# ---------------------------------------------------------------------------
def test_09_prevent_account_takeover_by_email_alone(client: TestClient):
    # 1. Legitimate local user registers with email 'victim@familyscreen.mn'
    reg_victim = client.post(
        "/api/v1/auth/register",
        json={
            "email": "victim@familyscreen.mn",
            "password": "VictimStrongPassword123!",
            "full_name": "Хохирогч Эцэг",
            "family_name": "Хохирогчийн гэр",
            "pin_code": "4321",
        },
    )
    assert reg_victim.status_code == 201
    victim_fam_id = reg_victim.json()["family"]["id"]

    # 2. Attacker creates an external Supabase account claiming 'victim@familyscreen.mn'
    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-09")]})
    now_ts = int(datetime.now(timezone.utc).timestamp())
    attacker_sub = "attacker-supabase-uuid-999"
    attacker_token = jwt.encode(
        {
            "sub": attacker_sub,
            "email": "victim@familyscreen.mn",
            "user_metadata": {"full_name": "Халдагч"},
            "aud": "authenticated",
            "exp": now_ts + 3600,
        },
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-09"},
    )

    # 3. Attacker calls /api/v1/auth/me -> MUST BE REJECTED with 409 Conflict
    attacker_headers = {"Authorization": f"Bearer {attacker_token}"}
    me_res = client.get("/api/v1/auth/me", headers=attacker_headers)
    assert me_res.status_code == 409
    assert "ACCOUNT_LINKING_REQUIRED" in me_res.json()["detail"]

    # 4. Attacker calls /api/v1/auth/supabase/sync -> MUST ALSO BE REJECTED with 409 Conflict
    sync_res = client.post(
        "/api/v1/auth/supabase/sync",
        headers=attacker_headers,
        json={"family_name": "Hijacked Family"},
    )
    assert sync_res.status_code == 409
    assert "ACCOUNT_LINKING_REQUIRED" in sync_res.json()["detail"]

    # 5. Verify victim's family is completely untouched
    db = client.TestingSession()
    victim_fam = db.get(Family, victim_fam_id)
    assert victim_fam.name == "Хохирогчийн гэр"
    db.close()


# ---------------------------------------------------------------------------
# Test 10: Account Link Rejects Unverified Supabase Email
# ---------------------------------------------------------------------------
def test_10_account_link_rejects_unverified_supabase_email(client: TestClient):
    # Register local user
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "unverified@familyscreen.mn",
            "password": "LocalPassword123!",
            "full_name": "Баталгаажаагүй",
            "family_name": "Гэр бүл",
            "pin_code": "1111",
        },
    )

    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-10")]})
    now_ts = int(datetime.now(timezone.utc).timestamp())

    # Token WITHOUT email_confirmed_at and user_metadata.email_verified is False
    unverified_token = jwt.encode(
        {
            "sub": "sup-unverified-10",
            "email": "unverified@familyscreen.mn",
            "user_metadata": {"email_verified": False},
            "aud": "authenticated",
            "exp": now_ts + 3600,
        },
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-10"},
    )

    res = client.post(
        "/api/v1/auth/supabase/link-account",
        headers={"Authorization": f"Bearer {unverified_token}"},
        json={"local_password": "LocalPassword123!"},
    )
    assert res.status_code == 403
    assert "баталгаажаагүй" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Test 11: Account Link Rejects Wrong Local Password
# ---------------------------------------------------------------------------
def test_11_account_link_rejects_wrong_local_password(client: TestClient):
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "link_test@familyscreen.mn",
            "password": "CorrectPassword123!",
            "full_name": "Төмөр",
            "family_name": "Төмөрийн гэр",
            "pin_code": "2222",
        },
    )

    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-11")]})
    now_ts = int(datetime.now(timezone.utc).timestamp())

    verified_token = jwt.encode(
        {
            "sub": "sup-verified-11",
            "email": "link_test@familyscreen.mn",
            "email_confirmed_at": "2026-11-09T00:00:00Z",
            "aud": "authenticated",
            "exp": now_ts + 3600,
        },
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-11"},
    )

    res = client.post(
        "/api/v1/auth/supabase/link-account",
        headers={"Authorization": f"Bearer {verified_token}"},
        json={"local_password": "WrongPassword!"},
    )
    assert res.status_code == 401
    assert "нууц үг буруу" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Test 12: Account Link Success Bridges Accounts
# ---------------------------------------------------------------------------
def test_12_account_link_success(client: TestClient):
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": "bridge@familyscreen.mn",
            "password": "MySecretPassword123!",
            "full_name": "Дорж",
            "family_name": "Доржийн гэр",
            "pin_code": "9876",
        },
    )
    original_fam_id = reg.json()["family"]["id"]
    original_user_id = reg.json()["user"]["id"]

    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-12")]})
    now_ts = int(datetime.now(timezone.utc).timestamp())
    sup_sub = "supabase-dorj-sub-12"

    verified_token = jwt.encode(
        {
            "sub": sup_sub,
            "email": "bridge@familyscreen.mn",
            "email_confirmed_at": "2026-11-09T00:00:00Z",
            "aud": "authenticated",
            "exp": now_ts + 3600,
        },
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-12"},
    )

    # 1. Link account
    link_res = client.post(
        "/api/v1/auth/supabase/link-account",
        headers={"Authorization": f"Bearer {verified_token}"},
        json={"local_password": "MySecretPassword123!"},
    )
    assert link_res.status_code == 200
    data = link_res.json()
    assert data["user"]["id"] == original_user_id
    assert data["family"]["id"] == original_fam_id

    # 2. Subsequent /auth/me call with Supabase token now recognizes user cleanly
    me_res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {verified_token}"})
    assert me_res.status_code == 200
    assert me_res.json()["user"]["id"] == original_user_id
    assert me_res.json()["family"]["id"] == original_fam_id

    # 3. Verify in DB that supabase_sub is saved on the user
    db = client.TestingSession()
    user = db.get(User, original_user_id)
    assert user.supabase_sub == sup_sub
    db.close()
