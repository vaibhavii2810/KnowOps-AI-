"""
app/ratelimit.py  –  Phase 10.5
Per-user rate limiting for the expensive endpoints (D-036).

A sliding-window counter kept in Postgres rather than in process memory: the API runs as serverless
instances that restart often and run side by side, so an in-memory counter would reset on every cold
start and each instance would count separately — the real limit would be N times the configured one.
The database is already shared by every instance.

The count for a window is a weighted blend of the current fixed window's hits and the *previous* fixed
window's hits, weighted by how much of the previous window's 60s still "overlaps" the trailing 60s ending
now (D-078, bug #19, supersedes D-072's "recorded, not fixed"): a plain fixed-window counter resets hard at
each boundary, so up to 2x the limit could pass in a couple of real seconds by bursting at the end of one
window and the start of the next. Blending in the previous window's hits (weight 1 right at the boundary,
decaying linearly to 0 by the time a full window has passed) closes that gap at the cost of one extra,
cheap, primary-key read per check — no new log/timestamp storage, no change to the table shape.

Latency: the app's get_conn() costs ~1.2s per call against the remote Neon database (a plain connect is
~0.4s; the rest is pgvector type registration, which the limiter does not need), so the limiter keeps
one plain connection open per process and reuses it (~70ms per check), reconnecting once if it has gone
stale — serverless instances freeze and Neon drops idle connections.

Fail-open: this protects cost and quota, it is not an access control. If the counter cannot be read
or written (database blip, table not creatable) the request is allowed and a warning is logged, so a
limiter fault can never take /ask down by itself.
"""

from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import psycopg
from fastapi import Depends, HTTPException, Request, Response, status

from app.auth import get_current_user_required
from app.config import settings
from app.logs import log_event

WINDOW_SECONDS = 60

# bucket name -> name of the Settings field holding its per-minute limit (0 disables the bucket)
BUCKET_LIMIT_SETTING = {
    "ask": "rate_limit_ask_per_minute",
    "agent": "rate_limit_agent_per_minute",
}

CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS rate_limits (
        user_key     TEXT    NOT NULL,
        bucket       TEXT    NOT NULL,
        window_start BIGINT  NOT NULL,
        hits         INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_key, bucket, window_start)
    )
"""

_table_ready = False
_conn: Optional[psycopg.Connection] = None
_conn_lock = threading.Lock()


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int  # seconds until the current window ends


def _with_conn(fn: Callable[[psycopg.Connection], int]) -> int:
    """Run `fn` on the shared connection, reconnecting once if it has gone stale."""
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
                return fn(_conn)
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


def _upsert_hit(user_key: str, bucket: str, window_start: int, now: float) -> int:
    """Count one hit in `window_start`'s row and return its new total."""
    def _do(conn: psycopg.Connection) -> int:
        hits = conn.execute(
            """
            INSERT INTO rate_limits (user_key, bucket, window_start, hits)
            VALUES (%s, %s, %s, 1)
            ON CONFLICT (user_key, bucket, window_start)
            DO UPDATE SET hits = rate_limits.hits + 1
            RETURNING hits
            """,
            (user_key, bucket, window_start),
        ).fetchone()[0]
        if random.random() < 0.01:  # opportunistic cleanup of windows older than a day
            conn.execute("DELETE FROM rate_limits WHERE window_start < %s", (int(now) - 86400,))
        return hits

    return _with_conn(_do)


def _read_hits(user_key: str, bucket: str, window_start: int) -> int:
    """The hit count already recorded for `window_start`, or 0 if that window has no row yet (D-078: used
    to read the *previous* window's count for the sliding-window blend, without incrementing it)."""
    def _do(conn: psycopg.Connection) -> int:
        row = conn.execute(
            "SELECT hits FROM rate_limits WHERE user_key = %s AND bucket = %s AND window_start = %s",
            (user_key, bucket, window_start),
        ).fetchone()
        return row[0] if row else 0

    return _with_conn(_do)


