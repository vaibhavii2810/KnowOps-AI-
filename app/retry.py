"""
app/retry.py  –  Phase 10.1
Shared retry/backoff for transient Gemini and Postgres failures (D-032).

One implementation instead of per-call-site loops: exponential backoff with jitter, a bounded
number of attempts, and an explicit "is this error worth retrying?" predicate so permanent
failures (bad API key, malformed request, wrong DB password) fail fast instead of burning the
serverless function's time budget.
"""

from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

import httpx
import psycopg
from google.genai import errors as genai_errors
from psycopg import errors as pg_errors

T = TypeVar("T")

DEFAULT_ATTEMPTS = 4
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 8.0


def is_transient_gemini_error(exc: BaseException) -> bool:
    """429 (rate limit), 408 (timeout), any 5xx, and network-level timeouts/connection failures."""
    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None)
        return code in (408, 429) or (isinstance(code, int) and code >= 500)
    return isinstance(exc, (httpx.TransportError, TimeoutError, ConnectionError))


def is_transient_db_error(exc: BaseException) -> bool:
    """Connection/availability failures (e.g. a Neon cold start), but never auth failures."""
    if isinstance(exc, (pg_errors.InvalidPassword, pg_errors.InvalidAuthorizationSpecification)):
        return False
    return isinstance(exc, psycopg.OperationalError)


def retry_call(
    fn: Callable[[], T],
    *,
    is_transient: Callable[[BaseException], bool],
    label: str,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
) -> T:
    """
    Call fn(); on an error that `is_transient` accepts, wait (exponential backoff + jitter)
    and try again, up to `attempts` total tries. A non-transient error, or the last attempt's
    error, is re-raised unchanged so callers keep their existing error handling.
    """
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == attempts or not is_transient(exc):
                raise
            delay = min(max_delay, base_delay * 2 ** (attempt - 1)) * random.uniform(0.5, 1.0)
            print(
                f"[Retry] {label} failed ({type(exc).__name__}: {str(exc)[:120]}); "
                f"attempt {attempt}/{attempts}, retrying in {delay:.1f}s"
            )
            time.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover
