"""
tests/test_metrics.py  –  Phase 12.4 (D-046)
GET /metrics: request count, average latency and error rate, counted in Postgres by RequestMetricsMiddleware.
Offline: Gemini and Postgres are fakes (memory_db). The SQL itself is not parsed by memory_db, so it was also
run once against the real database (see the Phase 12.4 notes in AGENTS.md).
"""

import json
from types import SimpleNamespace

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import metrics
from app.config import settings
from app.main import app
from app.metrics import HOUR_SECONDS, read_metrics, record_request

NOW = 1_800_000_000 - (1_800_000_000 % HOUR_SECONDS) + 1800  # 30 minutes into an hour


@pytest.fixture
def counting(memory_db, monkeypatch):
    """Request counting on, backed by memory_db (it is off by default in every test)."""
    monkeypatch.setattr(settings, "metrics_enabled", True)
    return memory_db


@pytest.fixture
def client(counting):
    return TestClient(app, raise_server_exceptions=False)


def counted(memory_db):
    """{(method, route): (requests, server_errors, client_errors)} summed over hours."""
    out = {}
    for (_, method, route), row in memory_db.request_metrics.items():
        total = out.setdefault((method, route), [0, 0, 0])
        total[0] += row[0]
        total[1] += row[1]
        total[2] += row[2]
    return {key: tuple(value) for key, value in out.items()}


# --- what gets counted ---------------------------------------------------------------------------

def test_api_requests_are_counted_under_their_route_template(client, auth_headers, counting):
    client.get("/tickets/stats", headers=auth_headers)
    client.get("/tickets/123", headers=auth_headers)
    client.get("/tickets/456", headers=auth_headers)
    client.get("/health")

    assert counted(counting) == {
        ("GET", "/tickets/stats"): (1, 0, 0),
        ("GET", "/tickets/{ticket_id}"): (2, 0, 2),   # two different ids, one row; both 404
        ("GET", "/health"): (1, 0, 0),
    }


def test_unknown_urls_share_one_label_so_hostile_paths_cannot_grow_the_table(client, counting):
    for path in ("/wp-admin", "/.env", "/a/b/c", "/%00", "/x" * 40):
        client.get(path)

    assert counted(counting) == {("GET", "(unmatched)"): (5, 0, 5)}
    assert len(counting.request_metrics) == 1


def test_status_classes_are_split_into_server_and_client_errors(client, auth_headers, counting, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "get_crm_stats", lambda: (_ for _ in ()).throw(ZeroDivisionError("boom")))

    client.get("/tickets/stats", headers=auth_headers)    # 500
    client.get("/tickets/stats")                           # 401
    client.get("/tickets/stats?limit=1", headers=auth_headers)   # 500 again (extra params are ignored)
    client.post("/health")                                 # 405: matched route, wrong method

    assert counted(counting) == {
        ("GET", "/tickets/stats"): (3, 2, 1),
        ("POST", "/health"): (1, 0, 1),
    }


@pytest.mark.parametrize("method,path", [
    ("GET", "/"),                      # the web console
    ("GET", "/static/js/app.js"),
    ("GET", "/docs"),
    ("GET", "/redoc"),
    ("GET", "/openapi.json"),
    ("OPTIONS", "/ask"),               # CORS preflight
])
def test_the_console_static_files_docs_and_preflights_are_not_counted(client, counting, method, path):
    client.request(method, path, headers={"Origin": "http://localhost", "Access-Control-Request-Method": "POST"})
    assert counting.request_metrics == {}


def test_reading_the_metrics_does_not_change_them(client, auth_headers, counting):
    client.get("/health")
    for _ in range(3):
        assert client.get("/metrics", headers=auth_headers).status_code == 200
    assert counted(counting) == {("GET", "/health"): (1, 0, 0)}


def test_nothing_is_counted_when_metrics_are_disabled(client, auth_headers, counting, monkeypatch):
    monkeypatch.setattr(settings, "metrics_enabled", False)
    client.get("/health")
    assert counting.request_metrics == {} and not counting.queries("request_metrics")


# --- the numbers -----------------------------------------------------------------------------------

def test_totals_averages_and_error_rate_are_exact(counting):
    record_request("GET", "/ask", 200, 100.0, now=NOW)
    record_request("GET", "/ask", 200, 300.0, now=NOW)
    record_request("GET", "/ask", 503, 200.0, now=NOW)
    record_request("GET", "/ask", 401, 0.0, now=NOW)
    record_request("GET", "/health", 200, 50.0, now=NOW)

    result = read_metrics(24, now=NOW)

    assert (result["requests"], result["server_errors"], result["client_errors"]) == (5, 1, 1)
    assert result["avg_latency_ms"] == 130.0          # (100 + 300 + 200 + 0 + 50) / 5
    assert result["max_latency_ms"] == 300.0
    assert result["error_rate"] == 0.2                 # 1 server error of 5
    ask, health = result["routes"]                     # busiest first
    assert (ask["route"], ask["requests"], ask["avg_latency_ms"], ask["max_latency_ms"]) == ("/ask", 4, 150.0, 300.0)
    assert (ask["server_errors"], ask["client_errors"], ask["error_rate"]) == (1, 1, 0.25)
    assert (health["route"], health["requests"], health["error_rate"]) == ("/health", 1, 0.0)


