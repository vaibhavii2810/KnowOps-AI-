"""
tests/test_auth_protection.py  –  Phase 5.4 / 5.5
Every route except GET /health and POST /auth/login must require a valid JWT:
401 with no token, 200 (or the route's normal success/validation code) with one.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


UNPROTECTED = [
    ("GET", "/health"),
]


PROTECTED_NO_BODY = [
    ("POST", "/conversations"),
    ("GET", "/conversations"),
    ("GET", "/conversations/1"),
    ("GET", "/tickets"),
    ("GET", "/tickets/stats"),
    ("GET", "/tickets/1"),
]


def test_unprotected_routes_need_no_token(client):
    """/health must stay reachable without a token."""
    for method, path in UNPROTECTED:
        response = client.request(method, path)
        assert response.status_code != 401, f"{method} {path} should not require auth"


def test_protected_routes_reject_missing_token(client):
    """Every protected GET/POST-without-body route returns 401 with no Authorization header."""
    for method, path in PROTECTED_NO_BODY:
        response = client.request(method, path)
        assert response.status_code == 401, f"{method} {path} should be 401 without a token"


def test_protected_routes_reject_bad_token(client):
    """A malformed/invalid bearer token is rejected the same as a missing one."""
    headers = {"Authorization": "Bearer not-a-real-jwt"}
    response = client.get("/tickets", headers=headers)
    assert response.status_code == 401


def test_ask_requires_auth(client):
    """POST /ask with no token should return 401 before any retrieval/generation runs."""
    response = client.post("/ask", json={"question": "How do I rollback a deployment?"})
    assert response.status_code == 401


def test_agent_routes_require_auth(client):
    """POST /agent/chat and /agent/triage/{id} should return 401 with no token."""
    assert client.post("/agent/chat", json={"prompt": "Investigate pod crash"}).status_code == 401
    assert client.post("/agent/triage/1").status_code == 401


def test_ask_succeeds_with_valid_token(client, auth_headers):
    """POST /ask with a valid token reaches the RAG pipeline and returns 200."""
    response = client.post(
        "/ask",
        json={"question": "How do I perform a database failover?", "top_k": 3},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert isinstance(data["sources"], list)
