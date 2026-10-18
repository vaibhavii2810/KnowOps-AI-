"""
tests/test_api_v2_5.py  –  Phase 2.5
Tests for Frontend SPA dashboard, conversation endpoints, and multi-turn memory.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_serve_frontend_dashboard(client):
    """GET / should serve the KnowOps AI HTML5 Operations Console."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "KnowOps" in response.text
    assert "app.css" in response.text


def test_conversation_lifecycle(client, auth_headers):
    """POST /conversations should create a thread, and GET should retrieve it (requires a valid JWT)."""
    # Create thread
    res_create = client.post("/conversations", headers=auth_headers)
    assert res_create.status_code == 200
    conv_data = res_create.json()
    conv_id = conv_data["id"]
    assert isinstance(conv_id, int)

    # Retrieve conversation detail
    res_get = client.get(f"/conversations/{conv_id}", headers=auth_headers)
    assert res_get.status_code == 200
    detail = res_get.json()
    assert detail["id"] == conv_id
    assert "messages" in detail

    # List conversations
    res_list = client.get("/conversations", headers=auth_headers)
    assert res_list.status_code == 200
    convs = res_list.json()
    assert any(c["id"] == conv_id for c in convs)


def test_conversation_not_found(client, auth_headers):
    """GET /conversations/999999 should return 404 for an authenticated caller."""
    response = client.get("/conversations/999999", headers=auth_headers)
    assert response.status_code == 404


def test_conversations_require_auth(client):
    """Conversation routes with no token should return 401 (Phase 5.4)."""
    assert client.post("/conversations").status_code == 401
    assert client.get("/conversations").status_code == 401
    assert client.get("/conversations/1").status_code == 401
