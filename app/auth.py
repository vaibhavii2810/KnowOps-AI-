"""
app/auth.py  –  Phase 2.5
JWT authentication, token generation, password verification, and security dependencies.

This module provides:
  - JWT token generation and verification using PyJWT
  - Configurable expiration (default 60 minutes)
  - Password hashing and constant-time comparison
  - FastAPI dependency providers:
      * get_current_user_optional: allows unauthenticated or authenticated access
      * get_current_user_required: strictly enforces authentication with HTTP 401
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

# HTTP Bearer scheme for Swagger UI and header extraction
security_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: Optional[str] = None) -> str:
    """
    Hash a password using SHA-256 with a salt.
    Format: salt$hex_digest
    """
    if salt is None:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=100_000,
    )
    return f"{salt}${key.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a salt$hash string."""
    try:
        salt, expected_hash = hashed_password.split("$", 1)
        actual_hash = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations=100_000,
        ).hex()
        return secrets.compare_digest(actual_hash, expected_hash)
    except (ValueError, AttributeError):
        return False


def verify_operator_credentials(username: str, password: str) -> bool:
    """
    Verify operator credentials against configured administrative settings.
    Uses constant-time comparison to prevent timing attacks.
    """
    # Compare as UTF-8 bytes: secrets.compare_digest raises TypeError on non-ASCII str, which
    # turned any login attempt containing e.g. "é" or an emoji into an HTTP 500 (Phase 10.2, D-033).
    valid_user = secrets.compare_digest(username.encode("utf-8"), settings.app_username.encode("utf-8"))
    valid_pass = secrets.compare_digest(password.encode("utf-8"), settings.app_password.encode("utf-8"))
    return valid_user and valid_pass


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a signed JWT access token containing arbitrary payload data.

    Args:
        data: Payload claims (e.g. {"sub": "admin", "role": "sre"})
        expires_delta: Token lifetime. Defaults to settings.jwt_expire_minutes.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.jwt_expire_minutes)

    to_encode.update({
        "exp": expire,
        "iat": now,
        "iss": "knowops-ai",
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """
    Decode and validate a JWT access token.

    Raises:
        HTTPException(401) if expired or malformed.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer="knowops-ai",
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user_optional(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
) -> Optional[dict]:
    """
    FastAPI dependency that extracts and verifies JWT if present.
    Returns None if no token is provided.
    """
    if not auth or not auth.credentials:
        return None
    return decode_access_token(auth.credentials)


def get_current_user_required(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer),
) -> dict:
    """
    FastAPI dependency that strictly requires a valid JWT.
    Raises HTTP 401 if missing or invalid.
    """
    if not auth or not auth.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_access_token(auth.credentials)
