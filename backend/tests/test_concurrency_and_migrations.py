"""Concurrency, Race-Condition Protection, and Database Migration Test Suite.

Validates:
1. Zero-downtime database migration and rollback with existing users and families.
2. Serialization and race-condition prevention for concurrent PIN initializations (POST /pin/init).
3. Concurrency protection preventing multiple Supabase identities from claiming the same local account.
4. Idempotent concurrent JIT provisioning without duplicate families or unhandled integrity errors.
5. Strict OWNER role requirement for PIN updates (MEMBER/GUEST rejected with 403 Forbidden).
"""

from __future__ import annotations

import base64
import concurrent.futures
from datetime import datetime, timezone
import os
import tempfile

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

import app.security as sec
from app.database import Base, get_db
from app.main import app
from app.migrations import (
    MIGRATION_ADVISORY_LOCK_ID,
    Migration,
    MigrationLockTimeoutError,
    MIGRATIONS,
    _sqlite_migration_lock,
    get_applied_migrations,
    init_db,
    migration_lock,
    rollback_migration,
    run_migrations,
)
from app.models import Family, FamilyMember, User


@pytest.fixture()
def client(tmp_path):
    """Isolated database fixture supporting genuine multi-threaded concurrency."""
    db_file = tmp_path / "test_concurrency.db"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"timeout": 30.0},
        future=True,
    )

    @event.listens_for(test_engine, "connect")
    def _fk_pragma(dbapi_conn, conn_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
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
        c.test_engine = test_engine
        yield c
    app.dependency_overrides.clear()
    sec.jwks_manager.clear_test_jwks()


def _generate_rsa_pair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv, priv.public_key()


def _rsa_to_jwk_dict(public_key, kid: str = "conc-key") -> dict:
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
# Test 1: Migration and Rollback Safety with Existing Production Data
# ---------------------------------------------------------------------------
def test_migration_upgrade_and_downgrade_with_existing_data(tmp_path):
    db_file = tmp_path / "test_migration.db"
    standalone_engine = create_engine(f"sqlite:///{db_file}")

    # 1. Create legacy users table WITHOUT supabase_sub
    with standalone_engine.begin() as conn:
        conn.execute(
            text(
                """
            CREATE TABLE users (
                id VARCHAR(36) PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                phone VARCHAR(32),
                password_hash VARCHAR(255) NOT NULL,
                full_name VARCHAR(120) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """
            )
        )
        conn.execute(
            text(
                """
            INSERT INTO users (id, email, password_hash, full_name, created_at, updated_at)
            VALUES ('u-legacy-1', 'legacy_user@familyscreen.mn', 'hash123', 'Legacy User', '2026-01-01 00:00:00', '2026-01-01 00:00:00')
        """
            )
        )

    # 2. Run migrations
    applied = run_migrations(standalone_engine)
    assert "001_add_supabase_sub_to_users" in applied

    # 3. Verify column and index exist and legacy user data is preserved
    with standalone_engine.connect() as conn:
        users = conn.execute(text("SELECT id, email, supabase_sub FROM users")).fetchall()
        assert len(users) == 1
        assert users[0][0] == "u-legacy-1"
        assert users[0][1] == "legacy_user@familyscreen.mn"
        assert users[0][2] is None

        # Verify uniqueness of supabase_sub
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, supabase_sub, created_at, updated_at) "
                "VALUES ('u-sub-1', 'sub1@test.mn', 'h', 'N', 'sub-unique-100', '2026-01-01', '2026-01-01')"
            )
        )
        with pytest.raises(Exception):
            conn.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, full_name, supabase_sub, created_at, updated_at) "
                    "VALUES ('u-sub-2', 'sub2@test.mn', 'h', 'N', 'sub-unique-100', '2026-01-01', '2026-01-01')"
                )
            )

    # 4. Rollback migration
    rolled = rollback_migration(standalone_engine)
    assert "001_add_supabase_sub_to_users" in rolled
    with standalone_engine.connect() as conn:
        cols = [c[1] for c in conn.execute(text("PRAGMA table_info(users)")).fetchall()]
        assert "supabase_sub" not in cols
        users_after = conn.execute(text("SELECT id, email FROM users")).fetchall()
        assert any(u[0] == "u-legacy-1" for u in users_after)


