# Pytest test configuration and fixtures (built in Phase 4; Gemini/DB fakes added in Phase 11.1, D-038)

import hashlib
import json
import math
import re
import socket
from types import SimpleNamespace

import psycopg
import pytest

from app import db, llm, ratelimit
from app.auth import create_access_token
from app.config import settings


@pytest.fixture
def auth_headers() -> dict:
    """Authorization header for a valid operator JWT (Phase 5.4 protected routes)."""
    token = create_access_token({"sub": settings.app_username, "role": "operator"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def rate_limits_off_by_default(monkeypatch):
    """Phase 10.5: the rate limiter would throttle the many /ask and /agent calls the rest of the suite
    makes as the same user. tests/test_rate_limit.py switches it back on for the tests that need it."""
    monkeypatch.setattr(settings, "rate_limit_ask_per_minute", 0)
    monkeypatch.setattr(settings, "rate_limit_agent_per_minute", 0)
    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 0)
    monkeypatch.setattr(settings, "rate_limit_login_per_hour", 0)


# ---------------------------------------------------------------------------
# Phase 11.1: no real network, a fake Gemini client and a fake database
# ---------------------------------------------------------------------------

class RealNetworkCallBlocked(RuntimeError):
    """Raised when a test that promised to stay offline tries to reach a real server.
    Not an OSError on purpose: httpx would map that to a transient ConnectError and retry it."""


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture
def no_network(monkeypatch):
    """
    Block every outbound socket connection except loopback, and every real Postgres connection
    (libpq opens its own sockets in C, so the socket guard alone would not catch it).

    App code swallows some errors on purpose (the agent loop, the rate limiter's fail-open, the
    best-effort n8n webhook), so a blocked call could go unnoticed. Each attempt is therefore also
    recorded in `.attempts`, and the test fails at teardown if there were any.
    """
    attempts: list[str] = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _blocked(what: str):
        attempts.append(what)
        raise RealNetworkCallBlocked(f"test tried a real network call: {what}")

    def _host(address) -> str:
        return str(address[0]) if isinstance(address, tuple) else str(address)

    def guarded_connect(sock, address):
        if sock.family == socket.AF_UNIX or _host(address) in _LOOPBACK:
            return real_connect(sock, address)
        _blocked(f"socket connect to {address!r}")

    def guarded_connect_ex(sock, address):
        if sock.family == socket.AF_UNIX or _host(address) in _LOOPBACK:
            return real_connect_ex(sock, address)
        _blocked(f"socket connect to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: _blocked("psycopg.connect (real Postgres)"))

    guard = SimpleNamespace(attempts=attempts)
    yield guard
    if guard.attempts:
        pytest.fail("Real network call(s) attempted in an offline test:\n  " + "\n  ".join(guard.attempts))


class FakeGemini:
    """
    Stands in for `genai.Client`: `client.models.embed_content(...)` and
    `client.models.generate_content(...)`, the only two calls the app makes.

    - Embeddings are deterministic: the same text always gives the same unit vector of
      `settings.embed_dim` floats, and different texts give different ones.
    - Replies to generate_content come from a queue filled with `reply(...)`, in call order. A str is
      returned as `.text`; a dict is JSON-encoded (the agent runs Gemini in JSON mode); an exception
      instance is raised; None mimics an empty MALFORMED_RESPONSE. When the queue is empty
      `default_reply` is used.
    - Every call is recorded in `embed_calls` / `chat_calls` (the keyword arguments as sent).
    """

    def __init__(self):
        self.models = self
        self.embed_calls: list[dict] = []
        self.chat_calls: list[dict] = []
        self.default_reply = "Fake Gemini answer."
        self._replies: list = []

    def reply(self, *replies) -> "FakeGemini":
        self._replies.extend(replies)
        return self

    @staticmethod
    def embedding_for(text: str) -> list[float]:
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [seed[i % len(seed)] - 127.5 + i % 7 for i in range(settings.embed_dim)]
        norm = math.sqrt(sum(x * x for x in raw))
        return [x / norm for x in raw]

    def embed_content(self, **kwargs):
        self.embed_calls.append(kwargs)
        return SimpleNamespace(embeddings=[SimpleNamespace(values=self.embedding_for(kwargs["contents"]))])

    def generate_content(self, **kwargs):
        self.chat_calls.append(kwargs)
        reply = self._replies.pop(0) if self._replies else self.default_reply
        if isinstance(reply, BaseException):
            raise reply
        if reply is None:
            return SimpleNamespace(text=None, candidates=[SimpleNamespace(finish_reason="MALFORMED_RESPONSE")])
        text = json.dumps(reply) if isinstance(reply, dict) else reply
        return SimpleNamespace(text=text, candidates=[SimpleNamespace(finish_reason="STOP")])


@pytest.fixture
def fake_gemini(monkeypatch, no_network):
    """
    A FakeGemini wired in at the root: `genai.Client` itself is replaced and `get_client()`'s cache
    cleared, so every module that calls `get_client()` (app/llm.py, app/agent.py, ...) gets the fake
    without having to be listed here. Pulls in `no_network`.
    """
    fake = FakeGemini()
    monkeypatch.setattr(llm.genai, "Client", lambda **kwargs: fake)
    llm.get_client.cache_clear()
    yield fake
    llm.get_client.cache_clear()  # don't leave the fake cached for a later test


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _FakeConnection:
    def __init__(self, fake_db):
        self._db = fake_db
        self.closed = False

    def execute(self, sql, params=None):
        return _FakeCursor(self._db._run(sql, params))

    def close(self):
        self.closed = True


def _squash(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().lower()


class FakeDB:
    """
    Stands in for Postgres at `psycopg.connect`. The app only ever does
    `conn.execute(sql, params).fetchone() / .fetchall()` with tuple rows, so that is all this supports.

    - `on(fragment, rows)` scripts a result: any statement containing `fragment` (case and whitespace
      ignored) returns `rows` — a list of tuples, or a callable taking the params and returning one.
      The most recently registered match wins, so a test can override an earlier script.
    - Unscripted statements succeed with no rows (fetchone() is None), like a write or an empty table.
    - `executed` holds every (sql, params) sent; `queries(fragment)` filters it.
    """

    def __init__(self):
        self.executed: list[tuple[str, object]] = []
        self.connections = 0
        self._scripts: list[tuple[str, object]] = []

    def on(self, fragment: str, rows) -> "FakeDB":
        self._scripts.append((_squash(fragment), rows))
        return self

    def queries(self, fragment: str = "") -> list[tuple[str, object]]:
        wanted = _squash(fragment)
        return [(sql, params) for sql, params in self.executed if wanted in _squash(sql)]

    def connect(self, *args, **kwargs) -> _FakeConnection:
        self.connections += 1
        return _FakeConnection(self)

    def _run(self, sql, params):
        self.executed.append((sql, params))
        squashed = _squash(sql)
        for fragment, rows in reversed(self._scripts):
            if fragment in squashed:
                return rows(params) if callable(rows) else rows
        return []


@pytest.fixture
def fake_db(monkeypatch, no_network):
    """
    A FakeDB behind every Postgres entry point: `get_conn()` (pgvector registration skipped) and the
    rate limiter's own connection. The limiter's cached connection is reset so a fake one can't leak
    into a later test. Pulls in `no_network`.
    """
    fake = FakeDB()
    monkeypatch.setattr(psycopg, "connect", fake.connect)
    monkeypatch.setattr(db, "register_vector", lambda conn: None)
    monkeypatch.setattr(ratelimit, "_conn", None)
    monkeypatch.setattr(ratelimit, "_table_ready", False)
    return fake
