# Pytest test configuration and fixtures (built in Phase 4)

import pytest

from app.auth import create_access_token
from app.config import settings


@pytest.fixture
def auth_headers() -> dict:
    """Authorization header for a valid operator JWT (Phase 5.4 protected routes)."""
    token = create_access_token({"sub": settings.app_username, "role": "operator"})
    return {"Authorization": f"Bearer {token}"}
