"""Database connection and session management (PostgreSQL / SQLite)."""

from __future__ import annotations

import os
from typing import Any, Dict, Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv(
    "FAMILYSCREEN_DATABASE_URL",
    "sqlite:///./familyscreen.db",
)

# Convert legacy postgres:// and generic postgresql:// to modern postgresql+psycopg2:// for SQLAlchemy 2.0+ compatibility
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

engine_kwargs: Dict[str, Any] = {"future": True}

if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
elif DATABASE_URL.startswith("postgresql"):
    # Production-grade connection pooling for PostgreSQL (e.g. Supabase, Cloud SQL, Neon)
    engine_kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE", "10"))
    engine_kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW", "20"))
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = int(os.getenv("DB_POOL_RECYCLE", "1800"))
    engine_kwargs["pool_timeout"] = int(os.getenv("DB_POOL_TIMEOUT", "30"))

ENVIRONMENT = os.getenv("ENVIRONMENT", os.getenv("ENV", "development")).lower()
if ENVIRONMENT == "production" and DATABASE_URL.startswith("sqlite"):
    import logging
    logging.getLogger("familyscreen.database").warning(
        "CRITICAL ARCHITECTURAL WARNING: SQLite is being used with ENVIRONMENT=production. "
        "SQLite does not support horizontal scaling, multi-instance concurrency, or distributed advisory locks. "
        "A managed PostgreSQL database (e.g. Supabase, Cloud SQL, Neon) is required for production."
    )

engine = create_engine(DATABASE_URL, **engine_kwargs)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fks(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""


def get_db() -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
