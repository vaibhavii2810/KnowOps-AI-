"""
tests/test_auth.py  –  Phase 2.5
Tests for JWT generation, verification, password hashing, and authentication endpoints.
"""

from datetime import timedelta
import pytest
from fastapi.testclient import TestClient

from app.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_operator_credentials,
    verify_password,
)
from app.config import settings
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_password_hashing():
    """Passwords should hash uniquely with salt and verify accurately."""
    pwd = "secret-super-password"
    hashed = hash_password(pwd)
    assert "$" in hashed
    assert verify_password(pwd, hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_operator_credentials_verification():
    """Configured admin credentials should pass verification; invalid credentials must fail."""
    assert verify_operator_credentials(settings.app_username, settings.app_password) is True
    assert verify_operator_credentials("admin", "wrong-pass") is False
    assert verify_operator_credentials("intruder", "admin") is False


def test_jwt_token_creation_and_decoding():
    """create_access_token should produce a valid signed token decodable with claims."""
    token = create_access_token({"sub": "admin_sre", "role": "operator"})
    payload = decode_access_token(token)
    assert payload["sub"] == "admin_sre"
    assert payload["role"] == "operator"
    assert payload["iss"] == "knowops-ai"
    assert "exp" in payload


def test_expired_jwt_token_raises_401():
    """An expired JWT must raise an HTTP 401 Unauthorized exception."""
    token = create_access_token(
        {"sub": "admin"},
        expires_delta=timedelta(seconds=-10),  # expired 10 seconds ago
    )
    with pytest.raises(Exception) as excinfo:
        decode_access_token(token)
    assert "401" in str(excinfo.value) or "expired" in str(excinfo.value).lower()


def test_login_endpoint_success(client):
    """POST /auth/login with valid credentials returns 200 and access_token."""
    response = client.post(
        "/auth/login",
        json={"username": settings.app_username, "password": settings.app_password},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["username"] == settings.app_username


def test_login_endpoint_invalid_credentials(client):
    """POST /auth/login with invalid credentials returns 401."""
    response = client.post(
        "/auth/login",
        json={"username": "wrong_user", "password": "wrong_password"},
    )
    assert response.status_code == 401


def test_auth_me_endpoint_protected(client):
    """GET /auth/me returns 401 without token, and 200 with valid Bearer token."""
    # Unauthenticated
    unauth = client.get("/auth/me")
    assert unauth.status_code == 401

    # Authenticated
    token = create_access_token({"sub": settings.app_username, "role": "operator"})
    auth_res = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert auth_res.status_code == 200
    data = auth_res.json()
    assert data["username"] == settings.app_username
    assert data["authenticated"] is True
