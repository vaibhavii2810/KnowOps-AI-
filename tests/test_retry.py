"""
tests/test_retry.py  –  Phase 10.1 (D-032)
Retry/backoff for transient Gemini and Postgres failures. Sleep is patched so these run instantly.
"""

import json

import httpx
import psycopg
import pytest
from google.genai import errors as genai_errors
from psycopg import errors as pg_errors

from app import db, llm
from app.agent import run_agent
from app.retry import is_transient_db_error, is_transient_gemini_error, retry_call


@pytest.fixture
def sleeps(monkeypatch):
    """Capture backoff delays instead of actually sleeping."""
    recorded = []
    monkeypatch.setattr("app.retry.time.sleep", lambda s: recorded.append(s))
    return recorded


def gemini_error(code):
    cls = genai_errors.ServerError if code >= 500 else genai_errors.ClientError
    return cls(code, {"error": {"code": code, "message": f"simulated {code}", "status": "SIMULATED"}})


# ---------------------------------------------------------------------------
# Classification: what is worth retrying
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
def test_transient_gemini_status_codes_are_retried(code):
    assert is_transient_gemini_error(gemini_error(code)) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_permanent_gemini_status_codes_fail_fast(code):
    assert is_transient_gemini_error(gemini_error(code)) is False


def test_network_failures_are_transient_but_programming_errors_are_not():
    assert is_transient_gemini_error(httpx.ReadTimeout("slow")) is True
    assert is_transient_gemini_error(httpx.ConnectError("refused")) is True
    assert is_transient_gemini_error(TimeoutError()) is True
    assert is_transient_gemini_error(ValueError("bug")) is False


def test_db_connection_failures_are_transient_but_auth_and_sql_errors_are_not():
    assert is_transient_db_error(psycopg.OperationalError("server closed the connection")) is True
    assert is_transient_db_error(pg_errors.InvalidPassword("bad password")) is False
    assert is_transient_db_error(pg_errors.InvalidAuthorizationSpecification("auth")) is False
    assert is_transient_db_error(psycopg.ProgrammingError("bad sql")) is False
    assert is_transient_db_error(psycopg.IntegrityError("dup")) is False


# ---------------------------------------------------------------------------
# retry_call mechanics
# ---------------------------------------------------------------------------

def test_success_on_first_try_never_sleeps(sleeps):
    assert retry_call(lambda: "ok", is_transient=lambda e: True, label="t") == "ok"
    assert sleeps == []


def test_retries_transient_errors_then_succeeds(sleeps):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise gemini_error(503)
        return "recovered"

    assert retry_call(flaky, is_transient=is_transient_gemini_error, label="t") == "recovered"
    assert len(calls) == 3
    assert len(sleeps) == 2


def test_permanent_error_raises_immediately_without_retry(sleeps):
    calls = []

    def bad_request():
        calls.append(1)
        raise gemini_error(400)

    with pytest.raises(genai_errors.ClientError):
        retry_call(bad_request, is_transient=is_transient_gemini_error, label="t")
    assert len(calls) == 1
    assert sleeps == []


def test_gives_up_after_max_attempts_and_reraises_the_last_error(sleeps):
    calls = []

    def always_down():
        calls.append(1)
        raise gemini_error(503)

    with pytest.raises(genai_errors.ServerError):
        retry_call(always_down, is_transient=is_transient_gemini_error, label="t", attempts=4)
    assert len(calls) == 4
    assert len(sleeps) == 3  # no sleep after the final failed attempt


def test_backoff_grows_exponentially_with_jitter_and_respects_the_cap(sleeps):
    def always_down():
        raise gemini_error(429)

    with pytest.raises(genai_errors.ClientError):
        retry_call(
            always_down, is_transient=is_transient_gemini_error, label="t",
            attempts=5, base_delay=1.0, max_delay=3.0,
        )
    # nominal delays 1, 2, 4->capped 3, 8->capped 3; jitter keeps each in [0.5x, 1.0x]
    nominal = [1.0, 2.0, 3.0, 3.0]
    assert len(sleeps) == 4
    for actual, ceiling in zip(sleeps, nominal):
        assert ceiling * 0.5 <= actual <= ceiling


# ---------------------------------------------------------------------------
# Call sites
# ---------------------------------------------------------------------------

class _Embedding:
    values = [0.1] * 768


class _EmbedResponse:
    embeddings = [_Embedding()]


class _TextResponse:
    def __init__(self, text):
        self.text = text
        self.candidates = []


def _fake_client(models):
    client = type("FakeClient", (), {})()
    client.models = models
    return client


def test_embed_text_retries_a_503_then_succeeds(sleeps, monkeypatch):
    attempts = []

    class Models:
        def embed_content(self, **kwargs):
            attempts.append(1)
            if len(attempts) < 3:
                raise gemini_error(503)
            return _EmbedResponse()

    monkeypatch.setattr(llm, "get_client", lambda: _fake_client(Models()))
    assert llm.embed_text("how do I fail over?") == [0.1] * 768
    assert len(attempts) == 3


