"""
tests/test_fixtures.py  –  Phase 11.1
Proves the shared fakes in tests/conftest.py do what they claim (D-038): Gemini and Postgres are
replaced at their roots, and an offline test that reaches a real server is caught even when the
app swallows the error.
"""

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from app import db, llm, ratelimit
from app.agent import run_agent
from app.db import get_conn
from app.main import app
from app.rag import retrieve


# --- fake_gemini -------------------------------------------------------------

def test_fake_gemini_serves_embeddings_deterministically(fake_gemini):
    first = llm.embed_query("how do I fail over the database?")
    again = llm.embed_query("how do I fail over the database?")
    other = llm.embed_query("rotate the TLS certificate")

    assert len(first) == 768
    assert first == again
    assert first != other
    assert abs(sum(x * x for x in first) - 1.0) < 1e-9  # unit vector, like a real cosine-search input
    assert fake_gemini.embed_calls[0]["config"].task_type == "RETRIEVAL_QUERY"


def test_fake_gemini_serves_chat_and_records_the_prompt(fake_gemini):
    fake_gemini.reply("Promote the replica (Disaster Recovery Runbook).")

    answer = llm.chat_completion("How do I fail over?", ["Step 1: promote the replica."])

    assert answer == "Promote the replica (Disaster Recovery Runbook)."
    sent = fake_gemini.chat_calls[0]["contents"][-1].parts[0].text
    assert "promote the replica" in sent and "<untrusted_data" in sent  # grounded + fenced (D-034)


def test_fake_gemini_reaches_the_agent_without_patching_app_agent(fake_gemini):
    """app/agent.py imports get_client by name; replacing genai.Client at the root still reaches it."""
    fake_gemini.reply({"thought": "Nothing to do.", "is_final": True, "final_answer": "All clear."})

    result = run_agent("Is anything wrong?", max_steps=2)

    assert result["resolution"] == "All clear."
    assert len(fake_gemini.chat_calls) == 1


def test_fake_gemini_can_raise_and_return_malformed_responses(fake_gemini):
    fake_gemini.reply(None, ValueError("boom"))

    assert fake_gemini.generate_content(contents="x").text is None
    with pytest.raises(ValueError, match="boom"):
        fake_gemini.generate_content(contents="y")
    assert fake_gemini.generate_content(contents="z").text == fake_gemini.default_reply


# --- fake_db -----------------------------------------------------------------

def test_fake_db_serves_get_conn_and_records_statements(fake_db):
    fake_db.on("SELECT COUNT(*) FROM chunks", [(80,)])

    with get_conn() as conn:
        assert conn.execute("select count(*)\n  from chunks").fetchone() == (80,)  # whitespace/case ignored
        assert conn.execute("INSERT INTO messages VALUES (%s)", ("hi",)).fetchone() is None  # unscripted

    assert fake_db.connections == 1
    assert fake_db.queries("insert into messages") == [("INSERT INTO messages VALUES (%s)", ("hi",))]


def test_fake_db_latest_script_wins_and_callables_see_params(fake_db):
    fake_db.on("FROM tickets", [("old",)])
    fake_db.on("FROM tickets WHERE id", lambda params: [(f"ticket {params[0]}",)])

    with get_conn() as conn:
        assert conn.execute("SELECT * FROM tickets WHERE id = %s", (7,)).fetchone() == ("ticket 7",)
        assert conn.execute("SELECT * FROM tickets").fetchone() == ("old",)


def test_retrieve_runs_on_both_fakes_and_keeps_the_database_order(fake_gemini, fake_db):
    fake_db.on("FROM chunks c", [
        (11, "DR Runbook", "dr.md", "4.2 Failover", "Promote the replica.", 0.91),
        (12, "DB Runbook", "db.md", "Backups", "Restore from snapshot.", 0.74),
    ])

    chunks = retrieve("how do I fail over?", top_k=2, threshold=0.5)

    assert [c.chunk_id for c in chunks] == [11, 12]
    assert chunks[0].similarity == 0.91
    sql, params = fake_db.queries("FROM chunks c")[0]
    assert params[2] == 0.5 and params[4] == 2  # threshold and top_k reach the SQL
    assert len(fake_gemini.embed_calls) == 1


def test_health_endpoint_works_end_to_end_on_the_fake_db(fake_db):
    fake_db.on("COUNT(*) FROM documents", [(5,)]).on("COUNT(*) FROM chunks", [(80,)])

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["knowledge_base"] == {"documents": 5, "chunks": 80}


def test_fake_db_also_backs_the_rate_limiter(fake_db, monkeypatch):
    fake_db.on("INSERT INTO rate_limits", [(1,)])

    result = ratelimit.check_rate_limit("alice", "ask", limit=10)

    assert result.allowed and result.remaining == 9
    assert fake_db.queries("CREATE TABLE IF NOT EXISTS rate_limits")


# --- no_network --------------------------------------------------------------

def test_no_network_blocks_outbound_http(no_network):
    with pytest.raises(Exception, match="real network call"):
        httpx.get("http://203.0.113.1/", timeout=2)  # TEST-NET-3 literal: no DNS lookup involved
    assert no_network.attempts
    no_network.attempts.clear()  # handled here; otherwise teardown would (rightly) fail this test


def test_no_network_blocks_real_postgres(no_network):
    with pytest.raises(Exception, match="real Postgres"):
        with get_conn():
            pass
    with pytest.raises(Exception, match="real Postgres"):
        psycopg.connect("postgresql://user:password@example.invalid/db")  # the template form the 10.4 scanner allows
    no_network.attempts.clear()


def test_no_network_records_calls_the_app_swallows(no_network, monkeypatch):
    """The rate limiter fails open on any error, so the blocked connect never reaches the test —
    which is exactly why attempts are recorded and checked at teardown."""
    monkeypatch.setattr(ratelimit, "_conn", None)  # force a fresh connect, not one cached by an earlier test
    result = ratelimit.check_rate_limit("alice", "ask", limit=10)

    assert result.allowed  # fail-open hid the error...
    assert no_network.attempts == ["psycopg.connect (real Postgres)"]  # ...the guard did not
    no_network.attempts.clear()


# --- get_conn(vectors=...) (D-080, bug #25) -----------------------------------

def test_get_conn_does_not_register_the_vector_adapter_by_default(fake_db, monkeypatch):
    """register_vector() is ~0.8s of get_conn()'s ~1.2s cost (measured in D-036) and is only needed by a
    caller that binds a raw Python list/array as a vector-typed parameter — scripts/ingest.py's
    insert_chunk(), the only place that does. Every other caller (including /ask's retrieve(), which
    formats the vector as a text literal and casts it server-side) needs no adapter at all."""
    calls = []
    monkeypatch.setattr(db, "register_vector", lambda conn: calls.append(conn))

    with get_conn():
        pass
    assert calls == []

    with get_conn(vectors=True):
        pass
    assert len(calls) == 1
