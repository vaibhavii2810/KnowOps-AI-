"""
tests/test_logging.py  –  Phase 12.1
Structured JSON logs (D-042): one `request` line per request with id, user, latency, status and the tools
the agent called; every other event during that request carries the same request_id; nothing secret
is ever written. Offline — Gemini and Postgres are fakes.
"""

import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.config import settings

PASSWORD_PROBE = "pässword-probe-8c1f"


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def logs(capsys):
    """Every JSON log line written so far, parsed (non-JSON output is ignored)."""
    def read():
        return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    return read


def only_request_line(entries):
    lines = [e for e in entries if e["event"] == "request"]
    assert len(lines) == 1, lines
    return lines[0]


def test_every_request_gets_one_request_line_and_an_id_header(client, memory_db, logs):
    response = client.get("/health")

    line = only_request_line(logs())
    assert response.headers["x-request-id"] == line["request_id"]
    assert len(line["request_id"]) == 32  # uuid4 hex
    assert (line["method"], line["path"], line["status"], line["level"]) == ("GET", "/health", 200, "info")
    assert isinstance(line["latency_ms"], (int, float)) and line["latency_ms"] >= 0
    assert line["user"] is None
    assert line["ts"].endswith("+00:00")


def test_two_requests_get_different_ids(client, memory_db, logs):
    first = client.get("/health").headers["x-request-id"]
    second = client.get("/health").headers["x-request-id"]
    assert first != second
    assert [e["request_id"] for e in logs() if e["event"] == "request"] == [first, second]


def test_a_valid_inbound_request_id_is_kept_and_a_hostile_one_replaced(client, memory_db, logs):
    kept = client.get("/health", headers={"X-Request-ID": "trace-0123456789"})
    replaced = client.get("/health", headers={"X-Request-ID": 'x"}\n{"event":"forged"'})

    assert kept.headers["x-request-id"] == "trace-0123456789"
    assert replaced.headers["x-request-id"] != 'x"}\n{"event":"forged"'
    entries = logs()
    assert [e["event"] for e in entries] == ["request", "request"]  # no forged line got in


def test_the_authenticated_user_is_logged_and_a_rejected_request_is_a_warning(client, auth_headers, memory_db, logs):
    client.get("/tickets/stats", headers=auth_headers)
    client.get("/tickets/stats")

    ok, rejected = [e for e in logs() if e["event"] == "request"]
    assert ok["user"] == settings.app_username and ok["status"] == 200
    assert rejected["user"] is None and rejected["status"] == 401 and rejected["level"] == "warning"


def test_the_tools_the_agent_called_are_on_the_request_line(client, auth_headers, fake_gemini, memory_db, logs):
    fake_gemini.reply(
        {"thought": "check", "action": "lookup_runbook", "args": {"query": "failover"}, "is_final": False},
        {"thought": "db", "action": "run_system_diagnostics", "args": {"component": "database"}, "is_final": False},
        {"thought": "done", "is_final": True, "final_answer": "All clear."},
    )

    response = client.post("/agent/chat", json={"prompt": "Is the database healthy?"}, headers=auth_headers)

    assert response.status_code == 200, response.text
    line = only_request_line(logs())
    assert line["tools"] == ["lookup_runbook", "run_system_diagnostics"]
    assert line["path"] == "/agent/chat" and line["user"] == settings.app_username


def test_events_during_a_request_carry_its_request_id(client, auth_headers, memory_db, logs, monkeypatch):
    """The rate limiter fails open with a warning; that warning must be findable by the request's id."""
    monkeypatch.setattr(settings, "rate_limit_ask_per_minute", 10)
    monkeypatch.setattr(main, "retrieve_and_format", lambda **kwargs: ([], []))
    monkeypatch.setattr(main, "chat_completion", lambda **kwargs: "stub answer")
    memory_db._db.on("INSERT INTO rate_limits", lambda params: (_ for _ in ()).throw(RuntimeError("counter down")))

    response = client.post("/ask", json={"question": "valid question"}, headers=auth_headers)

    entries = logs()
    warning = next(e for e in entries if e["event"] == "rate_limiter_unavailable")
    request = only_request_line(entries)
    assert warning["request_id"] == request["request_id"] == response.headers["x-request-id"]
    assert warning["level"] == "warning" and warning["error_type"] == "RuntimeError"


def test_an_unhandled_error_is_logged_as_a_500_with_its_type(client, auth_headers, memory_db, logs, monkeypatch):
    def broken():
        raise ZeroDivisionError("boom")
    monkeypatch.setattr(main, "get_crm_stats", broken)

    assert client.get("/tickets/stats", headers=auth_headers).status_code == 500

    line = only_request_line(logs())
    assert (line["status"], line["level"], line["error_type"]) == (500, "error", "ZeroDivisionError")


def test_vercels_own_request_id_is_kept_for_correlation(client, memory_db, logs):
    client.get("/health", headers={"x-vercel-id": "bom1::iad1::abcde-1700000000000-0123456789ab"})
    assert only_request_line(logs())["vercel_id"] == "bom1::iad1::abcde-1700000000000-0123456789ab"


def test_no_secrets_tokens_bodies_or_query_strings_are_logged(client, auth_headers, memory_db, logs, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 5)  # the login limiter writes to the DB too
    client.post("/auth/login", json={"username": "admin", "password": PASSWORD_PROBE})
    client.post("/tickets", json={"subject": "Secret subject probe", "description": "Secret description probe"},
                headers=auth_headers)
    client.get("/tickets?status=open&priority=P1", headers=auth_headers)

    raw = "\n".join(json.dumps(e) for e in logs())
    token = auth_headers["Authorization"].split()[1]
    for secret in (PASSWORD_PROBE, token, settings.jwt_secret, "Secret subject probe", "Secret description probe",
                   "priority=P1"):
        assert secret not in raw, secret


def test_long_fields_are_cut_and_every_line_is_one_json_object(capsys):
    from app.logs import MAX_FIELD_CHARS, log_event

    log_event("probe", "warning", detail="x" * 5000, note="line one\nline two")

    out = capsys.readouterr().out
    assert out.count("\n") == 1  # a newline inside a field is escaped, so it can't start a fake log line
    entry = json.loads(out)
    assert len(entry["detail"]) == MAX_FIELD_CHARS + 1 and entry["detail"].endswith("…")
    assert entry["note"] == "line one\nline two" and entry["level"] == "warning"
