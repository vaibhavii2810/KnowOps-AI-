"""
tests/test_input_validation.py  –  Phase 10.2 (D-033)
"A bad request never crashes the API": hostile input gets a clear 4xx, never a 500.

Gemini and the agent are stubbed, so these exercise only request validation and the database
layer — no quota is spent.
"""

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.auth import verify_operator_credentials
from app.config import settings


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "retrieve_and_format", lambda **kwargs: ([], []))
    monkeypatch.setattr(main, "chat_completion", lambda **kwargs: "stub answer")
    monkeypatch.setattr(
        main, "run_agent",
        lambda **kwargs: {"task": "t", "total_steps": 0, "steps": [], "resolution": "stub"},
    )
    # raise_server_exceptions=False: an unhandled error must surface as a 500, not a test exception
    return TestClient(main.app, raise_server_exceptions=False)


VALID_TICKET = {"subject": "Valid subject", "description": "A valid description"}

# (id, method, url, request kwargs) — every one of these must come back as a 4xx, never a 5xx.
HOSTILE_REQUESTS = [
    # --- malformed bodies on every JSON route ---
    ("login-invalid-json", "POST", "/auth/login", {"content": b"{not json"}),
    ("ask-invalid-json", "POST", "/ask", {"content": b"{not json"}),
    ("ticket-invalid-json", "POST", "/tickets", {"content": b"{not json"}),
    ("agent-invalid-json", "POST", "/agent/chat", {"content": b"{not json"}),
    ("patch-invalid-json", "PATCH", "/tickets/1", {"content": b"{not json"}),
    ("ask-empty-body", "POST", "/ask", {"content": b""}),
    ("ask-body-is-a-list", "POST", "/ask", {"content": b"[1,2,3]"}),
    ("ask-body-is-null", "POST", "/ask", {"content": b"null"}),
    ("ticket-wrong-content-type", "POST", "/tickets", {"content": b"hello", "headers": {"Content-Type": "text/plain"}}),
    # --- wrong types / nulls ---
    ("ask-question-int", "POST", "/ask", {"json": {"question": 12345}}),
    ("ask-question-null", "POST", "/ask", {"json": {"question": None}}),
    ("ask-top-k-string", "POST", "/ask", {"json": {"question": "valid question", "top_k": "five"}}),
    ("ticket-priority-int", "POST", "/tickets", {"json": {**VALID_TICKET, "priority": 1}}),
    ("patch-status-int", "PATCH", "/tickets/1", {"json": {"status": 5}}),
    # --- whitespace-only text (min_length used to count the spaces) ---
    ("ask-whitespace-question", "POST", "/ask", {"json": {"question": "     "}}),
    ("ticket-whitespace-subject", "POST", "/tickets", {"json": {"subject": "     ", "description": "A valid description"}}),
    ("ticket-whitespace-description", "POST", "/tickets", {"json": {"subject": "Valid subject", "description": "      "}}),
    ("agent-whitespace-prompt", "POST", "/agent/chat", {"json": {"prompt": "     "}}),
    # --- NUL bytes: Postgres cannot store them, so these used to be HTTP 500s ---
    ("ask-nul", "POST", "/ask", {"json": {"question": "hello\u0000world question"}}),
    ("ticket-nul-subject", "POST", "/tickets", {"json": {**VALID_TICKET, "subject": "bad\u0000subject"}}),
    ("ticket-nul-description", "POST", "/tickets", {"json": {**VALID_TICKET, "description": "bad\u0000description"}}),
    ("patch-nul-notes", "PATCH", "/tickets/1", {"json": {"status": "open", "resolution_notes": "a\u0000b"}}),
    ("agent-nul-prompt", "POST", "/agent/chat", {"json": {"prompt": "do\u0000thing now"}}),
    ("tickets-nul-status-filter", "GET", "/tickets?status=%00", {}),
    # --- enums ---
    ("ticket-bad-priority", "POST", "/tickets", {"json": {**VALID_TICKET, "priority": "banana"}}),
    ("patch-bad-status", "PATCH", "/tickets/1", {"json": {"status": "banana"}}),
    ("tickets-bad-status-filter", "GET", "/tickets?status=banana", {}),
    ("tickets-bad-priority-filter", "GET", "/tickets?priority=banana", {}),
    # --- numeric extremes ---
    ("ask-top-k-zero", "POST", "/ask", {"json": {"question": "valid question", "top_k": 0}}),
    ("ask-conversation-id-negative", "POST", "/ask", {"json": {"question": "valid question", "conversation_id": -5}}),
    ("ask-conversation-id-huge", "POST", "/ask", {"json": {"question": "valid question", "conversation_id": 10**30}}),
    ("ask-too-long", "POST", "/ask", {"json": {"question": "a" * 10000}}),
    ("agent-max-steps-99", "POST", "/agent/chat", {"json": {"prompt": "valid prompt", "max_steps": 99}}),
    ("login-password-too-long", "POST", "/auth/login", {"json": {"username": "admin", "password": "x" * 5000}}),
    # --- query parameters: a negative LIMIT used to be a 500 ---
    ("tickets-limit-negative", "GET", "/tickets?limit=-5", {}),
    ("tickets-limit-zero", "GET", "/tickets?limit=0", {}),
    ("tickets-limit-huge", "GET", "/tickets?limit=999999999999", {}),
    ("tickets-limit-text", "GET", "/tickets?limit=abc", {}),
    ("conversations-limit-negative", "GET", "/conversations?limit=-5", {}),
    ("conversations-limit-huge", "GET", "/conversations?limit=999999999999", {}),
    # --- path parameters ---
    ("ticket-id-text", "GET", "/tickets/abc", {}),
    ("ticket-id-float", "GET", "/tickets/1.5", {}),
    ("ticket-id-huge", "GET", "/tickets/99999999999999999999", {}),
    ("conversation-id-huge", "GET", "/conversations/99999999999999999999", {}),
    ("triage-id-text", "POST", "/agent/triage/abc", {}),
]


