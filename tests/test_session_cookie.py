"""
tests/test_session_cookie.py  –  D-082
The console's session is an HttpOnly cookie (no token in JavaScript); Bearer headers still work for scripts.
"""

from fastapi.testclient import TestClient

from app.auth import SESSION_COOKIE
from app.config import settings
from app.main import app


def _login(client):
    return client.post("/auth/login", json={"username": settings.app_username, "password": settings.app_password})


def test_login_sets_an_httponly_strict_cookie():
    res = _login(TestClient(app))
    assert res.status_code == 200
    cookie = res.headers["set-cookie"].lower()
    assert f"{SESSION_COOKIE}=" in cookie and "httponly" in cookie and "samesite=strict" in cookie


def test_cookie_alone_authenticates():
    client = TestClient(app)  # keeps cookies between calls, like a browser
    _login(client)
    assert client.get("/auth/me").status_code == 200


def test_bearer_header_still_works_and_wins_over_a_bad_cookie():
    token = _login(TestClient(app)).json()["access_token"]
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, "garbage")
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_bad_cookie_is_rejected():
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, "garbage")
    assert client.get("/auth/me").status_code == 401


def test_logout_clears_the_session():
    client = TestClient(app)
    _login(client)
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/auth/me").status_code == 401


def test_cookie_is_secure_on_vercel(monkeypatch):
    monkeypatch.setattr(settings, "vercel", "1")
    assert "secure" in _login(TestClient(app)).headers["set-cookie"].lower()
