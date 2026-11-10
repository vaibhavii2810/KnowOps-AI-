"""
tests/test_cors.py  –  Phase 10 security hardening, D-062
Bug #8 (external bug report, Medium): allow_origins=["*"] combined with allow_credentials=True made
Starlette's CORSMiddleware echo the request's own Origin back as Access-Control-Allow-Origin (browsers
reject a literal "*" alongside credentials, so the library works around it this way) — effectively
trusting every origin with credentials. Auth here is a Bearer token in a header, never a cookie, so
there is no ambient credential for a hostile page to ride on; allow_credentials=False removes the
echo-back behavior entirely while a real "*" still serves any origin, honestly, with no credentials.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.usefixtures("no_network")


@pytest.fixture
def client():
    return TestClient(app)


def _preflight(client, origin, path="/ask", method="POST"):
    return client.request(
        "OPTIONS", path,
        headers={"Origin": origin, "Access-Control-Request-Method": method},
    )


def test_an_unknown_origin_is_not_granted_cors_access(client):
    response = _preflight(client, "https://evil.com")
    # A real "*" (not the request's Origin echoed back) — the honest, credential-free wildcard behavior.
    assert response.headers.get("access-control-allow-origin") == "*"
    assert response.headers.get("access-control-allow-origin") != "https://evil.com"


def test_no_credentials_header_is_ever_sent():
    """Without this, a hostile page could at least confirm an ambient credential (a cookie) would be sent —
    there is none here, but the header should not even claim otherwise."""
    client = TestClient(app)
    response = _preflight(client, "https://evil.com")
    assert "access-control-allow-credentials" not in {k.lower() for k in response.headers}


@pytest.mark.parametrize("origin", ["https://evil.com", "http://localhost:3000", "https://knowops-ai.vercel.app"])
def test_every_origin_gets_the_same_honest_wildcard_not_special_treatment(client, origin):
    """The fix is origin-blind on purpose: a real "*" treats every origin identically, which is what makes
    it safe to pair with allow_credentials=False — there is nothing origin-specific left to get wrong."""
    response = _preflight(client, origin)
    assert response.headers.get("access-control-allow-origin") == "*"
