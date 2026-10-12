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


def test_conversation_lifecycle(client):
    """POST /conversations should create a thread, and GET should retrieve it."""
    # Create thread
    res_create = client.post("/conversations")
    assert res_create.status_code == 200
    conv_data = res_create.json()
    conv_id = conv_data["id"]
    assert isinstance(conv_id, int)

    # Retrieve conversation detail
    res_get = client.get(f"/conversations/{conv_id}")
    assert res_get.status_code == 200
    detail = res_get.json()
    assert detail["id"] == conv_id
    assert "messages" in detail

    # List conversations
    res_list = client.get("/conversations")
    assert res_list.status_code == 200
    convs = res_list.json()
    assert any(c["id"] == conv_id for c in convs)


def test_conversation_not_found(client):
    """GET /conversations/999999 should return 404."""
    response = client.get("/conversations/999999")
    assert response.status_code == 404