def test_an_empty_window_is_all_zeros_not_a_division_error(counting):
    assert read_metrics(24, now=NOW) == {
        "window_hours": 24, "since": read_metrics(24, now=NOW)["since"], "requests": 0, "avg_latency_ms": 0.0,
        "max_latency_ms": 0.0, "server_errors": 0, "client_errors": 0, "error_rate": 0.0, "routes": [],
    }


def test_the_window_is_the_current_hour_plus_the_hours_before_it(counting):
    record_request("GET", "/health", 200, 10.0, now=NOW)                          # this hour
    record_request("GET", "/health", 200, 10.0, now=NOW - 1 * HOUR_SECONDS)       # 1 hour ago
    record_request("GET", "/health", 200, 10.0, now=NOW - 5 * HOUR_SECONDS)       # 5 hours ago

    assert read_metrics(1, now=NOW)["requests"] == 1
    assert read_metrics(2, now=NOW)["requests"] == 2
    assert read_metrics(5, now=NOW)["requests"] == 2
    assert read_metrics(6, now=NOW)["requests"] == 3
    assert read_metrics(1, now=NOW)["since"] == "2027-01-15T08:00:00+00:00"


def test_old_hours_are_pruned_now_and_then(counting, monkeypatch):
    record_request("GET", "/health", 200, 10.0, now=NOW - 40 * 86400)
    monkeypatch.setattr(metrics.random, "random", lambda: 0.0)   # always take the 1% cleanup branch
    record_request("GET", "/health", 200, 10.0, now=NOW)

    assert [key[0] for key in counting.request_metrics] == [NOW - NOW % HOUR_SECONDS]


# --- the endpoint ------------------------------------------------------------------------------------

def test_the_endpoint_reports_what_the_middleware_counted(client, auth_headers, counting):
    client.get("/health")
    client.get("/tickets/stats")                                     # 401: no token

    response = client.get("/metrics", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["window_hours"], body["requests"], body["client_errors"], body["server_errors"]) == (24, 2, 1, 0)
    assert {(r["method"], r["route"]) for r in body["routes"]} == {("GET", "/health"), ("GET", "/tickets/stats")}
    assert response.headers["x-request-id"]


def test_the_endpoint_needs_a_token(client):
    assert client.get("/metrics").status_code == 401


@pytest.mark.parametrize("hours,expected", [(0, 422), (169, 422), (-1, 422), ("abc", 422), (1, 200), (168, 200)])
def test_the_window_is_bounded(client, auth_headers, hours, expected):
    assert client.get(f"/metrics?hours={hours}", headers=auth_headers).status_code == expected


def test_a_missing_table_is_created_and_reads_as_empty(client, auth_headers, counting):
    counting.request_metrics.clear()
    response = client.get("/metrics", headers=auth_headers)
    assert response.status_code == 200 and response.json()["requests"] == 0
    assert counting.queries("CREATE TABLE IF NOT EXISTS request_metrics")


def test_the_endpoint_reports_an_outage_instead_of_empty_numbers(client, auth_headers, counting, monkeypatch):
    def down(*args, **kwargs):
        raise psycopg.OperationalError("database unreachable")
    monkeypatch.setattr(metrics, "psycopg", SimpleNamespace(connect=down, OperationalError=psycopg.OperationalError))
    monkeypatch.setattr(metrics, "_conn", None)

    response = client.get("/metrics", headers=auth_headers)

    assert response.status_code == 503
    assert response.json()["detail"] == "Metrics are unavailable — the database could not be read."


# --- failing safe ---------------------------------------------------------------------------------------

def test_a_counter_fault_never_breaks_the_request_and_is_logged(client, auth_headers, counting, monkeypatch, capsys):
    def down(*args, **kwargs):
        raise psycopg.OperationalError("database unreachable")
    monkeypatch.setattr(metrics, "psycopg", SimpleNamespace(connect=down, OperationalError=psycopg.OperationalError))
    monkeypatch.setattr(metrics, "_conn", None)

    response = client.get("/tickets/stats", headers=auth_headers)

    assert response.status_code == 200
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    warning = next(e for e in events if e["event"] == "metrics_unavailable")
    assert warning["level"] == "warning" and warning["error_type"] == "OperationalError"
    assert warning["request_id_of_request"] == response.headers["x-request-id"]   # findable from the request's id


def test_the_shared_connection_is_reused_and_reopened_once_if_stale(counting, monkeypatch):
    connects = []
    real = psycopg.connect

    def counting_connect(*args, **kwargs):
        connects.append(1)
        return real(*args, **kwargs)
    monkeypatch.setattr(metrics, "psycopg", SimpleNamespace(connect=counting_connect, OperationalError=psycopg.OperationalError))
    monkeypatch.setattr(metrics, "_conn", None)

    for _ in range(4):
        record_request("GET", "/health", 200, 1.0, now=NOW)
    assert len(connects) == 1

    class Stale:
        closed = False
        def execute(self, *a, **kw):
            raise psycopg.OperationalError("server closed the connection unexpectedly")
        def close(self):
            pass
    metrics._conn = Stale()
    record_request("GET", "/health", 200, 1.0, now=NOW)
    assert len(connects) == 2 and counted(counting)[("GET", "/health")][0] == 5
