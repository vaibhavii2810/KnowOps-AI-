"""
tests/test_ask_integration.py  –  Phase 11.3
A full POST /ask round trip with the LLM mocked: the real route, JWT check, rate limiter, conversation
handling, retrieve(), citation formatting, prompt building and message persistence all run; only
Gemini (fake_gemini) and Postgres (fake_db) are fakes. Offline — both fixtures pull in no_network.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import ratelimit
from app.config import settings
from app.llm import SYSTEM_INSTRUCTION
from app.main import app

QUESTION = "How do I perform a database failover?"
ANSWER = "Promote the replica, then repoint db.internal (Disaster Recovery Runbook › 4.2 Failover)."
CHUNK_ROWS = [  # what the vector search returns, already ranked
    (11, "Disaster Recovery Runbook", "data/docs/disaster_recovery.md", "4.2 Failover",
     "Promote db-replica-01 with pg_ctl promote.", 0.83),
    (12, "Disaster Recovery Runbook", "data/docs/disaster_recovery.md", "4.3 Verification",
     "Confirm replication lag is zero.", 0.71),
]


_STATEMENT_KINDS = (
    ("CREATE TABLE IF NOT EXISTS rate_limits", "create rate_limits table"),  # once per limiter connection
    ("INSERT INTO rate_limits", "rate-limit hit"),
    ("INSERT INTO conversations", "new conversation"),
    ("FROM chunks c", "vector search"),
    ("INSERT INTO messages", "save turn"),
)


def _kind(sql: str) -> str:
    sql = " ".join(sql.split())  # the SQL is indented and aligned; compare it the way fake_db does
    return next((label for fragment, label in _STATEMENT_KINDS if fragment in sql), f"unexpected: {sql[:40]}")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def backend(fake_gemini, fake_db, monkeypatch):
    """The database and model state for a first question; the rate limiter is switched on."""
    monkeypatch.setattr(settings, "rate_limit_ask_per_minute", 10)
    # The limiter deletes old counter rows on a random 1% of writes; that extra DELETE once made this test's statement
    # list fail about one run in a hundred. Pin the dice so the list is always the same.
    monkeypatch.setattr(ratelimit, "random", SimpleNamespace(random=lambda: 1.0))
    fake_db.on("INSERT INTO rate_limits", [(1,)])
    fake_db.on("INSERT INTO conversations", [(101,)])
    fake_db.on("FROM chunks c", CHUNK_ROWS)
    fake_gemini.reply(ANSWER)
    return fake_gemini, fake_db


def test_ask_round_trip_with_the_llm_mocked(client, auth_headers, backend):
    fake_gemini, fake_db = backend

    response = client.post("/ask", json={"question": QUESTION, "top_k": 2}, headers=auth_headers)

    # The response: the model's answer, the retrieved chunks as ranked citations, a new conversation
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == ANSWER
    assert body["question"] == QUESTION
    assert body["conversation_id"] == 101
    assert [(s["chunk_id"], s["heading"], s["similarity"]) for s in body["sources"]] == [
        (11, "4.2 Failover", 0.83), (12, "4.3 Verification", 0.71),
    ]
    assert response.headers["X-RateLimit-Remaining"] == "9"

    # Gemini: the question embedded once as a query, then one grounded chat call
    assert [c["contents"] for c in fake_gemini.embed_calls] == [QUESTION]
    assert fake_gemini.embed_calls[0]["config"].task_type == "RETRIEVAL_QUERY"
    assert len(fake_gemini.chat_calls) == 1
    chat = fake_gemini.chat_calls[0]
    assert chat["config"].system_instruction == SYSTEM_INSTRUCTION
    assert len(chat["contents"]) == 1  # no history on a first question
    prompt = chat["contents"][0].parts[0].text
    assert "Source: Disaster Recovery Runbook › 4.2 Failover" in prompt  # citations reach the model
    assert "Promote db-replica-01 with pg_ctl promote." in prompt
    assert prompt.count("<untrusted_data") == 2  # each chunk fenced as data (D-034)
    assert prompt.rstrip().endswith(QUESTION)

    # Postgres, in order: rate-limit hit, new conversation, vector search (top_k reached the SQL), saved turn
    assert [_kind(sql) for sql, _ in fake_db.executed] == [
        "create rate_limits table", "rate-limit hit", "new conversation", "vector search", "save turn",
    ]
    assert fake_db.queries("FROM chunks c")[0][1][4] == 2
    assert fake_db.queries("INSERT INTO messages")[0][1] == (101, QUESTION, 101, ANSWER)


def test_ask_follow_up_sends_the_conversation_history_to_the_model(client, auth_headers, backend):
    fake_gemini, fake_db = backend
    fake_db.on("SELECT id FROM conversations", [(101,)])
    fake_db.on("FROM messages", [("user", "What is RTO?"), ("model", "Recovery time objective: 15 minutes.")])

    response = client.post(
        "/ask", json={"question": QUESTION, "conversation_id": 101}, headers=auth_headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["conversation_id"] == 101
    assert not fake_db.queries("INSERT INTO conversations")  # existing conversation reused
    assert fake_db.queries("FROM messages")[0][1] == (101,)

    turns = fake_gemini.chat_calls[0]["contents"]
    assert [(t.role, t.parts[0].text) for t in turns[:2]] == [
        ("user", "What is RTO?"), ("model", "Recovery time objective: 15 minutes."),
    ]
    assert turns[2].role == "user" and turns[2].parts[0].text.rstrip().endswith(QUESTION)
    assert fake_db.queries("INSERT INTO messages")[0][1] == (101, QUESTION, 101, ANSWER)