def check_rate_limit(
    user_key: str,
    bucket: str,
    limit: int,
    now: Optional[float] = None,
    window_seconds: int = WINDOW_SECONDS,
) -> RateLimitResult:
    """
    Count one request for (user, bucket) and say whether it is allowed, using a sliding-window estimate
    (D-078): `previous_window_hits * weight + current_window_hits`, where `weight` is how much of the
    previous fixed window still falls within the trailing `window_seconds` ending now (1.0 right at the
    boundary, decaying linearly to 0.0 by the time a full window has passed). This is what actually fixes
    bug #19 — a plain fixed-window count lets a burst at the end of one window and the start of the next
    pass as if they were two independent, fully-fresh allowances.
    """
    now = time.time() if now is None else now
    window_start = int(now // window_seconds) * window_seconds
    previous_window_start = window_start - window_seconds
    # retry_after stays "time until this fixed window ends" — a simple, always-correct upper bound. The
    # sliding estimate can in practice allow a request again sooner, as the previous window's weight decays.
    retry_after = max(1, math.ceil(window_start + window_seconds - now))

    try:
        current_hits = _upsert_hit(user_key, bucket, window_start, now)
        previous_hits = _read_hits(user_key, bucket, previous_window_start)
    except Exception as exc:
        log_event("rate_limiter_unavailable", "warning", bucket=bucket, action="allowed (fail-open)",
                  error_type=type(exc).__name__, error=str(exc)[:120])
        return RateLimitResult(allowed=True, limit=limit, remaining=limit, retry_after=retry_after)

    weight = max(0.0, (window_seconds - (now - window_start)) / window_seconds)
    estimated = previous_hits * weight + current_hits

    return RateLimitResult(
        allowed=estimated <= limit,
        limit=limit,
        remaining=max(0, int(limit - estimated)),
        retry_after=retry_after,
    )


def client_ip(request: Request) -> str:
    """
    The caller's IP. On Vercel (`settings.vercel` set — the platform sets this automatically on every
    Preview/Production build, D-055) `x-forwarded-for` / `x-vercel-forwarded-for` / `x-real-ip` are
    overwritten by the platform itself, which does not forward client-supplied values, so they cannot be
    spoofed there. Off Vercel (a local run, another host) these headers are not trusted at all — a client
    could send any value itself and rotate it to defeat the per-IP limit — so the real TCP peer address is
    used instead (D-061). A deployment behind some other trusted proxy would need its own signal here; none
    exists today.
    """
    if settings.vercel:
        for header in ("x-vercel-forwarded-for", "x-forwarded-for", "x-real-ip"):
            value = request.headers.get(header)
            if value:
                return value.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


# (bucket, Settings field, window seconds): a short window against bursts, an hourly cap against slow guessing
LOGIN_LIMITS = (
    ("login", "rate_limit_login_per_minute", 60),
    ("login-hourly", "rate_limit_login_per_hour", 3600),
)


def login_rate_limited(request: Request) -> None:
    """
    FastAPI dependency for POST /auth/login (Phase 10.5 follow-up, D-037). Counts every attempt per client IP —
    right or wrong, and before the credentials are checked, so a blocked caller learns nothing about whether
    a guess was correct. There is no per-username lockout on purpose: with a single operator it would let an
    attacker lock the real user out by sending bad logins.
    """
    ip = client_ip(request)
    for bucket, setting_name, window in LOGIN_LIMITS:
        limit = int(getattr(settings, setting_name))
        if limit <= 0:
            continue
        result = check_rate_limit(ip, bucket, limit, window_seconds=window)
        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many login attempts. Try again in {result.retry_after} seconds.",
                headers={"Retry-After": str(result.retry_after)},
            )


def rate_limited(bucket: str) -> Callable[..., dict]:
    """
    FastAPI dependency: authenticate (401 comes first), then count the request against the caller's
    `bucket`. Over the limit -> 429 with a Retry-After header. Returns the JWT payload, so it is a
    drop-in replacement for Depends(get_current_user_required).
    """
    setting_name = BUCKET_LIMIT_SETTING[bucket]

    def dependency(
        response: Response,
        user: dict = Depends(get_current_user_required),
    ) -> dict:
        limit = int(getattr(settings, setting_name))
        if limit <= 0:  # 0 disables this bucket
            return user

        result = check_rate_limit(str(user.get("sub", "unknown")), bucket, limit)
        headers = {
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": str(result.remaining),
        }
        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Rate limit exceeded: {result.limit} requests per minute for this endpoint. "
                    f"Try again in {result.retry_after} seconds."
                ),
                headers={**headers, "Retry-After": str(result.retry_after)},
            )
        response.headers.update(headers)
        return user

    return dependency