# ---------------------------------------------------------------------------
# Test 1.1: Empty Database Initialization
# ---------------------------------------------------------------------------
def test_empty_database_initialization(tmp_path):
    """Ensure init_db safely initializes a completely fresh/empty database."""
    db_file = tmp_path / "fresh_empty.db"
    fresh_engine = create_engine(f"sqlite:///{db_file}")

    # Run init_db on brand new empty database
    applied = init_db(fresh_engine)
    assert "001_add_supabase_sub_to_users" in applied

    # Verify all core tables and the migration tracker exist
    with fresh_engine.connect() as conn:
        tables = [r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()]
        assert "users" in tables
        assert "families" in tables
        assert "devices" in tables
        assert "schema_migrations" in tables

        # Verify supabase_sub column exists on users table
        cols = [c[1] for c in conn.execute(text("PRAGMA table_info(users)")).fetchall()]
        assert "supabase_sub" in cols

        # Verify migration record is stored
        versions = [r[0] for r in conn.execute(text("SELECT version FROM schema_migrations")).fetchall()]
        assert "001_add_supabase_sub_to_users" in versions


# ---------------------------------------------------------------------------
# Test 1.2: Existing Database Upgrade
# ---------------------------------------------------------------------------
def test_existing_database_upgrade(tmp_path):
    """Ensure init_db upgrades an existing database without data loss."""
    db_file = tmp_path / "existing_db.db"
    existing_engine = create_engine(f"sqlite:///{db_file}")

    # Seed legacy users table without supabase_sub
    with existing_engine.begin() as conn:
        conn.execute(
            text(
                """
            CREATE TABLE users (
                id VARCHAR(36) PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                phone VARCHAR(32),
                password_hash VARCHAR(255) NOT NULL,
                full_name VARCHAR(120) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
        """
            )
        )
        conn.execute(
            text(
                """
            INSERT INTO users (id, email, password_hash, full_name, created_at, updated_at)
            VALUES ('u-exist-1', 'existing@familyscreen.mn', 'hash456', 'Existing User', '2026-01-01', '2026-01-01')
        """
            )
        )

    # Run init_db on existing database
    applied = init_db(existing_engine)
    assert "001_add_supabase_sub_to_users" in applied

    # Verify legacy user is untouched and supabase_sub column is now present
    with existing_engine.connect() as conn:
        row = conn.execute(text("SELECT id, email, supabase_sub FROM users WHERE id='u-exist-1'")).fetchone()
        assert row is not None
        assert row[0] == "u-exist-1"
        assert row[1] == "existing@familyscreen.mn"
        assert row[2] is None


# ---------------------------------------------------------------------------
# Test 1.3: Repeated Migration Execution (Idempotency)
# ---------------------------------------------------------------------------
def test_repeated_migration_execution_is_idempotent(tmp_path):
    """Ensure repeated migration runs produce identical results with zero errors."""
    db_file = tmp_path / "idempotent.db"
    engine = create_engine(f"sqlite:///{db_file}")

    first_run = init_db(engine)
    assert "001_add_supabase_sub_to_users" in first_run

    # Second run should apply 0 migrations
    second_run = run_migrations(engine)
    assert second_run == []

    # Third run should still apply 0 migrations
    third_run = run_migrations(engine)
    assert third_run == []

    with engine.connect() as conn:
        history = get_applied_migrations(conn)
        assert history == ["001_add_supabase_sub_to_users"]


