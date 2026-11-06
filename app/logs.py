"""
app/logs.py  –  Phase 12.1
Structured JSON logging (D-042). Every line written to stdout is one JSON object, which Vercel collects
as a runtime log. RequestLogMiddleware gives each request an id, times it and writes one `request` line
(method, path, status, latency, user, tools the agent called); every other event logged while that
request is handled carries the same request_id, so one id finds everything that happened.

What is never logged: request bodies, query strings, headers, tokens, passwords or question text.
Events name what happened and carry short, bounded fields.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger("knowops")

# One mutable record per request. Sync dependencies and routes run in a threadpool that gets a *copy* of
# the context, so a value set there would never reach the middleware; mutating this shared dict does.
_request: ContextVar[Optional[dict]] = ContextVar("knowops_request", default=None)

# An inbound X-Request-ID is reused only if it looks like an id; anything else is replaced.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
MAX_FIELD_CHARS = 300


class _StdoutHandler(logging.StreamHandler):
    """Writes to whatever sys.stdout is at emit time (so pytest's capture sees it too)."""

    def __init__(self):
        super().__init__()

    @property
    def stream(self):
        return sys.stdout

    @stream.setter
    def stream(self, value):
        pass


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
        }
        request = _request.get()
        if request is not None:
            entry["request_id"] = request["request_id"]
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(entry, default=str, ensure_ascii=False)


def configure_logging() -> None:
    """Idempotent: one JSON handler on the `knowops` logger, not propagated to the root logger."""
    if any(isinstance(h, _StdoutHandler) for h in logger.handlers):
        return
    handler = _StdoutHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(settings.log_level.upper())
    logger.propagate = False


def _bounded(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
        return value[:MAX_FIELD_CHARS] + "…"
    return value


def log_event(event: str, level: str = "info", **fields: Any) -> None:
    """Log one structured event. Long string fields are cut to MAX_FIELD_CHARS."""
    logger.log(getattr(logging, level.upper()), event, extra={"fields": {k: _bounded(v) for k, v in fields.items()}})


def set_request_user(user: Optional[str]) -> None:
    """Called by the auth dependencies once a token is verified."""
    request = _request.get()
    if request is not None:
        request["user"] = user


def record_tool_call(tool: str) -> None:
    """Called by the agent loop for every tool it runs (blocked calls included, marked)."""
    request = _request.get()
    if request is not None:
        request["tools"].append(tool)


def current_request_id() -> Optional[str]:
    request = _request.get()
    return request["request_id"] if request else None


class RequestLogMiddleware:
    """Pure ASGI middleware: request id in, one `request` log line and an X-Request-ID header out."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        inbound = headers.get("x-request-id", "")
        request_id = inbound if _VALID_REQUEST_ID.match(inbound) else uuid.uuid4().hex
        request = {"request_id": request_id, "user": None, "tools": [], "status": None}
        token = _request.set(request)
        started = time.perf_counter()

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                request["status"] = message["status"]
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [(b"x-request-id", request_id.encode())]
            await send(message)

        error: Optional[BaseException] = None
        try:
            await self.app(scope, receive, send_with_request_id)
        except BaseException as exc:  # logged here, then re-raised for Starlette's 500 handler
            error = exc
            raise
        finally:
            status = request["status"] if request["status"] is not None else 500
            fields = {
                "method": scope.get("method"),
                "path": scope.get("path"),
                "status": status,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "user": request["user"],
            }
            if request["tools"]:
                fields["tools"] = request["tools"]
            if headers.get("x-vercel-id"):
                fields["vercel_id"] = headers["x-vercel-id"][:120]
            if error is not None:
                fields["error_type"] = type(error).__name__
            level = "error" if status >= 500 else "warning" if status >= 400 else "info"
            log_event("request", level, **fields)
            _request.reset(token)
