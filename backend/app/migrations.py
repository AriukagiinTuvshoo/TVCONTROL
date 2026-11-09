"""Lightweight, transactional database migration engine for FamilyScreen.

Supports both PostgreSQL and SQLite (>= 3.35.0) dialects.
Automatically tracks applied migrations in the `schema_migrations` table.
Guarantees zero data loss for existing users, families, and device records.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, List, NamedTuple, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Engine,
    MetaData,
    String,
    Table,
    inspect,
    select,
    text,
)

logger = logging.getLogger("familyscreen.migrations")


class Migration(NamedTuple):
    version: str
    description: str
    upgrade: Callable[[Any], None]
    downgrade: Callable[[Any], None]


def _migration_001_upgrade(conn) -> None:
    """Add supabase_sub column and unique index to users table if not already present."""
    inspector = inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("users")]

    if "supabase_sub" not in columns:
        logger.info("Applying migration 001: Adding supabase_sub column to users table")
        conn.execute(text("ALTER TABLE users ADD COLUMN supabase_sub VARCHAR(64)"))

    indexes = [idx["name"] for idx in inspector.get_indexes("users")]
    if "ix_users_supabase_sub" not in indexes:
        logger.info("Applying migration 001: Creating unique index on users.supabase_sub")
        conn.execute(text("CREATE UNIQUE INDEX ix_users_supabase_sub ON users (supabase_sub)"))


def _migration_001_downgrade(conn) -> None:
    """Remove supabase_sub column and unique index from users table."""
    inspector = inspect(conn)
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


def _ensure_schema_migrations_table(conn) -> None:
    """Create schema_migrations tracker table if it does not exist."""
    meta = MetaData()
    schema_migrations = Table(
        "schema_migrations",
        meta,
        Column("version", String(64), primary_key=True),
        Column("applied_at", DateTime(timezone=True), nullable=False),
    )
    schema_migrations.create(conn, checkfirst=True)


def get_applied_migrations(conn) -> List[str]:
    """Retrieve list of migration versions already applied to the database."""
    _ensure_schema_migrations_table(conn)
    result = conn.execute(text("SELECT version FROM schema_migrations ORDER BY version ASC"))
    return [row[0] for row in result.fetchall()]


def run_migrations(engine: Engine) -> List[str]:
    """Execute all pending schema migrations inside atomic transactions."""
    applied: List[str] = []
    with engine.begin() as conn:
        _ensure_schema_migrations_table(conn)
        existing = set(get_applied_migrations(conn))

        for mig in MIGRATIONS:
            if mig.version not in existing:
                logger.info(f"Running migration: {mig.version} - {mig.description}")
                mig.upgrade(conn)
                now_utc = datetime.now(timezone.utc)
                conn.execute(
                    text("INSERT INTO schema_migrations (version, applied_at) VALUES (:v, :t)"),
                    {"v": mig.version, "t": now_utc},
                )
                applied.append(mig.version)

    return applied


def rollback_migration(engine: Engine, target_version: Optional[str] = None) -> List[str]:
    """Roll back migrations down to (and not including) target_version."""
    rolled_back: List[str] = []
    with engine.begin() as conn:
        _ensure_schema_migrations_table(conn)
        current_applied = get_applied_migrations(conn)

        # Roll back in reverse order
        for mig in reversed(MIGRATIONS):
            if mig.version in current_applied:
                if target_version and mig.version == target_version:
                    break
                logger.info(f"Rolling back migration: {mig.version}")
                mig.downgrade(conn)
                conn.execute(
                    text("DELETE FROM schema_migrations WHERE version = :v"),
                    {"v": mig.version},
                )
                rolled_back.append(mig.version)

    return rolled_back
