"""
evals/client.py  –  Phase 13.2 (D-048)
Two ways to put a question to /ask, both returning the same AskResult:

  InProcessClient  runs the real FastAPI route inside this process (auth, retrieval, Gemini, citations — everything
                   but the network hop), using the database and Gemini key from .env. The default.
  HttpClient       logs in to a deployed site and calls it over HTTP (--url), pacing itself under the 10/min limit.

Neither client prints credentials or tokens.
"""

from __future__ import annotations

import logging
import time
import uuid
import warnings
from typing import Callable, Optional

import httpx

from app.config import settings
from evals.results import AskResult, SourceRef

REQUEST_ID_PREFIX = "kops-eval"
MAX_RETRY_AFTER_SECONDS = 70


class EvalSetupError(RuntimeError):
    """The evaluation cannot start (for example the login was rejected)."""


def _request_id(tag: Optional[str]) -> str:
    return f"{REQUEST_ID_PREFIX}-{tag or uuid.uuid4().hex[:8]}"


def _to_result(response: httpx.Response, latency_ms: float, request_id: str) -> AskResult:
    if response.status_code != 200:
        try:
            detail = str(response.json().get("detail", ""))
        except ValueError:
            detail = response.text
        return AskResult(status=response.status_code, answer="", sources=(), latency_ms=latency_ms,
                         request_id=request_id, error=f"HTTP {response.status_code}: {detail[:200]}")
    body = response.json()
    sources = tuple(
        SourceRef(document=s["document_source"], heading=s["heading"], similarity=float(s["similarity"]),
                  title=s.get("document_title", ""), content=s.get("content", ""))
        for s in body.get("sources", [])
    )
    return AskResult(status=200, answer=body["answer"], sources=sources, latency_ms=latency_ms, request_id=request_id)


def _payload(question: str, top_k: Optional[int]) -> dict:
    return {"question": question} | ({"top_k": top_k} if top_k else {})


NOISY_LOGGERS = ("knowops", "google_genai", "httpx")


class InProcessClient:
    """Context manager: while open, the rate limiter and request counter are switched off so a 19-question run is
    neither throttled nor written into the request_metrics table, and the app's loggers are silenced so they do not
    drown the report. Everything is restored on exit."""

    def __init__(self) -> None:
        self._saved: Optional[tuple] = None
        self._log_levels: dict[str, int] = {}

    def __enter__(self) -> "InProcessClient":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")      # Starlette's TestClient warns about httpx on import; not report material
            from fastapi.testclient import TestClient
            from app.auth import create_access_token
            from app.main import app

        self._saved = (settings.rate_limit_ask_per_minute, settings.metrics_enabled)
        settings.rate_limit_ask_per_minute = 0
        settings.metrics_enabled = False
        # The app writes one JSON log line per request, and the Gemini SDK is chatty; neither belongs in a report.
        for name in NOISY_LOGGERS:
            self._log_levels[name] = logging.getLogger(name).level
            logging.getLogger(name).setLevel(logging.CRITICAL)
        self._http = TestClient(app, raise_server_exceptions=False)
        token = create_access_token({"sub": "eval", "role": "operator"})
        self._headers = {"Authorization": f"Bearer {token}"}
        return self

    def __exit__(self, *exc_info) -> None:
        if self._saved is not None:
            settings.rate_limit_ask_per_minute, settings.metrics_enabled = self._saved
        for name, level in self._log_levels.items():
            logging.getLogger(name).setLevel(level)

    def ask(self, question: str, top_k: Optional[int] = None, tag: Optional[str] = None) -> AskResult:
        request_id = _request_id(tag)
        started = time.perf_counter()
        try:
            response = self._http.post("/ask", json=_payload(question, top_k),
                                       headers={**self._headers, "X-Request-ID": request_id})
        except Exception as exc:  # the route itself is never expected to raise; this keeps one bad call from ending a run
            return AskResult(status=0, answer="", sources=(), latency_ms=(time.perf_counter() - started) * 1000,
                             request_id=request_id, error=f"{type(exc).__name__}: {str(exc)[:200]}")
        return _to_result(response, (time.perf_counter() - started) * 1000, request_id)


class HttpClient:
    def __init__(
        self,
        base_url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        max_rate_limit_waits: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username if username is not None else settings.app_username
        self._password = password if password is not None else settings.app_password
        self._transport = transport
        self._sleep = sleep
        self._max_waits = max_rate_limit_waits

    def __enter__(self) -> "HttpClient":
        self._http = httpx.Client(base_url=self._base_url, timeout=120, transport=self._transport)
        try:
            response = self._http.post("/auth/login", json={"username": self._username, "password": self._password})
        except httpx.HTTPError as exc:
            raise EvalSetupError(f"cannot reach {self._base_url}: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise EvalSetupError(f"login to {self._base_url} failed with HTTP {response.status_code}")
        self._headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
        return self

    def __exit__(self, *exc_info) -> None:
        self._http.close()

    def ask(self, question: str, top_k: Optional[int] = None, tag: Optional[str] = None) -> AskResult:
        request_id = _request_id(tag)
        headers = {**self._headers, "X-Request-ID": request_id}
        for waited in range(self._max_waits + 1):
            started = time.perf_counter()
            try:
                response = self._http.post("/ask", json=_payload(question, top_k), headers=headers)
            except httpx.HTTPError as exc:
                return AskResult(status=0, answer="", sources=(), latency_ms=(time.perf_counter() - started) * 1000,
                                 request_id=request_id, error=f"{type(exc).__name__}: {str(exc)[:200]}")
            latency_ms = (time.perf_counter() - started) * 1000
            if response.status_code == 429 and waited < self._max_waits:
                # Over the per-user limit: wait as told (the wait is not part of the measured latency) and retry.
                try:
                    wait = float(response.headers.get("Retry-After", 10))
                except ValueError:
                    wait = 10.0
                self._sleep(min(max(wait, 1.0), MAX_RETRY_AFTER_SECONDS))
                continue
            return _to_result(response, latency_ms, request_id)
        raise AssertionError("unreachable")  # pragma: no cover