# ---------------------------------------------------------------------------
# Test 1.4: Migration Failure and Recovery (Atomic Rollback)
# ---------------------------------------------------------------------------
def test_migration_failure_and_recovery(tmp_path, monkeypatch):
    """Ensure failing migrations roll back atomically and can recover upon fix."""
    db_file = tmp_path / "failure_recovery.db"
    engine = create_engine(f"sqlite:///{db_file}")

    init_db(engine)

    call_count = 0

    def faulty_upgrade(conn):
        nonlocal call_count
        call_count += 1
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, full_name, is_active, created_at, updated_at) "
                "VALUES ('u-fail-1', 'fail@test.mn', 'h', 'N', 1, '2026-01-01', '2026-01-01')"
            )
        )
        if call_count == 1:
            raise RuntimeError("Simulated migration step failure")

    def faulty_downgrade(conn):
        conn.execute(text("DELETE FROM users WHERE id='u-fail-1'"))

    test_migration = Migration(
        version="002_faulty_test_step",
        description="Faulty test migration",
        upgrade=faulty_upgrade,
        downgrade=faulty_downgrade,
    )

    # Monkeypatch MIGRATIONS to include the faulty migration
    monkeypatch.setattr("app.migrations.MIGRATIONS", MIGRATIONS + [test_migration])

    # First attempt: must fail and rollback
    with pytest.raises(RuntimeError, match="Simulated migration step failure"):
        run_migrations(engine)

    # Verify atomic rollback: version 002 was NOT recorded and user row was rolled back
    with engine.connect() as conn:
        history = get_applied_migrations(conn)
        assert "002_faulty_test_step" not in history
        user = conn.execute(text("SELECT id FROM users WHERE id='u-fail-1'")).fetchone()
        assert user is None

    # Second attempt (after resolving the issue): succeeds cleanly
    applied = run_migrations(engine)
    assert "002_faulty_test_step" in applied

    with engine.connect() as conn:
        history = get_applied_migrations(conn)
        assert "002_faulty_test_step" in history
        user = conn.execute(text("SELECT id FROM users WHERE id='u-fail-1'")).fetchone()
        assert user is not None


# ---------------------------------------------------------------------------
# Test 2: Concurrent PIN Initialization Race Condition
# ---------------------------------------------------------------------------
def test_concurrent_pin_init_race_condition(client: TestClient):
    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-conc-pin")]})

    now_ts = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode(
        {"sub": "user-conc-pin", "email": "conc_pin@familyscreen.mn", "aud": "authenticated", "exp": now_ts + 3600},
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-conc-pin"},
    )
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    fam_id = me.json()["family"]["id"]
    local_token = me.json()["access_token"]
    authed_headers = {"Authorization": f"Bearer {local_token}"}

    def _init_pin(pin_value: str):
        c = TestClient(app)
        res = c.post(
            f"/api/v1/families/{fam_id}/pin/init",
            headers=authed_headers,
            json={"new_pin": pin_value},
        )
        return res.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_init_pin, "1111")
        f2 = executor.submit(_init_pin, "2222")
        results = [f1.result(), f2.result()]

    # Exactly one request must succeed (200) and the other must be rejected (409 Conflict)
    assert 200 in results
    assert 409 in results

    # Verify family state has exactly one valid PIN configured
    db = client.TestingSession()
    family = db.get(Family, fam_id)
    assert family.pin_configured is True
    assert family.pin_hash is not None
    db.close()


# ---------------------------------------------------------------------------
# Test 3: Concurrent Account Linking Race Condition
# ---------------------------------------------------------------------------
def test_concurrent_supabase_account_link_race_condition(client: TestClient):
    # 1. Register target local account
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "target_account@familyscreen.mn",
            "password": "TargetPassword123!",
            "full_name": "Target User",
            "family_name": "Target Family",
            "pin_code": "4321",
        },
    )

    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-conc-link")]})
    now_ts = int(datetime.now(timezone.utc).timestamp())

    token_a = jwt.encode(
        {
            "sub": "sub-identity-A",
            "email": "target_account@familyscreen.mn",
            "email_confirmed_at": "2026-11-09T00:00:00Z",
            "aud": "authenticated",
            "exp": now_ts + 3600,
        },
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-conc-link"},
    )
    token_b = jwt.encode(
        {
            "sub": "sub-identity-B",
            "email": "target_account@familyscreen.mn",
            "email_confirmed_at": "2026-11-09T00:00:00Z",
            "aud": "authenticated",
            "exp": now_ts + 3600,
        },
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-conc-link"},
    )

    def _link_account(token: str):
        c = TestClient(app)
        res = c.post(
            "/api/v1/auth/supabase/link-account",
            headers={"Authorization": f"Bearer {token}"},
            json={"local_password": "TargetPassword123!"},
        )
        return res.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_a = executor.submit(_link_account, token_a)
        f_b = executor.submit(_link_account, token_b)
        results = [f_a.result(), f_b.result()]

    # Exactly one identity must link (200), and the competing identity must be rejected (409)
    assert 200 in results
    assert 409 in results

    # Verify in DB that only one sub is bound
    db = client.TestingSession()
    user = db.scalar(select(User).where(User.email == "target_account@familyscreen.mn"))
    assert user.supabase_sub in ["sub-identity-A", "sub-identity-B"]
    db.close()