def test_embed_text_does_not_retry_a_bad_request(sleeps, monkeypatch):
    attempts = []

    class Models:
        def embed_content(self, **kwargs):
            attempts.append(1)
            raise gemini_error(400)

    monkeypatch.setattr(llm, "get_client", lambda: _fake_client(Models()))
    with pytest.raises(genai_errors.ClientError):
        llm.embed_text("x")
    assert len(attempts) == 1


def test_chat_completion_retries_a_500_which_the_old_code_never_did(sleeps, monkeypatch):
    """The old inline loop only recognised 429/503 (by string match); a plain 500 was fatal."""
    attempts = []

    class Models:
        def generate_content(self, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise gemini_error(500)
            return _TextResponse("grounded answer")

    monkeypatch.setattr(llm, "get_client", lambda: _fake_client(Models()))
    assert llm.chat_completion("q", ["ctx"]) == "grounded answer"
    assert len(attempts) == 2


def test_run_agent_step_survives_a_429(sleeps, monkeypatch):
    """The agent's Gemini calls previously had no retry for real API errors at all."""
    attempts = []
    final = json.dumps({"thought": "done", "action": "", "args": {}, "is_final": True, "final_answer": "All clear."})

    class Models:
        def generate_content(self, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise gemini_error(429)
            return _TextResponse(final)

    monkeypatch.setattr("app.agent.get_client", lambda: _fake_client(Models()))
    result = run_agent("Report status.", max_steps=2)
    assert result["resolution"] == "All clear."
    assert len(attempts) == 2


class _FakeConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_get_conn_retries_a_transient_connect_failure(sleeps, monkeypatch):
    attempts = []
    conn = _FakeConn()

    def flaky_connect(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise psycopg.OperationalError("connection refused (Neon cold start)")
        return conn

    monkeypatch.setattr(db.psycopg, "connect", flaky_connect)
    monkeypatch.setattr(db, "register_vector", lambda c: None)

    with db.get_conn() as got:
        assert got is conn
    assert len(attempts) == 3
    assert conn.closed is True


def test_get_conn_fails_fast_on_a_wrong_password(sleeps, monkeypatch):
    attempts = []

    def bad_auth(*args, **kwargs):
        attempts.append(1)
        raise pg_errors.InvalidPassword("password authentication failed")

    monkeypatch.setattr(db.psycopg, "connect", bad_auth)

    with pytest.raises(pg_errors.InvalidPassword):
        with db.get_conn():
            pass
    assert len(attempts) == 1
    assert sleeps == []


# ---------------------------------------------------------------------------
# HTTP contract: retries must not change status codes or error text (D-032)
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


def _failing_gemini(monkeypatch, code):
    calls = []

    class Models:
        def embed_content(self, **kwargs):
            calls.append(1)
            raise gemini_error(code)

        def generate_content(self, **kwargs):
            calls.append(1)
            raise gemini_error(code)

    monkeypatch.setattr(llm, "get_client", lambda: _fake_client(Models()))
    return calls


def test_ask_still_maps_exhausted_embedding_retries_to_the_same_503(client, auth_headers, sleeps, monkeypatch):
    calls = _failing_gemini(monkeypatch, 503)
    r = client.post("/ask", json={"question": "How do I fail over the database?"}, headers=auth_headers)
    assert r.status_code == 503
    assert r.json()["detail"].startswith("Retrieval failed — database or embedding error:")
    assert len(calls) == 4  # retried, then gave up
    assert len(sleeps) == 3


def test_ask_still_maps_a_permanent_embedding_error_to_the_same_503_without_retrying(
    client, auth_headers, sleeps, monkeypatch
):
    calls = _failing_gemini(monkeypatch, 400)
    r = client.post("/ask", json={"question": "How do I fail over the database?"}, headers=auth_headers)
    assert r.status_code == 503
    assert r.json()["detail"].startswith("Retrieval failed — database or embedding error:")
    assert len(calls) == 1
    assert sleeps == []


def test_ask_still_maps_exhausted_chat_retries_to_the_same_503(client, auth_headers, sleeps, monkeypatch):
    monkeypatch.setattr("app.main.retrieve_and_format", lambda **kwargs: ([], []))
    calls = _failing_gemini(monkeypatch, 500)
    r = client.post("/ask", json={"question": "How do I fail over the database?"}, headers=auth_headers)
    assert r.status_code == 503
    assert r.json()["detail"].startswith("AI generation failed — Gemini API error:")
    assert len(calls) == 4


def test_health_reports_degraded_immediately_without_retrying(client, sleeps, monkeypatch):
    """/health must fail fast: a monitor needs the 503, not a ~7s hang that looks like a timeout."""
    attempts = []

    def down(*args, **kwargs):
        attempts.append(1)
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(db.psycopg, "connect", down)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["detail"] == {"status": "degraded", "database": "error: connection refused"}
    assert len(attempts) == 1
    assert sleeps == []


def test_agent_database_diagnostic_reports_degraded_instead_of_retrying(sleeps, monkeypatch):
    from app.agent import tool_run_system_diagnostics

    attempts = []

    def down(*args, **kwargs):
        attempts.append(1)
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(db.psycopg, "connect", down)
    result = json.loads(tool_run_system_diagnostics("database"))
    assert result["status"] == "degraded"
    assert len(attempts) == 1
    assert sleeps == []
