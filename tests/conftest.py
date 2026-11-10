# Pytest test configuration and fixtures (built in Phase 4; Gemini/DB fakes added in Phase 11.1, D-038)

import hashlib
import itertools
import json
import math
import re
import socket
from datetime import datetime, timezone
from types import SimpleNamespace

import psycopg
import pytest

from app import db, llm, metrics, ratelimit
from app.auth import create_access_token
from app.config import settings
from scripts import ingest


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


@pytest.fixture(autouse=True)
def metrics_off_by_default(monkeypatch):
    """Phase 12.4: request counting would send a database write after every request in every test, including
    the ones that use no database fixture (and so would reach whatever DATABASE_URL .env holds). tests/test_metrics.py
    switches it back on, always together with memory_db."""
    monkeypatch.setattr(settings, "metrics_enabled", False)


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
    monkeypatch.setattr(ingest, "EMBED_SLEEP_SECONDS", 0)  # free-tier pacing; pointless against a fake
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
    monkeypatch.setattr(metrics, "_conn", None)
    monkeypatch.setattr(metrics, "_table_ready", False)
    return fake


# ---------------------------------------------------------------------------
# Phase 11.4: an in-memory stand-in for the app's tables
# ---------------------------------------------------------------------------

_PRIORITY_RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


class MemoryDB:
    """
    The app's tables kept in Python, answering exactly the statements the app sends (tickets,
    conversations, messages, documents, chunks — including the pgvector search — and rate_limits).
    State carries across statements, so create → fetch → update round trips behave like Postgres.

    It does not parse SQL: each statement is recognised by a fragment, as FakeDB does. A statement it
    does not recognise is recorded in `unknown` and fails the test at teardown, so a new query in the
    app can't silently get "no rows". The `live` variant of `db_backend` runs the same tests against
    real Postgres, which is what catches this fake drifting from the real thing.
    """

    def __init__(self, fake_db: FakeDB):
        self._db = fake_db
        self.tickets: dict[int, list] = {}
        self.conversations: dict[int, datetime] = {}
        self.messages: list[tuple] = []          # (id, conversation_id, role, content, created_at)
        self.documents: dict[int, dict] = {}     # id -> {"source", "title", "content_hash"}
        self.chunks: list[dict] = []             # {"id", "document_id", "chunk_index", "heading", "content", "embedding"}
        self.rate_limits: dict[tuple, int] | None = {}  # (user_key, bucket, window_start) -> hits; None = dropped
        # (hour_start, method, route) -> [requests, server_errors, client_errors, latency_sum, latency_max]
        self.request_metrics: dict[tuple, list] = {}
        self.unknown: list[str] = []
        self._ids = {table: itertools.count(1) for table in ("tickets", "conversations", "messages", "documents", "chunks")}
        self._install()

    def queries(self, fragment: str = "") -> list[tuple[str, object]]:
        """Every statement sent so far that contains `fragment` (see FakeDB.queries)."""
        return self._db.queries(fragment)

    # -- statements ---------------------------------------------------------
    def _install(self):
        on = self._db.on
        on("", self._unrecognised)  # lowest precedence: FakeDB tries later registrations first

        # tickets (app/crm.py)
        on("INSERT INTO tickets", self._insert_ticket)
        on("FROM tickets WHERE id = %s", lambda p: self._ticket_rows([p[0]]))
        on("FROM tickets ORDER BY CASE priority", lambda p: self._list_tickets(None, None, p[0]))
        on("FROM tickets WHERE status = %s ORDER BY", lambda p: self._list_tickets(p[0], None, p[1]))
        on("FROM tickets WHERE priority = %s ORDER BY", lambda p: self._list_tickets(None, p[0], p[1]))
        on("FROM tickets WHERE status = %s AND priority = %s ORDER BY", lambda p: self._list_tickets(p[0], p[1], p[2]))
        on("UPDATE tickets SET status = %s, updated_at = %s WHERE id = %s",
           lambda p: self._update_ticket(p[2], p[0], p[1], None))
        on("UPDATE tickets SET status = %s, resolution_notes = %s, updated_at = %s WHERE id = %s",
           lambda p: self._update_ticket(p[3], p[0], p[2], p[1]))
        on("SELECT COUNT(*) FROM tickets", lambda p: [(len(self.tickets),)])
        for status in ("open", "in_progress", "resolved"):
            on(f"SELECT COUNT(*) FROM tickets WHERE status = '{status}'",
               lambda p, status=status: [(sum(t[4] == status for t in self.tickets.values()),)])
        on("SELECT COUNT(*) FROM tickets WHERE priority = 'P1' AND status IN ('open', 'in_progress')",
           lambda p: [(sum(t[3] == "P1" and t[4] in ("open", "in_progress") for t in self.tickets.values()),)])


        # conversations and messages (app/main.py)
        on("INSERT INTO conversations DEFAULT VALUES", self._insert_conversation)
        on("SELECT id FROM conversations WHERE id = %s",
           lambda p: [(p[0],)] if p[0] in self.conversations else [])
        on("SELECT id, created_at FROM conversations WHERE id = %s",
           lambda p: [(p[0], self.conversations[p[0]])] if p[0] in self.conversations else [])
        on("FROM conversations c LEFT JOIN messages m", self._list_conversations)
        on("INSERT INTO messages", self._insert_messages)
        on("SELECT role, content FROM messages WHERE conversation_id = %s",
           lambda p: [(m[2], m[3]) for m in self._messages_of(p[0])][:8])  # ORDER BY id ASC LIMIT 8
        on("SELECT id, role, content, created_at FROM messages WHERE conversation_id = %s",
           lambda p: [(m[0], m[2], m[3], m[4]) for m in self._messages_of(p[0])])

        # knowledge base (scripts/ingest.py, app/rag.py, /health, the agent's DB diagnostic)
        on("SELECT 1", lambda p: [(1,)])
        on("SELECT COUNT(*) FROM documents", lambda p: [(len(self.documents),)])
        on("SELECT COUNT(*) FROM chunks", lambda p: [(len(self.chunks),)])
        on("SELECT id FROM documents WHERE source = %s", lambda p: [(i,) for i in self._docs_by_source(p[0])])
        on("SELECT id, content_hash FROM documents WHERE source = %s",
           lambda p: [(i, self.documents[i]["content_hash"]) for i in self._docs_by_source(p[0])])
        on("INSERT INTO documents (source, title, content_hash)", self._insert_document)
        on("UPDATE documents SET title = %s, content_hash = %s WHERE id = %s", self._update_document)
        on("DELETE FROM documents", lambda p: self._delete_documents(list(self.documents)))
        on("DELETE FROM documents WHERE source = %s", lambda p: self._delete_documents(self._docs_by_source(p[0])))
        on("DELETE FROM chunks", lambda p: self.chunks.clear() or [])
        on("DELETE FROM chunks WHERE document_id = %s", lambda p: self._delete_chunks_of([p[0]]))
        on("INSERT INTO chunks (document_id, chunk_index, heading, content, embedding)", self._insert_chunk)
        on("FROM chunks c JOIN documents d", self._vector_search)

        # rate limiter (app/ratelimit.py)
        on("CREATE TABLE IF NOT EXISTS rate_limits", self._create_rate_limits)
        on("DROP TABLE IF EXISTS rate_limits", lambda p: setattr(self, "rate_limits", None) or [])
        on("INSERT INTO rate_limits", self._hit_rate_limit)
        on("DELETE FROM rate_limits WHERE window_start < %s", self._prune_rate_limits)
        on("DELETE FROM rate_limits WHERE user_key LIKE 'rltest-%'", self._delete_test_rate_limits)
        on("SELECT hits FROM rate_limits WHERE user_key = %s",
           lambda p: [(hits,) for (user, _, _), hits in (self.rate_limits or {}).items() if user == p[0]])

        # request counters (app/metrics.py)
        on("CREATE TABLE IF NOT EXISTS request_metrics", lambda p: [])
        on("INSERT INTO request_metrics", self._count_request)
        on("DELETE FROM request_metrics WHERE hour_start < %s", self._prune_request_metrics)
        on("FROM request_metrics WHERE hour_start >= %s GROUP BY method, route", self._summarise_request_metrics)

    def _unrecognised(self, params):
        sql = " ".join(self._db.executed[-1][0].split())  # FakeDB records the statement before calling us
        self.unknown.append(sql)
        return []

    # -- tickets --------------------------------------------------------------
    def _ticket_rows(self, ids):
        return [tuple(self.tickets[i]) for i in ids if i in self.tickets]

    def _insert_ticket(self, p):
        subject, description, priority, status, created_at, updated_at = p
        ticket_id = next(self._ids["tickets"])
        self.tickets[ticket_id] = [ticket_id, subject, description, priority, status, created_at, updated_at, None]
        return self._ticket_rows([ticket_id])

    def _list_tickets(self, status, priority, limit):
        rows = [t for t in self.tickets.values()
                if (status is None or t[4] == status) and (priority is None or t[3] == priority)]
        rows.sort(key=lambda t: (_PRIORITY_RANK.get(t[3], 5), -t[0]))
        return [tuple(t) for t in rows[:limit]]

    def _update_ticket(self, ticket_id, status, updated_at, notes):
        ticket = self.tickets.get(ticket_id)
        if ticket is None:
            return []
        ticket[4], ticket[6] = status, updated_at
        if notes is not None:
            ticket[7] = notes
        return self._ticket_rows([ticket_id])

    # -- conversations and messages ----------------------------------------
    def _insert_conversation(self, p):
        conversation_id = next(self._ids["conversations"])
        self.conversations[conversation_id] = datetime.now(timezone.utc)
        return [(conversation_id, self.conversations[conversation_id])]

    def _list_conversations(self, p):
        rows = [(cid, created, sum(m[1] == cid for m in self.messages))
                for cid, created in self.conversations.items()]
        return sorted(rows, key=lambda r: -r[0])[:p[0]]

    def _insert_messages(self, p):
        # /ask's INSERT carries the roles as literals: VALUES (%s, 'user', %s), (%s, 'model', %s)
        for (conversation_id, content), role in zip(zip(p[0::2], p[1::2]), itertools.cycle(("user", "model"))):
            self.messages.append((next(self._ids["messages"]), conversation_id, role, content, datetime.now(timezone.utc)))
        return []

    def _messages_of(self, conversation_id):
        return sorted((m for m in self.messages if m[1] == conversation_id), key=lambda m: m[0])

    # -- knowledge base -------------------------------------------------------
    def _docs_by_source(self, source):
        return [i for i, d in self.documents.items() if d["source"] == source]

    def _insert_document(self, p):
        source, title, content_hash = p
        if self._docs_by_source(source):
            raise psycopg.errors.UniqueViolation("duplicate key value violates unique constraint \"documents_source_key\"")
        document_id = next(self._ids["documents"])
        self.documents[document_id] = {"source": source, "title": title, "content_hash": content_hash}
        return [(document_id,)]

    def _update_document(self, p):
        title, content_hash, document_id = p
        if document_id in self.documents:
            self.documents[document_id].update(title=title, content_hash=content_hash)
        return []

    def _delete_chunks_of(self, document_ids):
        self.chunks = [c for c in self.chunks if c["document_id"] not in document_ids]
        return []

    def _delete_documents(self, document_ids):
        for document_id in document_ids:
            self.documents.pop(document_id, None)
        return self._delete_chunks_of(document_ids)  # ON DELETE CASCADE

    def _insert_chunk(self, p):
        document_id, chunk_index, heading, content, embedding = p
        self.chunks.append({"id": next(self._ids["chunks"]), "document_id": document_id, "chunk_index": chunk_index,
                            "heading": heading, "content": content, "embedding": [float(x) for x in embedding]})
        return []

    def _vector_search(self, p):
        """retrieve()'s query: similarity = 1 - cosine distance, filtered by threshold, best first, LIMIT top_k."""
        query_literal, _, threshold, _, top_k = p
        query = [float(x) for x in query_literal.strip("[]").split(",")]
        query_norm = math.sqrt(sum(x * x for x in query))
        scored = []
        for chunk in self.chunks:
            norm = math.sqrt(sum(x * x for x in chunk["embedding"])) * query_norm
            similarity = sum(a * b for a, b in zip(query, chunk["embedding"])) / norm if norm else 0.0
            if similarity >= threshold:
                document = self.documents[chunk["document_id"]]
                scored.append((round(similarity, 6), chunk, document))
        scored.sort(key=lambda s: -s[0])
        return [(c["id"], d["title"], d["source"], c["heading"] or "", c["content"], sim) for sim, c, d in scored[:top_k]]

    # -- rate limiter ---------------------------------------------------------
    def _create_rate_limits(self, p):
        if self.rate_limits is None:
            self.rate_limits = {}
        return []

    def _hit_rate_limit(self, p):
        if self.rate_limits is None:
            raise psycopg.errors.UndefinedTable('relation "rate_limits" does not exist')
        key = tuple(p)  # (user_key, bucket, window_start); ON CONFLICT ... hits = hits + 1 RETURNING hits
        self.rate_limits[key] = self.rate_limits.get(key, 0) + 1
        return [(self.rate_limits[key],)]

    def _prune_rate_limits(self, p):
        if self.rate_limits:
            self.rate_limits = {k: v for k, v in self.rate_limits.items() if k[2] >= p[0]}
        return []

    def _count_request(self, p):
        hour_start, method, route, server_error, client_error, latency, _ = p
        row = self.request_metrics.setdefault((hour_start, method, route), [0, 0, 0, 0.0, 0.0])
        row[0] += 1
        row[1] += server_error
        row[2] += client_error
        row[3] += latency
        row[4] = max(row[4], latency)
        return []

    def _prune_request_metrics(self, p):
        self.request_metrics = {k: v for k, v in self.request_metrics.items() if k[0] >= p[0]}
        return []

    def _summarise_request_metrics(self, p):
        """SUM/MAX per (method, route) over hours >= p[0], busiest first — the same shape SUMMARY_SQL returns."""
        grouped: dict[tuple, list] = {}
        for (hour_start, method, route), row in self.request_metrics.items():
            if hour_start >= p[0]:
                total = grouped.setdefault((method, route), [0, 0, 0, 0.0, 0.0])
                total[0] += row[0]
                total[1] += row[1]
                total[2] += row[2]
                total[3] += row[3]
                total[4] = max(total[4], row[4])
        ordered = sorted(grouped.items(), key=lambda item: (-item[1][0], item[0][1], item[0][0]))
        return [(method, route, *totals) for (method, route), totals in ordered]

    def _delete_test_rate_limits(self, p):
        if self.rate_limits:
            self.rate_limits = {k: v for k, v in self.rate_limits.items() if not k[0].startswith("rltest-")}
        return []


@pytest.fixture
def memory_db(fake_db):
    """The app's tables in memory (MemoryDB), behind fake_db — so offline, via no_network."""
    store = MemoryDB(fake_db)
    yield store
    if store.unknown:
        pytest.fail("MemoryDB does not understand these statements (add them to MemoryDB._install):\n  "
                    + "\n  ".join(store.unknown))


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.live)])
def db_backend(request):
    """
    Run a database-dependent test twice: on MemoryDB by default, and against the real Postgres from
    .env as a `live` variant (`pytest -m live`). Same test body both times, so the live run is what
    shows MemoryDB still behaves like Postgres.
    """
    if request.param == "memory":
        return request.getfixturevalue("memory_db")
    return None