# ---------------------------------------------------------------------------
# Test 4: Concurrent JIT Provisioning Race Condition
# ---------------------------------------------------------------------------
def test_concurrent_jit_provisioning_race_condition(client: TestClient):
    priv_key, pub_key = _generate_rsa_pair()
    sec.jwks_manager.set_test_jwks({"keys": [_rsa_to_jwk_dict(pub_key, "key-conc-jit")]})
    now_ts = int(datetime.now(timezone.utc).timestamp())

    token = jwt.encode(
        {
            "sub": "user-conc-jit-999",
            "email": "conc_jit@familyscreen.mn",
            "user_metadata": {"full_name": "JIT Parent"},
            "aud": "authenticated",
            "exp": now_ts + 3600,
        },
        priv_key,
        algorithm="RS256",
        headers={"kid": "key-conc-jit"},
    )

    def _call_me():
        c = TestClient(app)
        res = c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        return res.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(_call_me)
        f2 = executor.submit(_call_me)
        results = [f1.result(), f2.result()]

    # Both requests must complete successfully with 200 OK
    assert results == [200, 200], f"Got results: {results}"

    # Verify no duplicate user or family was created
    db = client.TestingSession()
    users = db.scalars(select(User).where(User.email == "conc_jit@familyscreen.mn")).all()
    assert len(users) == 1
    memberships = db.scalars(select(FamilyMember).where(FamilyMember.user_id == users[0].id)).all()
    assert len(memberships) == 1
    db.close()


def test_jit_provisioning_idempotency_and_takeover_prevention(client: TestClient):
    """Verify that when user exists with matching email and identical supabase_sub,
    _provision_supabase_family returns existing user without 409 conflict,
    while a mismatched sub with existing email raises 409 ACCOUNT_LINKING_REQUIRED."""
    from fastapi import HTTPException
    from app.main import _provision_supabase_family
    from app.security import AuthPrincipal

    db = client.TestingSession()
    # 1. Create a user who already has a supabase_sub
    u = User(
        id="sub-match-user-1",
        supabase_sub="sub-match-user-1",
        email="submatch@familyscreen.mn",
        password_hash="supabase_managed_auth",
        full_name="Matching Sub Parent",
    )
    db.add(u)
    f = Family(name="Matching Family", plan_tier="FREE")
    db.add(f)
    db.flush()
    m = FamilyMember(family_id=f.id, user_id=u.id, role="OWNER")
    db.add(m)
    db.commit()

    # 2. Case: legitimate call with matching sub -> succeeds without 409
    import time
    now_ts = int(time.time())
    principal_legit = AuthPrincipal(
        user_id="sub-match-user-1",
        family_id="",
        issued_at=now_ts,
        auth_provider="supabase",
        email="submatch@familyscreen.mn",
        full_name="Matching Sub Parent",
    )
    user_ret, fam_ret = _provision_supabase_family(db, principal_legit)
    assert user_ret.id == "sub-match-user-1"
    assert fam_ret.id == f.id

    # 3. Case: account takeover attempt (different sub trying to claim existing email) -> 409 CONFLICT
    principal_takeover = AuthPrincipal(
        user_id="different-attacker-sub",
        family_id="",
        issued_at=now_ts,
        auth_provider="supabase",
        email="submatch@familyscreen.mn",
        full_name="Attacker",
    )
    with pytest.raises(HTTPException) as exc_info:
        _provision_supabase_family(db, principal_takeover)
    assert exc_info.value.status_code == 409
    assert "ACCOUNT_LINKING_REQUIRED" in exc_info.value.detail
    db.close()


