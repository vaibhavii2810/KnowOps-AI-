# Pytest test configuration and fixtures (built in Phase 4)

import pytest

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
