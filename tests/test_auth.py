"""
tests/test_auth.py  –  Phase 2.5
Tests for JWT generation, verification, password hashing, and authentication endpoints.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException
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

# Every test here is offline; the guard proves it (Phase 11.2).
pytestmark = pytest.mark.usefixtures("no_network")


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
    with pytest.raises(HTTPException) as excinfo:
        decode_access_token(token)
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail == "Token has expired. Please log in again."
    assert excinfo.value.headers == {"WWW-Authenticate": "Bearer"}


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


# --- Phase 11.2: invalid tokens --------------------------------------------------------------

def _claims(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    claims = {"sub": "admin", "iat": now, "exp": now + timedelta(minutes=5), "iss": "knowops-ai"}
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def _assert_rejected_as_invalid(token: str) -> None:
    with pytest.raises(HTTPException) as excinfo:
        decode_access_token(token)
    assert excinfo.value.status_code == 401
    assert excinfo.value.detail.startswith("Invalid token:")


def test_a_valid_token_round_trips_with_its_expiry_in_the_future():
    payload = decode_access_token(create_access_token({"sub": "admin"}))
    assert payload["exp"] > datetime.now(timezone.utc).timestamp()
    assert payload["iat"] <= payload["exp"]


def test_tampered_payload_is_rejected():
    header, body, signature = create_access_token({"sub": "admin", "role": "operator"}).split(".")
    forged_body = jwt.utils.base64url_encode(b'{"sub":"root","role":"operator","iss":"knowops-ai","exp":9999999999}')
    _assert_rejected_as_invalid(f"{header}.{forged_body.decode()}.{signature}")


def test_token_signed_with_another_secret_is_rejected():
    _assert_rejected_as_invalid(jwt.encode(_claims(), "not-the-real-secret", algorithm=settings.jwt_algorithm))


def test_unsigned_alg_none_token_is_rejected():
    _assert_rejected_as_invalid(jwt.encode(_claims(), None, algorithm="none"))


def test_token_using_a_different_algorithm_is_rejected():
    """Same secret, but HS512: only the configured algorithm is accepted."""
    _assert_rejected_as_invalid(jwt.encode(_claims(), settings.jwt_secret, algorithm="HS512"))


@pytest.mark.parametrize("issuer", ["someone-else", None])
def test_wrong_or_missing_issuer_is_rejected(issuer):
    _assert_rejected_as_invalid(jwt.encode(_claims(iss=issuer), settings.jwt_secret, algorithm=settings.jwt_algorithm))


@pytest.mark.parametrize("token,leaked_phrase", [
    (jwt.encode({"sub": "admin", "iss": "knowops-ai", "exp": 9999999999}, "", algorithm="none"), "alg"),
    ("not-a-jwt-at-all", "segments"),
    (jwt.encode(_claims(), "wrong-secret", algorithm="HS256"), "signature"),
    (jwt.encode(_claims(iss="someone-else"), settings.jwt_secret, algorithm=settings.jwt_algorithm), "issuer"),
])
def test_the_401_does_not_leak_which_specific_check_failed(token, leaked_phrase):
    """Bug #14 (external bug report, Low, D-067): the 401 used to echo PyJWT's own exception text verbatim
    (e.g. "The specified alg value is not allowed"), telling an attacker exactly which validation rule
    rejected their forged token instead of a flat, uninformative rejection."""
    with pytest.raises(HTTPException) as excinfo:
        decode_access_token(token)
    assert leaked_phrase.lower() not in excinfo.value.detail.lower()
    assert excinfo.value.detail == "Invalid token: authentication failed."


@pytest.mark.parametrize("garbage", ["", "not-a-jwt", "a.b.c", "Bearer abc"])
def test_garbage_tokens_are_rejected(garbage):
    _assert_rejected_as_invalid(garbage)


@pytest.mark.parametrize("headers", [
    {},                                                    # no header
    {"Authorization": "Bearer"},                           # scheme, no token
    {"Authorization": "Basic YWRtaW46YWRtaW4="},           # wrong scheme
    {"Authorization": "Bearer not-a-jwt"},                 # malformed
], ids=["missing", "empty-bearer", "basic-scheme", "malformed"])
def test_protected_route_rejects_bad_authorization_headers(client, headers):
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


def test_protected_route_rejects_an_expired_token(client):
    token = create_access_token({"sub": "admin"}, expires_delta=timedelta(seconds=-1))
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Token has expired. Please log in again."
