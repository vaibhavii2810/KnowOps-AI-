"""
tests/test_edge_cases.py  –  Phase 11.4
The build guide's edge cases, offline: an empty knowledge base, malformed JSON bodies and an expired
JWT. Gemini is fake_gemini and Postgres is MemoryDB, which starts with every table empty.
"""

from datetime import timedelta

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.agent import tool_lookup_runbook
from app.auth import create_access_token
from app.config import settings
from app.main import app
from app.rag import retrieve

REFUSAL = "I don't have enough information in the knowledge base to answer that."


@pytest.fixture
def client():
    return TestClient(app)


# --- empty knowledge base ----------------------------------------------------------------------

def test_health_on_an_empty_knowledge_base_is_ok_with_zero_counts(client, memory_db):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["knowledge_base"] == {"documents": 0, "chunks": 0}


def test_ask_on_an_empty_knowledge_base_answers_without_sources(client, auth_headers, fake_gemini, memory_db):
    fake_gemini.reply(REFUSAL)

    response = client.post("/ask", json={"question": "How do I perform a database failover?"}, headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["sources"] == []
    assert response.json()["answer"] == REFUSAL
    prompt = fake_gemini.chat_calls[0]["contents"][-1].parts[0].text
    assert "No context available." in prompt  # the model is told there is nothing, not given an empty block
    conversation_id = response.json()["conversation_id"]
    assert [(m[2], m[3]) for m in memory_db.messages] == [
        ("user", "How do I perform a database failover?"), ("model", REFUSAL),
    ]
    assert all(m[1] == conversation_id for m in memory_db.messages)


def test_retrieve_on_an_empty_knowledge_base_returns_nothing(fake_gemini, memory_db):
    assert retrieve("How do I perform a database failover?", threshold=0.0) == []
    assert len(fake_gemini.embed_calls) == 1  # it still asked; there was just nothing to find


def test_the_agent_runbook_lookup_says_so_on_an_empty_knowledge_base(fake_gemini, memory_db):
    assert tool_lookup_runbook("database failover") == "No relevant runbook sections found with similarity >= 0.50."


# --- malformed JSON bodies -----------------------------------------------------------------------

JSON_ROUTES = [
    ("POST", "/auth/login"),
    ("POST", "/ask"),
    ("POST", "/tickets"),
    ("PATCH", "/tickets/1"),
    ("POST", "/agent/chat"),
]
MALFORMED_BODIES = {
    "truncated": b'{"question": "How do I',
    "array": b'["How do I perform a database failover?"]',
    "bare-string": b'"How do I perform a database failover?"',
    "number": b"42",
    "null": b"null",
    "trailing-garbage": b'{"question": "valid question"} extra',
}


@pytest.mark.parametrize("method,path", JSON_ROUTES, ids=[f"{m} {p}" for m, p in JSON_ROUTES])
@pytest.mark.parametrize("body", MALFORMED_BODIES.values(), ids=MALFORMED_BODIES.keys())
def test_malformed_json_is_a_422_before_any_work_is_done(client, auth_headers, fake_gemini, memory_db, method, path, body):
    headers = {**auth_headers, "Content-Type": "application/json"}

    response = client.request(method, path, content=body, headers=headers)

    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"][0] == "body"
    assert fake_gemini.embed_calls == [] and fake_gemini.chat_calls == []
    assert memory_db.tickets == {} and memory_db.conversations == {}


# --- expired JWT ---------------------------------------------------------------------------------

# Every protected route, with a body that would otherwise be valid, so a 401 can only be the token.
PROTECTED = [
    ("GET", "/auth/me", None),
    ("POST", "/conversations", None),
    ("GET", "/conversations", None),
    ("GET", "/conversations/{conversation_id}", None),
    ("POST", "/ask", {"question": "How do I perform a database failover?"}),
    ("POST", "/tickets", {"subject": "Valid subject", "description": "A valid description"}),
    ("GET", "/tickets", None),
    ("GET", "/tickets/stats", None),
    ("GET", "/tickets/{ticket_id}", None),
    ("PATCH", "/tickets/{ticket_id}", {"status": "resolved"}),
    ("POST", "/agent/chat", {"prompt": "Investigate pod crash"}),
    ("POST", "/agent/triage/{ticket_id}", None),
]
# Deliberately open: the SPA shell, health, login, and the cron job (its own CRON_SECRET check, D-022)
OPEN = {("GET", "/"), ("GET", "/health"), ("POST", "/auth/login"), ("GET", "/cron/reindex")}


def test_every_api_route_is_either_protected_here_or_deliberately_open():
    """A new route must be added to PROTECTED (and so tested below) or consciously listed in OPEN."""
    declared = {(method, route.path) for route in app.routes if isinstance(route, APIRoute)
                for method in route.methods if method != "HEAD"}
    declared -= {(m, p) for m, p in declared if p.startswith(("/docs", "/redoc", "/openapi"))}
    assert declared == {(m, p) for m, p, _ in PROTECTED} | OPEN


@pytest.mark.parametrize("method,path,body", PROTECTED, ids=[f"{m} {p}" for m, p, _ in PROTECTED])
def test_an_expired_token_is_rejected_on_every_protected_route(client, fake_gemini, memory_db, monkeypatch, method, path, body):
    monkeypatch.setattr(settings, "rate_limit_ask_per_minute", 10)   # limiter on: it must not count a rejected token
    monkeypatch.setattr(settings, "rate_limit_agent_per_minute", 5)
    token = create_access_token({"sub": settings.app_username, "role": "operator"}, expires_delta=timedelta(seconds=-1))
    url = path.format(conversation_id=1, ticket_id=1)

    response = client.request(method, url, json=body, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "Token has expired. Please log in again."
    assert response.headers["www-authenticate"] == "Bearer"
    assert fake_gemini.embed_calls == [] and fake_gemini.chat_calls == []
    assert memory_db.rate_limits == {} and memory_db.tickets == {} and memory_db.conversations == {}
