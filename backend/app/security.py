"""Security utilities: password hashing, PIN hashing, rate-limiting, HMAC tokens, and Supabase JWT verification."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ENVIRONMENT = os.getenv("ENVIRONMENT", os.getenv("ENV", "development")).lower()
SECRET_KEY = os.getenv("FAMILYSCREEN_SECRET_KEY", "familyscreen-dev-secret-key-change-in-prod")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", None)

# Enforce strict secret key validation in production to prevent deployment with default credentials
if ENVIRONMENT == "production":
    if SECRET_KEY == "familyscreen-dev-secret-key-change-in-prod" or len(SECRET_KEY) < 32:
        raise RuntimeError(
            "CRITICAL SECURITY CONFIGURATION ERROR: FAMILYSCREEN_SECRET_KEY must be set to a "
            "cryptographically strong secret (minimum 32 characters) in production environment!"
        )

PBKDF2_ITERATIONS = 120_000
MAX_PIN_ATTEMPTS = 5
PIN_LOCKOUT_MINUTES = 15
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days
DEVICE_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 365  # 1 year for paired TV hardware

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthPrincipal:
    """Authenticated parent user and their authorized family ID."""

    user_id: str
    family_id: str
    issued_at: int
    auth_provider: str = "local"


@dataclass(frozen=True)
class DevicePrincipal:
    """Authenticated TV / FamilyScreen Box hardware principal."""

    device_id: str
    family_id: str
    issued_at: int


def hash_secret(secret_value: str) -> str:
    """Hash a password or PIN using PBKDF2-HMAC-SHA256 with a random salt."""
    salt = secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        secret_value.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${derived}"


def verify_secret(plain_value: str, stored_hash: str | None) -> bool:
    """Verify a password or PIN against its stored PBKDF2 hash in constant time."""
    if not stored_hash:
        return False
    try:
        algorithm, iter_str, salt, expected_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
    except ValueError:
        return False

    candidate_hex = hashlib.pbkdf2_hmac(
        "sha256",
        plain_value.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(candidate_hex, expected_hex)


def sha256_hex(plain_value: str) -> str:
    """Compute a fast SHA-256 hex digest for high-entropy device tokens."""
    return hashlib.sha256(plain_value.encode("utf-8")).hexdigest()


def generate_access_token(user_id: str, family_id: str) -> str:
    """Generate a signed HMAC token for parent authentication."""
    issued_at = int(datetime.now(timezone.utc).timestamp())
    nonce = secrets.token_hex(8)
    payload = f"{user_id}:{family_id}:{issued_at}:{nonce}"
    sig = hmac.new(SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def generate_device_token(device_id: str, family_id: str) -> str:
    """Generate a signed HMAC token for a paired Android TV / FamilyScreen Box."""
    issued_at = int(datetime.now(timezone.utc).timestamp())
    nonce = secrets.token_hex(12)
    payload = f"dev:{device_id}:{family_id}:{issued_at}:{nonce}"
    sig = hmac.new(SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_device_token(token: str) -> DevicePrincipal:
    """Verify HMAC signature and structure of a device token."""
    if not token or "." not in token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Төхөөрөмжийн токен буруу эсвэл байхгүй байна.",
        )
    payload, provided_sig = token.rsplit(".", 1)
    expected_sig = hmac.new(
        SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Төхөөрөмжийн токен хүчингүй байна.",
        )

    parts = payload.split(":")
    if len(parts) != 5 or parts[0] != "dev":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Төхөөрөмжийн токены бүтэц буруу байна.",
        )

    _prefix, device_id, family_id, issued_at_str, _nonce = parts
    try:
        issued_at = int(issued_at_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Төхөөрөмжийн токены хугацаа буруу байна.",
        ) from exc

    now_ts = int(datetime.now(timezone.utc).timestamp())
    if now_ts - issued_at > DEVICE_TOKEN_TTL_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Төхөөрөмжийн токены хугацаа дууссан байна.",
        )

    return DevicePrincipal(device_id=device_id, family_id=family_id, issued_at=issued_at)


def verify_supabase_jwt(token: str) -> AuthPrincipal:
    """Validate Supabase Auth RS256/HS256 JWT token."""
    secret = SUPABASE_JWT_SECRET or SECRET_KEY
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256", "RS256"],
            options={"verify_aud": False},
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Supabase JWT токены sub талбар олдсонгүй.",
            )
        family_id = payload.get("family_id") or payload.get("app_metadata", {}).get("family_id") or f"fam-{user_id}"
        issued_at = payload.get("iat", int(datetime.now(timezone.utc).timestamp()))
        return AuthPrincipal(
            user_id=str(user_id),
            family_id=str(family_id),
            issued_at=int(issued_at),
            auth_provider="supabase",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Supabase JWT токен хүчингүй байна: {str(exc)}",
        ) from exc


def verify_access_token(token: str) -> AuthPrincipal:
    """Verify access token supporting both standard HMAC tokens and Supabase JWTs."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нэвтрэх эрхийн токен буруу эсвэл байхгүй байна.",
        )

    # 1. Supabase JWT standard format (header.payload.signature)
    if token.count(".") == 2:
        return verify_supabase_jwt(token)

    # 2. FamilyScreen High-Performance HMAC Token
    if "." not in token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нэвтрэх эрхийн токен буруу эсвэл байхгүй байна.",
        )

    payload, provided_sig = token.rsplit(".", 1)
    expected_sig = hmac.new(
        SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нэвтрэх эрхийн токен хүчингүй байна.",
        )

    parts = payload.split(":")
    if len(parts) != 4:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токены бүтэц буруу байна.",
        )

    user_id, family_id, issued_at_str, _nonce = parts
    try:
        issued_at = int(issued_at_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токены хугацааны мэдээлэл буруу байна.",
        ) from exc

    now_ts = int(datetime.now(timezone.utc).timestamp())
    if now_ts - issued_at > TOKEN_TTL_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нэвтрэх хугацаа дууссан байна. Дахин нэвтэрнэ үү.",
        )

    return AuthPrincipal(user_id=user_id, family_id=family_id, issued_at=issued_at, auth_provider="local")