@pytest.mark.parametrize("name,method,url,kwargs", HOSTILE_REQUESTS, ids=[c[0] for c in HOSTILE_REQUESTS])
def test_hostile_request_gets_a_4xx_never_a_5xx(client, auth_headers, name, method, url, kwargs):
    headers = {**auth_headers, **kwargs.get("headers", {})}
    if "json" in kwargs:
        headers.setdefault("Content-Type", "application/json")
    elif "content" in kwargs and "headers" not in kwargs:
        headers["Content-Type"] = "application/json"
    request_kwargs = {k: v for k, v in kwargs.items() if k != "headers"}
    response = client.request(method, url, headers=headers, **request_kwargs)
    assert 400 <= response.status_code < 500, f"{name}: got {response.status_code}: {response.text[:200]}"


# ---------------------------------------------------------------------------
# The 422s are clear: they name the field and say what is allowed
# ---------------------------------------------------------------------------

def _first_error(response):
    assert response.status_code == 422
    error = response.json()["detail"][0]
    return ".".join(str(part) for part in error["loc"]), error["msg"]


def test_whitespace_only_subject_is_rejected_not_stored_blank(client, auth_headers):
    loc, msg = _first_error(client.post("/tickets", headers=auth_headers, json={**VALID_TICKET, "subject": "     "}))
    assert loc == "body.subject"
    assert "at least 3 characters" in msg


def test_invalid_priority_is_a_422_listing_the_allowed_values(client, auth_headers):
    loc, msg = _first_error(client.post("/tickets", headers=auth_headers, json={**VALID_TICKET, "priority": "banana"}))
    assert loc == "body.priority"
    assert "'P1', 'P2', 'P3' or 'P4'" in msg


def test_invalid_ticket_status_is_a_422_not_the_old_400(client, auth_headers):
    loc, msg = _first_error(client.patch("/tickets/1", headers=auth_headers, json={"status": "banana"}))
    assert loc == "body.status"
    assert "'open', 'in_progress', 'resolved' or 'closed'" in msg


def test_nul_byte_is_a_422_naming_the_field(client, auth_headers):
    loc, msg = _first_error(client.post("/tickets", headers=auth_headers, json={**VALID_TICKET, "description": "bad\u0000x description"}))
    assert loc == "body.description"
    assert "NUL" in msg


def test_limit_bounds_are_enforced_on_both_list_routes(client, auth_headers):
    assert _first_error(client.get("/tickets?limit=-5", headers=auth_headers))[0] == "query.limit"
    assert _first_error(client.get("/tickets?limit=201", headers=auth_headers))[0] == "query.limit"
    assert _first_error(client.get("/conversations?limit=101", headers=auth_headers))[0] == "query.limit"
    assert client.get("/tickets?limit=200", headers=auth_headers).status_code == 200
    assert client.get("/conversations?limit=100", headers=auth_headers).status_code == 200


# ---------------------------------------------------------------------------
# Auth: non-ASCII credentials used to crash login with a 500
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("username,password", [("ädmin", "x"), ("admin", "pässwörd"), ("🔥", "🔥"), ("管理者", "密码")])
def test_login_with_non_ascii_credentials_is_a_401_not_a_500(client, username, password):
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 401


def test_verify_operator_credentials_handles_non_ascii_without_raising():
    assert verify_operator_credentials("ädmin", "pässwörd") is False
    assert verify_operator_credentials(settings.app_username, settings.app_password) is True


# ---------------------------------------------------------------------------
# Strictness must not break legitimate input
# ---------------------------------------------------------------------------

def test_priority_and_status_stay_case_insensitive_and_whitespace_is_trimmed(client, auth_headers):
    created = client.post(
        "/tickets", headers=auth_headers,
        json={"subject": "  padded subject  ", "description": "A valid description", "priority": "p1"},
    )
    assert created.status_code == 200
    assert created.json()["subject"] == "padded subject"
    assert created.json()["priority"] == "P1"

    updated = client.patch(f"/tickets/{created.json()['id']}", headers=auth_headers, json={"status": " In_Progress "})
    assert updated.status_code == 200
    assert updated.json()["status"] == "in_progress"


def test_unicode_and_sql_looking_text_is_stored_verbatim(client, auth_headers):
    """Queries are parameterized: hostile-looking text is just data, and unicode is fine."""
    subject = "x'); DROP TABLE tickets;-- 🔥 日本語"
    created = client.post("/tickets", headers=auth_headers, json={**VALID_TICKET, "subject": subject})
    assert created.status_code == 200
    fetched = client.get(f"/tickets/{created.json()['id']}", headers=auth_headers)
    assert fetched.json()["subject"] == subject
    assert client.get("/tickets/stats", headers=auth_headers).status_code == 200  # table still exists
