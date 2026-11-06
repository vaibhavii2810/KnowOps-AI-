"""
app/metrics.py  –  Phase 12.4 (stretch)
GET /metrics: request count, average latency and error rate (D-046).

Counters are hourly rows in Postgres, one per (hour, method, route), not process memory: the API runs as
serverless instances that restart often and run side by side, so in-memory counters would reset on every cold
start and each instance would count only its own traffic (the same reasoning as the rate limiter, D-036).

RequestMetricsMiddleware counts every API request after its response is done; routes are labelled with their
template (`/tickets/{ticket_id}`, never the raw URL) so hostile URLs cannot create unlimited rows, and unknown
URLs share one `(unmatched)` label. Like the rate limiter it keeps one plain connection open per process and
fails open: if the counter cannot be written, the request still succeeds and a warning is logged.

Only sums and a maximum are stored, so averages and error rates are exact but percentiles (p95) are not available.
"""

from __future__ import annotations

import random
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import psycopg
from fastapi.concurrency import run_in_threadpool
from fastapi.routing import APIRoute

from app.config import settings
from app.logs import log_event

HOUR_SECONDS = 3600
RETENTION_DAYS = 30
UNMATCHED = "(unmatched)"
NOT_COUNTED = frozenset({"/metrics", "/"})  # reading the metrics must not change them; "/" is the web console

CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS request_metrics (
        hour_start     BIGINT           NOT NULL,
        method         TEXT             NOT NULL,
        route          TEXT             NOT NULL,
        requests       INTEGER          NOT NULL DEFAULT 0,
        server_errors  INTEGER          NOT NULL DEFAULT 0,
        client_errors  INTEGER          NOT NULL DEFAULT 0,
        latency_ms_sum DOUBLE PRECISION NOT NULL DEFAULT 0,
        latency_ms_max DOUBLE PRECISION NOT NULL DEFAULT 0,
        PRIMARY KEY (hour_start, method, route)
    )
"""

UPSERT_SQL = """
    INSERT INTO request_metrics
        (hour_start, method, route, requests, server_errors, client_errors, latency_ms_sum, latency_ms_max)
    VALUES (%s, %s, %s, 1, %s, %s, %s, %s)
    ON CONFLICT (hour_start, method, route) DO UPDATE SET
        requests       = request_metrics.requests + 1,
        server_errors  = request_metrics.server_errors + EXCLUDED.server_errors,
        client_errors  = request_metrics.client_errors + EXCLUDED.client_errors,
        latency_ms_sum = request_metrics.latency_ms_sum + EXCLUDED.latency_ms_sum,
        latency_ms_max = GREATEST(request_metrics.latency_ms_max, EXCLUDED.latency_ms_max)
"""

SUMMARY_SQL = """
    SELECT method, route, SUM(requests), SUM(server_errors), SUM(client_errors),
           SUM(latency_ms_sum), MAX(latency_ms_max)
    FROM request_metrics
    WHERE hour_start >= %s
    GROUP BY method, route
    ORDER BY SUM(requests) DESC, route, method