def get_current_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> AuthPrincipal:
    """FastAPI dependency requiring a valid Bearer access token."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Энэ үйлдлийг хийхийн тулд эцэг эхийн бүртгэлээр нэвтэрсэн байх шаардлагатай.",
        )
    return verify_access_token(credentials.credentials)


def get_optional_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[AuthPrincipal]:
    """FastAPI dependency returning AuthPrincipal if Bearer parent token is present, else None."""
    if credentials is None or not credentials.credentials:
        return None
    if credentials.credentials.startswith("dev:"):
        return None
    return verify_access_token(credentials.credentials)


def get_optional_device_principal(
    x_device_token: Optional[str] = Header(default=None, alias="X-Device-Token"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[DevicePrincipal]:
    """Extract and verify DevicePrincipal from X-Device-Token or Bearer dev:... token."""
    raw_token: Optional[str] = x_device_token
    if not raw_token and credentials and credentials.credentials.startswith("dev:"):
        raw_token = credentials.credentials
    if not raw_token:
        return None
    return verify_device_token(raw_token)


def ensure_family_access(principal: AuthPrincipal, target_family_id: str) -> None:
    """Raise 403 Forbidden if the authenticated parent belongs to a different family."""
    if principal.family_id != target_family_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Танд өөр гэр бүлийн мэдээлэлд хандах эрх байхгүй байна.",
        )


def ensure_device_access(
    device_principal: DevicePrincipal,
    expected_device_id: str,
    expected_family_id: Optional[str] = None,
) -> None:
    """Raise 403 Forbidden if the device token belongs to another device or family."""
    if device_principal.device_id != expected_device_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Өөр төхөөрөмжийн мэдээлэлд хандах эрхгүй байна.",
        )
    if expected_family_id and device_principal.family_id != expected_family_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Төхөөрөмж өөр гэр бүлд бүртгэлтэй байна.",
        )


def generate_pairing_code() -> str:
    """Generate a 6-digit numeric pairing code (e.g., '482910')."""
    return f"{secrets.randbelow(900_000) + 100_000}"


def is_pin_locked(pin_locked_until: datetime | None, now_utc: datetime | None = None) -> bool:
    """Return True if the family PIN is currently locked due to failed attempts."""
    if pin_locked_until is None:
        return False
    now = now_utc or datetime.now(timezone.utc)
    if pin_locked_until.tzinfo is None:
        pin_locked_until = pin_locked_until.replace(tzinfo=timezone.utc)
    return now < pin_locked_until


def compute_lockout_expiry(now_utc: datetime | None = None) -> datetime:
    """Compute the UTC timestamp until which PIN verification is locked."""
    now = now_utc or datetime.now(timezone.utc)
    return now + timedelta(minutes=PIN_LOCKOUT_MINUTES)
