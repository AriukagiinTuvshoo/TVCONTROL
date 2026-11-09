"""Comprehensive security verification suite for Supabase Auth JWT validation,
JWKS key management, claims verification, and FamilyScreen User/Family provisioning.

Verifies the 12 mandatory security test requirements:
1. Valid RS256 JWT — PASS
2. Valid HS256 JWT — PASS (strictly when configured)
3. Invalid signature — REJECT
4. Expired JWT — REJECT
5. Wrong issuer (iss) — REJECT
6. Wrong audience (aud) — REJECT
7. Different Supabase project token — REJECT
8. JWKS key not found — Safe REJECT
9. JWKS key rotation — Handled properly
10. Cross-family data access — REJECT (403 Forbidden)
11. Supabase user not yet in database — JIT provisioning & safe isolation
12. Custom authentication regression — Existing features continue to work
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
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
    """Isolated in-memory test database fixture."""
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
    sec.jwks_manager.clear_test_jwks()


def _generate_rsa_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _rsa_to_jwk_dict(public_key, kid="test-kid-1"):
    jwk_dict = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk_dict["kid"] = kid
    return jwk_dict


# ---------------------------------------------------------------------------
# Test 1: Valid RS256 JWT — PASS
# ---------------------------------------------------------------------------
def test_01_valid_rs256_jwt_pass():
    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-01")]})

    now_ts = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "sub": "user-supabase-001",
        "email": "user001@familyscreen.mn",
        "aud": "authenticated",
        "iat": now_ts,
        "exp": now_ts + 3600,
    }
    token = jwt.encode(payload, priv_key, algorithm="RS256", headers={"kid": "key-01"})

    principal = sec.verify_access_token(token)
    assert principal.user_id == "user-supabase-001"
    assert principal.email == "user001@familyscreen.mn"
    assert principal.auth_provider == "supabase"


# ---------------------------------------------------------------------------
# Test 2: Valid HS256 JWT — PASS only when configured
# ---------------------------------------------------------------------------
def test_02_valid_hs256_jwt_pass_when_configured():
    custom_hs256_secret = "my-custom-supabase-hs256-secret-key-32chars"
    now_ts = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "sub": "user-supabase-002",
        "email": "user002@familyscreen.mn",
        "aud": "authenticated",
        "iat": now_ts,
        "exp": now_ts + 3600,
    }
    token = jwt.encode(payload, custom_hs256_secret, algorithm="HS256")

    # A) When secret is configured -> PASS
    with patch.object(sec, "SUPABASE_JWT_SECRET", custom_hs256_secret):
        principal = sec.verify_access_token(token)
        assert principal.user_id == "user-supabase-002"
        assert principal.auth_provider == "supabase"

    # B) When secret is NOT configured -> REJECT with 401
    with patch.object(sec, "SUPABASE_JWT_SECRET", None):
        with pytest.raises(sec.HTTPException) as exc_info:
            sec.verify_access_token(token)
        assert exc_info.value.status_code == 401
        assert "HS256" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Test 3: Invalid Signature — REJECT
# ---------------------------------------------------------------------------
def test_03_invalid_signature_reject():
    priv_key_real, pub_key_real = _generate_rsa_pair()
    priv_key_attacker, _ = _generate_rsa_pair()

    # Server trusts pub_key_real
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key_real, "key-real")]})

    # Attacker signs token with different key
    now_ts = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode(
        {"sub": "user-attacker", "aud": "authenticated", "exp": now_ts + 3600},
        priv_key_attacker,
        algorithm="RS256",
        headers={"kid": "key-real"},
    )

    with pytest.raises(sec.HTTPException) as exc_info:
        sec.verify_access_token(token)
    assert exc_info.value.status_code == 401
    assert "хүчингүй" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Test 4: Expired JWT — REJECT
# ---------------------------------------------------------------------------
def test_04_expired_jwt_reject():
    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-04")]})

    past_ts = int(datetime.now(timezone.utc).timestamp()) - 1000
    token = jwt.encode(
        {"sub": "user-expired", "aud": "authenticated", "iat": past_ts - 3600, "exp": past_ts},
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-04"},
    )

    with pytest.raises(sec.HTTPException) as exc_info:
        sec.verify_access_token(token)
    assert exc_info.value.status_code == 401
    assert "дууссан" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Test 5: Wrong Issuer (iss) — REJECT
# ---------------------------------------------------------------------------
def test_05_wrong_issuer_reject():
    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-05")]})

    now_ts = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode(
        {
            "sub": "user-wrong-iss",
            "aud": "authenticated",
            "iss": "https://attacker.evil.com/auth/v1",
            "exp": now_ts + 3600,
        },
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-05"},
    )

    with patch.object(sec, "SUPABASE_JWT_ISSUER", "https://official-project.supabase.co/auth/v1"):
        with pytest.raises(sec.HTTPException) as exc_info:
            sec.verify_access_token(token)
        assert exc_info.value.status_code == 401
        assert "issuer" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Test 6: Wrong Audience (aud) — REJECT
# ---------------------------------------------------------------------------
def test_06_wrong_audience_reject():
    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-06")]})

    now_ts = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode(
        {"sub": "user-bad-aud", "aud": "anonymous", "exp": now_ts + 3600},
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-06"},
    )

    with pytest.raises(sec.HTTPException) as exc_info:
        sec.verify_access_token(token)
    assert exc_info.value.status_code == 401
    assert "audience" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Test 7: Different Supabase Project Token — REJECT
# ---------------------------------------------------------------------------
def test_07_different_supabase_project_token_reject():
    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-07")]})

    now_ts = int(datetime.now(timezone.utc).timestamp())
    token_project_b = jwt.encode(
        {
            "sub": "user-proj-b",
            "aud": "authenticated",
            "iss": "https://project-b.supabase.co/auth/v1",
            "exp": now_ts + 3600,
        },
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-07"},
    )

    with patch.object(sec, "SUPABASE_JWT_ISSUER", "https://project-a.supabase.co/auth/v1"):
        with pytest.raises(sec.HTTPException) as exc_info:
            sec.verify_access_token(token_project_b)
        assert exc_info.value.status_code == 401
        assert "өөр project" in exc_info.value.detail or "issuer" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Test 8: JWKS Key Not Found — Safe REJECT
# ---------------------------------------------------------------------------
def test_08_jwks_key_not_found_safe_reject():
    priv_key, pub_key = _generate_rsa_pair()
    # JWKS only has key-alpha
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-alpha")]})

    now_ts = int(datetime.now(timezone.utc).timestamp())
    # Token requests unknown kid "key-ghost"
    token = jwt.encode(
        {"sub": "user-ghost", "aud": "authenticated", "exp": now_ts + 3600},
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-ghost"},
    )

    with pytest.raises(sec.HTTPException) as exc_info:
        sec.verify_access_token(token)
    assert exc_info.value.status_code == 401
    assert "түлхүүр" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Test 9: JWKS Key Rotation Handled Properly
# ---------------------------------------------------------------------------
def test_09_jwks_key_rotation_handled_properly():
    priv_key1, pub_key1 = _generate_rsa_pair()
    priv_key2, pub_key2 = _generate_rsa_pair()

    now_ts = int(datetime.now(timezone.utc).timestamp())
    token1 = jwt.encode(
        {"sub": "user-rot-1", "aud": "authenticated", "exp": now_ts + 3600},
        priv_key1,
        algorithm="RS256",
        headers={"kid": "rot-key-1"},
    )
    token2 = jwt.encode(
        {"sub": "user-rot-2", "aud": "authenticated", "exp": now_ts + 3600},
        priv_key2,
        algorithm="RS256",
        headers={"kid": "rot-key-2"},
    )

    # Initially only rot-key-1 is active
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key1, "rot-key-1")]})
    assert sec.verify_access_token(token1).user_id == "user-rot-1"

    # Token signed with rotated key-2 fails before rotation
    with pytest.raises(sec.HTTPException):
        sec.verify_access_token(token2)

    # Supabase performs key rotation: JWKS now includes rot-key-2
    sec.jwks_manager.set_test_jwks({
        "keys": [
            _rsa_to_jwk_dict(pub_key1, "rot-key-1"),
            _rsa_to_jwk_dict(pub_key2, "rot-key-2"),
        ]
    })
    # Now token2 immediately passes
    assert sec.verify_access_token(token2).user_id == "user-rot-2"


# ---------------------------------------------------------------------------
# Test 10: Cross-Family Access with Supabase Token — REJECT (403)
# ---------------------------------------------------------------------------
def test_10_cross_family_access_supabase_reject(client: TestClient):
    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-10")]})

    now_ts = int(datetime.now(timezone.utc).timestamp())
    token_a = jwt.encode(
        {
            "sub": "user-sup-a",
            "email": "user_a@familyscreen.mn",
            "family_id": "fam-alpha",
            "aud": "authenticated",
            "exp": now_ts + 3600,
        },
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-10"},
    )

    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Register/sync user A in database
    sync_res = client.post(
        "/api/v1/auth/supabase/sync",
        headers=headers_a,
        json={"family_name": "Family Alpha", "pin_code": "1111"},
    )
    assert sync_res.status_code == 200
    fam_a_id = sync_res.json()["family"]["id"]

    # Try to access a completely different family's children
    cross_res = client.get("/api/v1/families/fam-foreign-999/children", headers=headers_a)
    assert cross_res.status_code == 403
    assert "өөр гэр бүл" in cross_res.json()["detail"]


# ---------------------------------------------------------------------------
# Test 11: Supabase User JIT Provisioning on /auth/me — PASS
# ---------------------------------------------------------------------------
def test_11_supabase_user_jit_provisioning(client: TestClient):
    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-11")]})

    now_ts = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode(
        {
            "sub": "user-new-parent-001",
            "email": "new_parent@familyscreen.mn",
            "user_metadata": {"full_name": "Бат-Эрдэнэ"},
            "aud": "authenticated",
            "exp": now_ts + 3600,
        },
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-11"},
    )

    # 1. First time call: User does NOT exist in DB yet
    headers = {"Authorization": f"Bearer {token}"}
    me_res = client.get("/api/v1/auth/me", headers=headers)
    assert me_res.status_code == 200
    data = me_res.json()
    assert data["user"]["id"] == "user-new-parent-001"
    assert data["user"]["email"] == "new_parent@familyscreen.mn"
    assert data["user"]["full_name"] == "Бат-Эрдэнэ"
    assert "Бат-Эрдэнэ" in data["family"]["name"]

    # 2. Second call returns the existing account cleanly without duplicate error
    me_res2 = client.get("/api/v1/auth/me", headers=headers)
    assert me_res2.status_code == 200
    assert me_res2.json()["family"]["id"] == data["family"]["id"]


# ---------------------------------------------------------------------------
# Test 12: Custom Authentication Regression — PASS
# ---------------------------------------------------------------------------
def test_12_custom_authentication_regression(client: TestClient):
    # 1. Custom Register
    reg_res = client.post(
        "/api/v1/auth/register",
        json={
            "email": "custom_parent@familyscreen.mn",
            "password": "Password123!",
            "full_name": "Хүслэн",
            "family_name": "Хүслэнгийн гэр бүл",
            "pin_code": "5555",
        },
    )
    assert reg_res.status_code == 201
    custom_token = reg_res.json()["access_token"]
    assert custom_token.count(".") == 1  # HMAC token has 1 dot

    # 2. Access /auth/me with custom HMAC token
    me_res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {custom_token}"})
    assert me_res.status_code == 200
    assert me_res.json()["user"]["email"] == "custom_parent@familyscreen.mn"

    # 3. Custom Login
    login_res = client.post(
        "/api/v1/auth/login",
        json={
            "email": "custom_parent@familyscreen.mn",
            "password": "Password123!",
        },
    )
    assert login_res.status_code == 200
    assert login_res.json()["access_token"] != ""