"""

_table_ready = False
_conn: Optional[psycopg.Connection] = None
_conn_lock = threading.Lock()


def _with_connection(work: Callable[[psycopg.Connection], Any]) -> Any:
    """Run `work(conn)` on the shared connection, creating the table on first use and reconnecting once if stale."""
    global _conn, _table_ready
    with _conn_lock:
        for attempt in (1, 2):
            try:
                if _conn is None or _conn.closed:
                    _conn = psycopg.connect(settings.database_url, autocommit=True, connect_timeout=5)
                    _table_ready = False
                if not _table_ready:
                    # first use on this connection: create the table, so production needs no manual migration
                    _conn.execute(CREATE_TABLE_SQL)
                    _table_ready = True
                return work(_conn)
            except psycopg.OperationalError:
                try:
                    if _conn is not None:
                        _conn.close()
                except Exception:
                    pass
                _conn = None
                if attempt == 2:
                    raise
    raise AssertionError("unreachable")  # pragma: no cover


def _hour_start(now: float) -> int:
    return int(now // HOUR_SECONDS) * HOUR_SECONDS


def record_request(
    method: str,
    route: str,
    status: int,
    latency_ms: float,
    now: Optional[float] = None,
    request_id: Optional[str] = None,
) -> None:
    """Count one finished request. Never raises: a counter fault must not break the request it describes."""
    now = time.time() if now is None else now
    latency_ms = round(latency_ms, 1)
    params = (_hour_start(now), method, route, int(status >= 500), int(400 <= status < 500), latency_ms, latency_ms)

    def work(conn: psycopg.Connection) -> None:
        conn.execute(UPSERT_SQL, params)
        if random.random() < 0.01:  # opportunistic cleanup of hours older than the retention window
            conn.execute("DELETE FROM request_metrics WHERE hour_start < %s", (_hour_start(now) - RETENTION_DAYS * 86400,))

    try:
        _with_connection(work)
    except Exception as exc:
        fields = {"action": "request not counted", "error_type": type(exc).__name__, "error": str(exc)[:120]}
        if request_id:
            fields["request_id_of_request"] = request_id  # the middleware runs after the request context has closed
        log_event("metrics_unavailable", "warning", **fields)


def route_label(scope: dict) -> Optional[str]:
    """
    What to count this request under, or None to not count it.
    API routes use their template; static files, /docs, /redoc and /openapi.json (which have an endpoint but no
    API route) and CORS preflights are not counted; any other URL is "(unmatched)".
    """
    route = scope.get("route")
    if isinstance(route, APIRoute):
        return None if route.path in NOT_COUNTED else route.path
    if "endpoint" in scope or scope.get("method") == "OPTIONS":
        return None
    return UNMATCHED


def _ratio(numerator: float, denominator: float, digits: int = 1) -> float:
    return round(numerator / denominator, digits) if denominator else 0.0


def read_metrics(hours: int, now: Optional[float] = None) -> dict:
    """
    Totals and a per-route breakdown for the last `hours` hourly buckets (the current, partly-elapsed hour
    plus the `hours - 1` before it). Raises if the database cannot be read: unlike recording, reading must
    report an outage.
    """
    now = time.time() if now is None else now
    since = _hour_start(now) - (hours - 1) * HOUR_SECONDS
    rows = _with_connection(lambda conn: conn.execute(SUMMARY_SQL, (since,)).fetchall())

    routes = []
    totals = {"requests": 0, "server_errors": 0, "client_errors": 0, "latency_sum": 0.0, "latency_max": 0.0}
    for method, route, requests, server_errors, client_errors, latency_sum, latency_max in rows:
        requests, server_errors, client_errors = int(requests), int(server_errors), int(client_errors)
        routes.append({
            "method": method,
            "route": route,
            "requests": requests,
            "avg_latency_ms": _ratio(latency_sum, requests),
            "max_latency_ms": round(float(latency_max), 1),
            "server_errors": server_errors,
            "client_errors": client_errors,
            "error_rate": _ratio(server_errors, requests, 4),
        })
        totals["requests"] += requests
        totals["server_errors"] += server_errors
        totals["client_errors"] += client_errors
        totals["latency_sum"] += float(latency_sum)
        totals["latency_max"] = max(totals["latency_max"], float(latency_max))

    return {
        "window_hours": hours,
        "since": datetime.fromtimestamp(since, tz=timezone.utc).isoformat(timespec="seconds"),
        "requests": totals["requests"],
        "avg_latency_ms": _ratio(totals["latency_sum"], totals["requests"]),
        "max_latency_ms": round(totals["latency_max"], 1),
        "server_errors": totals["server_errors"],
        "client_errors": totals["client_errors"],
        "error_rate": _ratio(totals["server_errors"], totals["requests"], 4),
        "routes": routes,
    }


class RequestMetricsMiddleware:
    """
    Pure ASGI middleware, added after RequestLogMiddleware so it is the outermost: its latency covers the whole
    stack, and its own database write happens after the log line is written, so neither the logged latency nor
    the counted latency includes the cost of counting.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not settings.metrics_enabled:
            return await self.app(scope, receive, send)

        started = time.perf_counter()
        seen: dict[str, Any] = {"status": None, "request_id": None}

        async def send_and_note(message):
            if message["type"] == "http.response.start":
                seen["status"] = message["status"]
                for name, value in message.get("headers", []):
                    if name == b"x-request-id":
                        seen["request_id"] = value.decode("latin-1")
            await send(message)

        try:
            await self.app(scope, receive, send_and_note)
        finally:
            latency_ms = (time.perf_counter() - started) * 1000
            route = route_label(scope)
            if route is not None:
                status = seen["status"] if seen["status"] is not None else 500  # died before responding
                await run_in_threadpool(record_request, scope["method"], route, status, latency_ms,
                                        None, seen["request_id"])
