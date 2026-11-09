"""Lightweight, transactional, and concurrency-safe database migration engine for FamilyScreen.

Supports both PostgreSQL and SQLite (>= 3.35.0) dialects.
Guarantees:
1. Cross-instance serialization via PostgreSQL session advisory lock (pg_try_advisory_lock).
2. In-process multi-threading safety via RLock and SQLite busy_timeout.
3. Fully atomic transactions: DDL and tracker updates commit or rollback together.
4. Idempotent execution and safe re-entrance.
5. Zero data loss for existing users, families, devices, and policies.
6. Support for both CLI execution and programmatic startup initialization.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import os
import sys
import threading
import time
from typing import Any, Callable, List, NamedTuple, Optional, Union

from sqlalchemy import (
    Column,
    Connection,
    DateTime,
    Engine,
    MetaData,
    String,
    Table,
    inspect,
    text,
)

logger = logging.getLogger("familyscreen.migrations")

# 64-bit integer advisory lock ID for FamilyScreen migrations:
# 0x46414D5343524E01 ("FAMSCRN\x01") -> 5062400588665038337
MIGRATION_ADVISORY_LOCK_ID: int = 5062400588665038337
_sqlite_migration_lock = threading.RLock()


class MigrationLockTimeoutError(RuntimeError):
    """Raised when acquiring the migration lock times out."""
    pass


class MigrationError(RuntimeError):
    """Raised when a schema migration fails and is rolled back."""
    pass


@contextmanager
def migration_lock(conn: Connection, timeout_seconds: float = 30.0):
    """Acquire a cross-instance advisory lock on PostgreSQL or an in-process lock on SQLite."""
    dialect_name = conn.dialect.name
    if dialect_name == "postgresql":
        start_time = time.monotonic()
        acquired = False
        while time.monotonic() - start_time < timeout_seconds:
            # pg_try_advisory_lock returns true if acquired, false otherwise
            res = conn.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
            ).scalar()
            if res:
                acquired = True
                break
            time.sleep(0.1)

        if not acquired:
            raise MigrationLockTimeoutError(
                f"Timed out after {timeout_seconds}s waiting for PostgreSQL migration advisory lock "
                f"({MIGRATION_ADVISORY_LOCK_ID}). Another backend instance may be applying migrations."
            )

        # Commit the autobegun transaction from pg_try_advisory_lock so caller can begin an explicit transaction
        if conn.in_transaction():
            conn.commit()

        try:
            logger.info("Acquired PostgreSQL migration advisory lock %s", MIGRATION_ADVISORY_LOCK_ID)
            yield
        finally:
            if acquired:
                try:
                    # Clean up any lingering uncommitted transaction before executing unlock
                    if conn.in_transaction():
                        conn.rollback()
                    conn.execute(
                        text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": MIGRATION_ADVISORY_LOCK_ID},
                    )
                    conn.commit()
                    logger.info("Released PostgreSQL migration advisory lock %s", MIGRATION_ADVISORY_LOCK_ID)
                except Exception as exc:
                    logger.warning("Failed to release PostgreSQL migration advisory lock: %s", exc)
    elif dialect_name == "sqlite":
        acquired = _sqlite_migration_lock.acquire(timeout=timeout_seconds)
        if not acquired:
            raise MigrationLockTimeoutError(
                f"Timed out after {timeout_seconds}s waiting for SQLite migration lock. "
                "Another thread is currently executing migrations."
            )
        try:
            try:
                conn.execute(text("PRAGMA busy_timeout = 30000"))
                if conn.in_transaction():
                    conn.commit()
            except Exception:
                pass
            yield
        finally:
            _sqlite_migration_lock.release()
    else:
        yield


class Migration(NamedTuple):
    version: str
    description: str
    upgrade: Callable[[Any], None]
    downgrade: Callable[[Any], None]


def _migration_001_upgrade(conn: Connection) -> None:
    """Add supabase_sub column and unique index to users table if not already present."""
    inspector = inspect(conn)
    if not inspector.has_table("users"):
        logger.info("Migration 001: users table does not exist yet; skipping ALTER TABLE.")
        return

    columns = [col["name"] for col in inspector.get_columns("users")]
    if "supabase_sub" not in columns:
        logger.info("Applying migration 001: Adding supabase_sub column to users table")
        conn.execute(text("ALTER TABLE users ADD COLUMN supabase_sub VARCHAR(64)"))

    indexes = [idx["name"] for idx in inspector.get_indexes("users")]
    if "ix_users_supabase_sub" not in indexes:
        logger.info("Applying migration 001: Creating unique index on users.supabase_sub")
        conn.execute(text("CREATE UNIQUE INDEX ix_users_supabase_sub ON users (supabase_sub)"))


def _migration_001_downgrade(conn: Connection) -> None:
    """Remove supabase_sub column and unique index from users table."""
    inspector = inspect(conn)
    if not inspector.has_table("users"):
        logger.info("Migration 001 rollback: users table does not exist; skipping.")
        return

    indexes = [idx["name"] for idx in inspector.get_indexes("users")]
    if "ix_users_supabase_sub" in indexes:
        conn.execute(text("DROP INDEX IF EXISTS ix_users_supabase_sub"))

    columns = [col["name"] for col in inspector.get_columns("users")]
    if "supabase_sub" in columns:
        conn.execute(text("ALTER TABLE users DROP COLUMN supabase_sub"))


MIGRATIONS: List[Migration] = [
    Migration(
        version="001_add_supabase_sub_to_users",
        description="Add supabase_sub column and unique index to users table for verified Supabase authentication",
        upgrade=_migration_001_upgrade,
        downgrade=_migration_001_downgrade,
    ),
]


def _ensure_schema_migrations_table(conn: Connection) -> None:
    """Create schema_migrations tracker table if it does not exist."""
    meta = MetaData()
    schema_migrations = Table(
        "schema_migrations",
        meta,
        Column("version", String(64), primary_key=True),
        Column("applied_at", DateTime(timezone=True), nullable=False),
    )
    schema_migrations.create(conn, checkfirst=True)


def get_applied_migrations(conn: Connection) -> List[str]:
    """Retrieve list of migration versions already applied to the database."""
    _ensure_schema_migrations_table(conn)
    result = conn.execute(text("SELECT version FROM schema_migrations ORDER BY version ASC"))
    return [row[0] for row in result.fetchall()]


def _run_migrations_on_connection(conn: Connection) -> List[str]:
    """Internal helper to apply migrations on an active locked connection."""
    applied: List[str] = []
    _ensure_schema_migrations_table(conn)
    existing = set(get_applied_migrations(conn))

    for mig in MIGRATIONS:
        if mig.version not in existing:
            logger.info("Running migration: %s - %s", mig.version, mig.description)
            try:
                mig.upgrade(conn)
            except Exception as exc:
                logger.error("Migration %s failed: %s", mig.version, exc, exc_info=True)
                raise MigrationError(f"Migration {mig.version} failed: {exc}") from exc

            now_utc = datetime.now(timezone.utc)
            conn.execute(
                text("INSERT INTO schema_migrations (version, applied_at) VALUES (:v, :t)"),
                {"v": mig.version, "t": now_utc},
            )
            applied.append(mig.version)

    return applied


def run_migrations(
    engine_or_conn: Union[Engine, Connection],
    timeout_seconds: float = 30.0,
) -> List[str]:
    """Execute all pending schema migrations inside an advisory lock and atomic transaction."""
    if isinstance(engine_or_conn, Engine):
        with engine_or_conn.connect() as conn:
            with migration_lock(conn, timeout_seconds=timeout_seconds):
                with conn.begin():
                    return _run_migrations_on_connection(conn)
    else:
        conn = engine_or_conn
        with migration_lock(conn, timeout_seconds=timeout_seconds):
            if conn.in_transaction():
                return _run_migrations_on_connection(conn)
            else:
                with conn.begin():
                    return _run_migrations_on_connection(conn)


def _rollback_migrations_on_connection(
    conn: Connection,
    target_version: Optional[str] = None,
) -> List[str]:
    """Internal helper to rollback migrations on an active locked connection."""
    rolled_back: List[str] = []
    _ensure_schema_migrations_table(conn)
    current_applied = get_applied_migrations(conn)

    for mig in reversed(MIGRATIONS):
        if mig.version in current_applied:
            if target_version and mig.version == target_version:
                break
            logger.info("Rolling back migration: %s", mig.version)
            try:
                mig.downgrade(conn)
            except Exception as exc:
                logger.error("Rollback of %s failed: %s", mig.version, exc, exc_info=True)
                raise MigrationError(f"Rollback of {mig.version} failed: {exc}") from exc

            conn.execute(
                text("DELETE FROM schema_migrations WHERE version = :v"),
                {"v": mig.version},
            )
            rolled_back.append(mig.version)

    return rolled_back


def rollback_migration(
    engine_or_conn: Union[Engine, Connection],
    target_version: Optional[str] = None,
    timeout_seconds: float = 30.0,
) -> List[str]:
    """Roll back migrations down to (and not including) target_version."""
    if isinstance(engine_or_conn, Engine):
        with engine_or_conn.connect() as conn:
            with migration_lock(conn, timeout_seconds=timeout_seconds):
                with conn.begin():
                    return _rollback_migrations_on_connection(conn, target_version)
    else:
        conn = engine_or_conn
        with migration_lock(conn, timeout_seconds=timeout_seconds):
            if conn.in_transaction():
                return _rollback_migrations_on_connection(conn, target_version)
            else:
                with conn.begin():
                    return _rollback_migrations_on_connection(conn, target_version)


def init_db(
    engine_or_conn: Union[Engine, Connection],
    timeout_seconds: float = 30.0,
) -> List[str]:
    """Ensure baseline schema exists, then run all pending migrations under lock.

    Safe for both fresh (empty) databases and existing production databases.
    Guarantees cross-instance concurrency safety via advisory locks and atomic transactions.
    """
    from .database import Base

    if isinstance(engine_or_conn, Engine):
        with engine_or_conn.connect() as conn:
            with migration_lock(conn, timeout_seconds=timeout_seconds):
                with conn.begin():
                    Base.metadata.create_all(bind=conn)
                    return _run_migrations_on_connection(conn)
    else:
        conn = engine_or_conn
        with migration_lock(conn, timeout_seconds=timeout_seconds):
            if conn.in_transaction():
                Base.metadata.create_all(bind=conn)
                return _run_migrations_on_connection(conn)
            else:
                with conn.begin():
                    Base.metadata.create_all(bind=conn)
                    return _run_migrations_on_connection(conn)


if __name__ == "__main__":
    from .database import engine

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="FamilyScreen Database Migration CLI")
    parser.add_argument("--rollback", action="store_true", help="Roll back the most recent migration")
    parser.add_argument("--target", type=str, default=None, help="Target version to roll back to")
    parser.add_argument("--status", action="store_true", help="Show applied migrations")
    args = parser.parse_args()

    if args.status:
        with engine.connect() as conn:
            applied = get_applied_migrations(conn)
            print(f"Applied migrations ({len(applied)}): {applied}")
    elif args.rollback:
        rolled = rollback_migration(engine, target_version=args.target)
        print(f"Rolled back migrations ({len(rolled)}): {rolled}")
    else:
        applied = init_db(engine)
        print(f"Database initialized and migrations applied ({len(applied)}): {applied}")