# ---------------------------------------------------------------------------
# Test 5: Role Policy: OWNER vs MEMBER PIN Update Authorization
# ---------------------------------------------------------------------------
def test_pin_update_owner_vs_member_authorization(client: TestClient):
    # 1. Register family (Owner)
    reg_res = client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner_pin@familyscreen.mn",
            "password": "Password123!",
            "full_name": "Owner Parent",
            "family_name": "Secure Family",
            "pin_code": "1234",
        },
    )
    fam_id = reg_res.json()["family"]["id"]
    owner_token = reg_res.json()["access_token"]

    # 2. Create second user in database with role "MEMBER" (Caregiver)
    db = client.TestingSession()
    member_user = User(
        id="user-member-caregiver",
        email="caregiver@familyscreen.mn",
        password_hash="somehash",
        full_name="Caregiver Member",
    )
    db.add(member_user)
    db.flush()
    member_rel = FamilyMember(
        family_id=fam_id,
        user_id=member_user.id,
        role="MEMBER",  # Not OWNER
    )
    db.add(member_rel)
    db.commit()
    db.close()

    member_token = sec.generate_access_token(member_user.id, fam_id)

    # 3. Member attempts PUT /pin -> 403 Forbidden
    member_res = client.put(
        f"/api/v1/families/{fam_id}/pin",
        headers={"Authorization": f"Bearer {member_token}"},
        json={"current_pin": "1234", "new_pin": "9999"},
    )
    assert member_res.status_code == 403
    assert "эзэмшигч" in member_res.json()["detail"] or "OWNER" in member_res.json()["detail"]

    # 4. Member attempts POST /pin/init on unconfigured -> 403 Forbidden
    member_init_res = client.post(
        f"/api/v1/families/{fam_id}/pin/init",
        headers={"Authorization": f"Bearer {member_token}"},
        json={"new_pin": "9999"},
    )
    assert member_init_res.status_code == 403

    # 5. Owner attempts PUT /pin -> 200 OK
    owner_res = client.put(
        f"/api/v1/families/{fam_id}/pin",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"current_pin": "1234", "new_pin": "5678"},
    )
    assert owner_res.status_code == 200
    assert "амжилттай" in owner_res.json()["message"]


# ---------------------------------------------------------------------------
# Test 6: Concurrent Database Initialization Race Condition (Advisory Locking)
# ---------------------------------------------------------------------------
def test_concurrent_database_initialization_race_condition(tmp_path):
    """Launch multiple concurrent threads executing init_db(engine) simultaneously.

    Asserts that all threads succeed without deadlocks, users table exists,
    schema_migrations contains version 001 exactly once, and zero errors occur.
    """
    db_file = tmp_path / "concurrent_init.db"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"timeout": 30.0},
        future=True,
    )

    def _init_worker():
        return init_db(test_engine)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_init_worker) for _ in range(4)]
        results = [f.result() for f in futures]

    # Verify that all threads completed without exceptions
    assert len(results) == 4

    with test_engine.connect() as conn:
        # Check that schema_migrations has version 001 exactly once
        applied = get_applied_migrations(conn)
        assert applied == ["001_add_supabase_sub_to_users"]

        # Check that core tables and columns exist
        tables = [r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()]
        assert "users" in tables
        assert "families" in tables
        assert "devices" in tables
        assert "schema_migrations" in tables

        cols = [c[1] for c in conn.execute(text("PRAGMA table_info(users)")).fetchall()]
        assert "supabase_sub" in cols


