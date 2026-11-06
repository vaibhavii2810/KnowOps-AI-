"""
tests/test_rate_limit.py  –  Phase 10.5 (D-036)
Per-user rate limiting on /ask and /agent/*. The counters live in MemoryDB by default and in the local
database under `pytest -m live` (Phase 11.4), with a unique user per test and frozen time so a minute
boundary mid-test cannot make a test flaky.
"""

import time
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import psycopg

import app.main as main
from app import ratelimit
from app.auth import create_access_token
from app.config import settings
from app.db import get_conn
from app.ratelimit import check_rate_limit, client_ip

# Phase 11.4: every test here runs on MemoryDB by default and against real Postgres under `pytest -m live`.
pytestmark = pytest.mark.usefixtures("db_backend")


@pytest.fixture
def user():
    key = f"rltest-{uuid.uuid4().hex[:10]}"
    yield key
    with get_conn() as conn:
        conn.execute("DELETE FROM rate_limits WHERE user_key LIKE 'rltest-%'")


@pytest.fixture
def fresh_limiter_connection():
    """Start the test with no shared limiter connection, and leave none behind."""
    def reset():
        if ratelimit._conn is not None:
            try:
                ratelimit._conn.close()
            except Exception:
                pass
        ratelimit._conn = None
        ratelimit._table_ready = False

    reset()
    yield
    reset()