# ---------------------------------------------------------------------------
# Test 7: Existing Data Preservation Across Migrations
# ---------------------------------------------------------------------------
def test_existing_data_preservation_across_migrations(tmp_path):
    """Seed full legacy schema (users, families, members, devices, policies) without supabase_sub.

    Execute init_db(engine) and verify every record, foreign key, and policy
    attribute is 100% preserved without any data loss.
    """
    db_file = tmp_path / "preserve_data.db"
    test_engine = create_engine(f"sqlite:///{db_file}")

    with test_engine.begin() as conn:
        conn.execute(
            text(
                """
            CREATE TABLE users (
                id VARCHAR(36) PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                phone VARCHAR(32),
                password_hash VARCHAR(255) NOT NULL,
                full_name VARCHAR(120) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
            )
        )
        conn.execute(
            text(
                """
            CREATE TABLE families (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                pin_hash VARCHAR(255),
                pin_configured BOOLEAN NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
            )
        )
        conn.execute(
            text(
                """
            CREATE TABLE family_members (
                id VARCHAR(36) PRIMARY KEY,
                family_id VARCHAR(36) NOT NULL REFERENCES families(id),
                user_id VARCHAR(36) NOT NULL REFERENCES users(id),
                role VARCHAR(32) NOT NULL DEFAULT 'MEMBER',
                created_at TIMESTAMP NOT NULL
            )
            """
            )
        )
        conn.execute(
            text(
                """
            CREATE TABLE devices (
                id VARCHAR(36) PRIMARY KEY,
                device_name VARCHAR(120) NOT NULL,
                family_id VARCHAR(36) NOT NULL REFERENCES families(id),
                device_type VARCHAR(32) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
            )
        )
        conn.execute(
            text(
                """
            CREATE TABLE policies (
                id VARCHAR(36) PRIMARY KEY,
                device_id VARCHAR(36) NOT NULL REFERENCES devices(id),
                daily_limit_minutes INTEGER NOT NULL,
                bed_time VARCHAR(5) NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL
            )
            """
            )
        )
        conn.execute(
            text(
                """
            INSERT INTO users (id, email, password_hash, full_name, created_at, updated_at)
            VALUES ('u-pres-1', 'parent@familyscreen.mn', 'hash999', 'Preserve Parent', '2026-01-01', '2026-01-01')
            """
            )
        )
        conn.execute(
            text(
                """
            INSERT INTO families (id, name, pin_hash, pin_configured, created_at, updated_at)
            VALUES ('fam-pres-1', 'Preserve Family', 'hash_pin_123', 1, '2026-01-01', '2026-01-01')
            """
            )
        )
        conn.execute(
            text(
                """
            INSERT INTO family_members (id, family_id, user_id, role, created_at)
            VALUES ('mem-pres-1', 'fam-pres-1', 'u-pres-1', 'OWNER', '2026-01-01')
            """
            )
        )
        conn.execute(
            text(
                """
            INSERT INTO devices (id, device_name, family_id, device_type, created_at, updated_at)
            VALUES ('dev-pres-1', 'Living Room Android TV', 'fam-pres-1', 'ANDROID_TV', '2026-01-01', '2026-01-01')
            """
            )
        )
        conn.execute(
            text(
                """
            INSERT INTO policies (id, device_id, daily_limit_minutes, bed_time, created_at, updated_at)
            VALUES ('pol-pres-1', 'dev-pres-1', 120, '21:00', '2026-01-01', '2026-01-01')
            """
            )
        )

    # Apply database migrations on top of existing data
    applied = init_db(test_engine)
    assert "001_add_supabase_sub_to_users" in applied

    # Verify 100% data preservation
    with test_engine.connect() as conn:
        user_row = conn.execute(
            text("SELECT id, email, full_name, supabase_sub FROM users WHERE id='u-pres-1'")
        ).fetchone()
        assert user_row is not None
        assert user_row[0] == "u-pres-1"
        assert user_row[1] == "parent@familyscreen.mn"
        assert user_row[2] == "Preserve Parent"
        assert user_row[3] is None  # supabase_sub is NULL for legacy user

        fam_row = conn.execute(text("SELECT id, name, pin_configured FROM families WHERE id='fam-pres-1'")).fetchone()
        assert fam_row is not None
        assert fam_row[1] == "Preserve Family"
        assert fam_row[2] == 1

        mem_row = conn.execute(
            text("SELECT id, family_id, user_id, role FROM family_members WHERE id='mem-pres-1'")
        ).fetchone()
        assert mem_row is not None
        assert mem_row[3] == "OWNER"

        dev_row = conn.execute(
            text("SELECT id, device_name, family_id FROM devices WHERE id='dev-pres-1'")
        ).fetchone()
        assert dev_row is not None
        assert dev_row[1] == "Living Room Android TV"

        pol_row = conn.execute(
            text("SELECT id, device_id, daily_limit_minutes, bed_time FROM policies WHERE id='pol-pres-1'")
        ).fetchone()
        assert pol_row is not None
        assert pol_row[2] == 120
        assert pol_row[3] == "21:00"


# ---------------------------------------------------------------------------
# Test 8: Migration Lock Timeout Handling
# ---------------------------------------------------------------------------
def test_migration_lock_timeout_handling(tmp_path):
    """Verify that attempting to acquire a locked migration lock times out cleanly

    and raises MigrationLockTimeoutError instead of hanging indefinitely.
    """
    import threading

    db_file = tmp_path / "lock_timeout.db"
    test_engine = create_engine(f"sqlite:///{db_file}")

    holder_acquired = threading.Event()
    release_holder = threading.Event()

    def _lock_holder():
        with _sqlite_migration_lock:
            holder_acquired.set()
            release_holder.wait(timeout=5.0)

    holder_thread = threading.Thread(target=_lock_holder)
    holder_thread.start()
    assert holder_acquired.wait(timeout=3.0)

    try:
        with test_engine.connect() as conn:
            # Competing attempt should time out after 0.2s and raise MigrationLockTimeoutError
            with pytest.raises(MigrationLockTimeoutError, match="Timed out.*waiting for.*migration lock"):
                with migration_lock(conn, timeout_seconds=0.2):
                    pass
    finally:
        release_holder.set()
        holder_thread.join(timeout=3.0)

    # After holder finishes, acquiring lock should succeed cleanly
    with test_engine.connect() as conn:
        with migration_lock(conn, timeout_seconds=2.0):
            pass


# ---------------------------------------------------------------------------
# Test 9: PostgreSQL Advisory Lock and Concurrency (Container Integration)
# ---------------------------------------------------------------------------
def test_postgresql_advisory_lock_and_concurrent_migrations():
    """Verify PostgreSQL-specific session advisory locking (pg_try_advisory_lock).

    Only executes when TEST_POSTGRES_URL environment variable is provided
    (e.g., in GitHub Actions with a PostgreSQL service container).
    """
    pg_url = os.getenv("TEST_POSTGRES_URL")
    if not pg_url:
        pytest.skip("TEST_POSTGRES_URL environment variable not set. Skipping live PostgreSQL test.")

    if pg_url.startswith("postgres://"):
        pg_url = pg_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif pg_url.startswith("postgresql://"):
        pg_url = pg_url.replace("postgresql://", "postgresql+psycopg2://", 1)

    pg_engine = create_engine(pg_url, pool_pre_ping=True)

    # 1. Test low-level advisory lock mutual exclusion across separate connections
    with pg_engine.connect() as conn1:
        # Acquire lock on conn1
        locked1 = conn1.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
        ).scalar()
        assert locked1 is True

        try:
            # Attempt to acquire same lock on conn2 -> should return False immediately
            with pg_engine.connect() as conn2:
                locked2 = conn2.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
                ).scalar()
                assert locked2 is False

                # migration_lock with short timeout must raise MigrationLockTimeoutError
                with pytest.raises(MigrationLockTimeoutError):
                    with migration_lock(conn2, timeout_seconds=0.3):
                        pass
        finally:
            # Release lock on conn1
            unlocked = conn1.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
            ).scalar()
            assert unlocked is True

    # 2. Test concurrent multi-threaded init_db on live PostgreSQL
    def _pg_worker():
        return init_db(pg_engine)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_pg_worker) for _ in range(4)]
        results = [f.result() for f in futures]

    assert len(results) == 4
    with pg_engine.connect() as conn:
        applied = get_applied_migrations(conn)
        assert "001_add_supabase_sub_to_users" in applied