@pytest.fixture
def window_start():
    """A fixed point at the start of a window, so every call in a test lands in the same window."""
    return int(time.time() // 60) * 60


@pytest.fixture
def client(monkeypatch, window_start):
    monkeypatch.setattr(main, "retrieve_and_format", lambda **kwargs: ([], []))
    monkeypatch.setattr(main, "chat_completion", lambda **kwargs: "stub answer")
    monkeypatch.setattr(
        main, "run_agent",
        lambda **kwargs: {"task": "t", "total_steps": 0, "steps": [], "resolution": "stub"},
    )
    # freeze the limiter's clock only (patching time.time globally would disturb everything else)
    monkeypatch.setattr(ratelimit, "time", SimpleNamespace(time=lambda: window_start + 10))
    return TestClient(main.app)


def headers_for(user_key):
    token = create_access_token({"sub": user_key, "role": "operator"})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# The counter
# ---------------------------------------------------------------------------

def test_allows_up_to_the_limit_then_blocks(user, window_start):
    results = [check_rate_limit(user, "ask", 3, now=window_start + 5) for _ in range(5)]
    assert [r.allowed for r in results] == [True, True, True, False, False]
    assert [r.remaining for r in results] == [2, 1, 0, 0, 0]


def test_retry_after_is_the_time_left_in_the_window(user, window_start):
    assert check_rate_limit(user, "ask", 1, now=window_start + 20).retry_after == 40
    assert check_rate_limit(user, "ask", 1, now=window_start + 59.2).retry_after == 1  # never below 1s


def test_a_new_window_starts_a_fresh_count(user, window_start):
    for _ in range(3):
        check_rate_limit(user, "ask", 3, now=window_start + 5)
    assert check_rate_limit(user, "ask", 3, now=window_start + 5).allowed is False
    next_window = check_rate_limit(user, "ask", 3, now=window_start + 65)
    assert next_window.allowed is True
    assert next_window.remaining == 2


def test_users_and_buckets_are_counted_separately(user, window_start):
    other = user + "-other"
    assert check_rate_limit(user, "ask", 1, now=window_start).allowed is True
    assert check_rate_limit(user, "ask", 1, now=window_start).allowed is False
    assert check_rate_limit(other, "ask", 1, now=window_start).allowed is True     # a different user
    assert check_rate_limit(user, "agent", 1, now=window_start).allowed is True    # a different bucket


def test_the_counter_table_is_created_on_first_use(user, window_start, fresh_limiter_connection):
    """Production needs no manual migration: the first request creates the table."""
    with get_conn() as conn:
        conn.execute("DROP TABLE IF EXISTS rate_limits")

    assert check_rate_limit(user, "ask", 5, now=window_start).allowed is True

    with get_conn() as conn:
        assert conn.execute("SELECT hits FROM rate_limits WHERE user_key = %s", (user,)).fetchone()[0] == 1


def test_it_fails_open_when_the_counter_cannot_be_reached(user, window_start, fresh_limiter_connection, monkeypatch, capsys):
    """A limiter fault must not take /ask down: the request is allowed and a warning is logged."""
    def unreachable(*args, **kwargs):
        raise psycopg.OperationalError("database unreachable")

    # Replace psycopg only inside the limiter's namespace: patching psycopg.connect itself would also
    # break this test's own cleanup connection.
    monkeypatch.setattr(
        ratelimit, "psycopg",
        SimpleNamespace(connect=unreachable, OperationalError=psycopg.OperationalError),
    )
    result = check_rate_limit(user, "ask", 1, now=window_start)
    assert result.allowed is True
    assert "Rate limiter unavailable" in capsys.readouterr().out


def test_it_reuses_one_connection_instead_of_connecting_per_request(user, window_start, fresh_limiter_connection, monkeypatch):
    """Connecting to the remote database costs ~1.2s through get_conn(); the limiter must pay that once."""
    real_connect = psycopg.connect
    connects = []

    def counting_connect(*args, **kwargs):
        connects.append(1)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(
        ratelimit, "psycopg",
        SimpleNamespace(connect=counting_connect, OperationalError=psycopg.OperationalError),
    )
    for _ in range(5):
        check_rate_limit(user, "ask", 99, now=window_start)
    assert len(connects) == 1


def test_it_reconnects_if_the_shared_connection_was_closed(user, window_start, fresh_limiter_connection):
    check_rate_limit(user, "ask", 99, now=window_start)
    ratelimit._conn.close()
    assert check_rate_limit(user, "ask", 99, now=window_start).remaining == 97  # counted 1, 2, then this 3rd


def test_it_reconnects_once_if_the_connection_has_gone_stale(user, window_start, fresh_limiter_connection):
    """A frozen serverless instance or an idle-dropped Neon connection fails on first use, not at open."""
    check_rate_limit(user, "ask", 99, now=window_start)

    class StaleConnection:
        closed = False

        def execute(self, *args, **kwargs):
            raise psycopg.OperationalError("server closed the connection unexpectedly")

        def close(self):
            pass

    ratelimit._conn = StaleConnection()
    result = check_rate_limit(user, "ask", 99, now=window_start)
    assert result.allowed is True
    assert result.remaining == 97                       # it really counted, on a fresh connection
    assert not isinstance(ratelimit._conn, StaleConnection)


# ---------------------------------------------------------------------------
# Over HTTP
# ---------------------------------------------------------------------------

def test_ask_returns_429_with_retry_after_once_over_the_limit(client, user, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_ask_per_minute", 2)
    headers = headers_for(user)
    body = {"question": "How do I fail over the database?"}

    first = client.post("/ask", json=body, headers=headers)
    second = client.post("/ask", json=body, headers=headers)
    third = client.post("/ask", json=body, headers=headers)

    assert (first.status_code, second.status_code, third.status_code) == (200, 200, 429)
    assert (first.headers["X-RateLimit-Limit"], first.headers["X-RateLimit-Remaining"]) == ("2", "1")
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert third.status_code == 429
    assert "Rate limit exceeded" in third.json()["detail"]
    assert 1 <= int(third.headers["Retry-After"]) <= 60
    assert third.headers["X-RateLimit-Remaining"] == "0"


def test_agent_chat_and_agent_triage_share_one_limit(client, user, monkeypatch):
    """/agent/triage runs the same expensive loop, so it must not be a way around /agent/chat's limit."""
    monkeypatch.setattr(settings, "rate_limit_agent_per_minute", 2)
    headers = headers_for(user)
    chat = {"prompt": "Investigate the worker crash"}

    assert client.post("/agent/chat", json=chat, headers=headers).status_code == 200
    assert client.post("/agent/chat", json=chat, headers=headers).status_code == 200
    assert client.post("/agent/triage/1", headers=headers).status_code == 429
    assert client.post("/agent/chat", json=chat, headers=headers).status_code == 429


def test_ask_and_agent_limits_are_independent(client, user, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_ask_per_minute", 1)
    monkeypatch.setattr(settings, "rate_limit_agent_per_minute", 1)
    headers = headers_for(user)
    assert client.post("/ask", json={"question": "valid question"}, headers=headers).status_code == 200
    assert client.post("/ask", json={"question": "valid question"}, headers=headers).status_code == 429
    assert client.post("/agent/chat", json={"prompt": "valid prompt"}, headers=headers).status_code == 200


def test_each_user_has_their_own_allowance_over_http(client, user, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_ask_per_minute", 1)
    body = {"question": "valid question"}
    assert client.post("/ask", json=body, headers=headers_for(user)).status_code == 200
    assert client.post("/ask", json=body, headers=headers_for(user)).status_code == 429
    assert client.post("/ask", json=body, headers=headers_for(user + "-b")).status_code == 200


def test_unauthenticated_requests_get_401_and_use_up_nothing(client, user, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_ask_per_minute", 1)
    for _ in range(3):
        assert client.post("/ask", json={"question": "valid question"}).status_code == 401
    assert client.post("/ask", json={"question": "valid question"}, headers=headers_for(user)).status_code == 200


def test_a_limit_of_zero_disables_the_bucket(client, user):
    headers = headers_for(user)  # conftest defaults both limits to 0
    for _ in range(5):
        assert client.post("/ask", json={"question": "valid question"}, headers=headers).status_code == 200


def test_other_routes_are_not_rate_limited(client, user, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_ask_per_minute", 1)
    monkeypatch.setattr(settings, "rate_limit_agent_per_minute", 1)
    headers = headers_for(user)
    for _ in range(5):
        assert client.get("/tickets/stats", headers=headers).status_code == 200
    assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# Login: per-client-IP limits (D-037)
# ---------------------------------------------------------------------------

def _request(headers, client=("9.9.9.9", 1234)):
    from starlette.requests import Request
    return Request({
        "type": "http", "client": client,
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
    })


def _login(client, ip, password="not-the-password", username="admin"):
    return client.post(
        "/auth/login", json={"username": username, "password": password}, headers={"X-Forwarded-For": ip}
    )


def test_client_ip_prefers_the_vercel_header_then_the_first_forwarded_entry_then_the_socket():
    assert client_ip(_request({"x-vercel-forwarded-for": "1.1.1.1", "x-forwarded-for": "2.2.2.2"})) == "1.1.1.1"
    assert client_ip(_request({"x-forwarded-for": "3.3.3.3, 4.4.4.4"})) == "3.3.3.3"
    assert client_ip(_request({"x-real-ip": "5.5.5.5"})) == "5.5.5.5"
    assert client_ip(_request({})) == "9.9.9.9"
    assert client_ip(_request({}, client=None)) == "unknown"


def test_login_attempts_are_limited_per_ip(client, user, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 3)
    codes = [_login(client, user).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]
    blocked = _login(client, user)
    assert "Too many login attempts" in blocked.json()["detail"]
    assert 1 <= int(blocked.headers["Retry-After"]) <= 60


def test_correct_credentials_get_nothing_extra_once_blocked(client, user, monkeypatch):
    """If the right password still worked after the limit, response speed would tell an attacker when a guess hit."""
    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 3)
    for _ in range(3):
        _login(client, user)
    assert _login(client, user, password=settings.app_password).status_code == 429


def test_a_normal_login_within_the_limit_still_works(client, user, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 3)
    response = _login(client, user, password=settings.app_password, username=settings.app_username)
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_each_ip_has_its_own_login_allowance(client, user, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 2)
    for _ in range(2):
        _login(client, user)
    assert _login(client, user).status_code == 429
    assert _login(client, user + "-b", password=settings.app_password, username=settings.app_username).status_code == 200


def test_malformed_login_bodies_count_too(client, user, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 2)
    headers = {"X-Forwarded-For": user}
    codes = [client.post("/auth/login", json={"username": 1}, headers=headers).status_code for _ in range(3)]
    assert codes == [422, 422, 429]


def test_the_hourly_cap_stops_slow_guessing_that_stays_under_the_per_minute_limit(client, user, monkeypatch, window_start):
    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 0)
    monkeypatch.setattr(settings, "rate_limit_login_per_hour", 2)
    codes = [_login(client, user).status_code for _ in range(3)]
    assert codes == [401, 401, 429]
    now = window_start + 10                      # the frozen clock from the `client` fixture
    hour_end = (int(now // 3600) + 1) * 3600
    assert _login(client, user).headers["Retry-After"] == str(hour_end - now)


def test_login_limits_can_be_switched_off(client, user):
    assert [_login(client, user).status_code for _ in range(8)] == [401] * 8   # conftest defaults both to 0


def test_other_auth_routes_are_not_login_limited(client, user, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 1)
    headers = {**headers_for(user), "X-Forwarded-For": user}
    for _ in range(4):
        assert client.get("/auth/me", headers=headers).status_code == 200
