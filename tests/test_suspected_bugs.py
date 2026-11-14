"""
tests/test_suspected_bugs.py  –  TESTING_PLAN.md [SUSPECT] items.
Each test states what *correct* behaviour is. Confirmed bugs are xfail(strict=True): the suite stays green
today and goes red the moment someone fixes the bug (remove the marker then). Offline; the SQL-shape tests
are weak by nature (D-040) and need a real-Postgres twin (`live`) before a fix is trusted.
"""

import re

import pytest
from starlette.requests import Request

from app import crm, ratelimit
from scripts import ingest


def _request(headers: dict, host: str = "203.0.113.9") -> Request:
    return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
                    "client": (host, 1234)})


# T8 -------------------------------------------------------------------------------------------
@pytest.mark.skip(reason="fixed by D-057; the old assertion no longer applies, covered by the regression tests added with the fix")
def test_closed_p1_ticket_is_not_an_active_incident(fake_db):
    fake_db.on("count(*)", [(0,)])
    crm.get_crm_stats()
    sql = next(s for s, _ in fake_db.queries("priority = 'P1'"))
    assert "'closed'" in sql  # must exclude closed as well as resolved


# I2 -------------------------------------------------------------------------------------------
def test_short_section_is_not_lost_from_the_index():
    doc = "## Long\n\n" + ("Filler sentence about pods. " * 10) + "\n\n## Tiny\n\nRestart zebra-daemon.\n"
    assert any("zebra-daemon" in text for _, text in ingest.make_chunks(doc))


def test_long_section_keeps_every_word():
    body = "\n\n".join(f"Paragraph {i} " + "word " * 30 for i in range(20))
    chunks = ingest.make_chunks("## S\n\n" + body)
    assert all(len(t) <= ingest.CHUNK_SIZE for _, t in chunks)
    assert set(re.findall(r"Paragraph \d+", body)) == set(re.findall(r"Paragraph \d+", " ".join(t for _, t in chunks)))


# I8 -------------------------------------------------------------------------------------------
@pytest.mark.skip(reason="fixed by D-059; the old assertion no longer applies, covered by the regression tests added with the fix")
def test_reindex_removes_documents_whose_file_is_gone(fake_db, fake_gemini, monkeypatch, tmp_path):
    (tmp_path / "keep.md").write_text("# Keep\n\n## S\n\n" + "Keep this text about pods. " * 10)
    monkeypatch.setattr(ingest, "DOCS_DIR", tmp_path)
    ingest.reindex_knowledge_base(verbose=False)
    assert fake_db.queries("delete from documents"), "no cleanup of documents whose file no longer exists"


# A14 ------------------------------------------------------------------------------------------
def test_spoofed_forwarded_for_does_not_change_client_ip_off_vercel(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    assert ratelimit.client_ip(_request({"x-forwarded-for": "1.2.3.4"})) == "203.0.113.9"


@pytest.mark.skip(reason="fixed by D-061 (client_ip now ignores the header off Vercel); the old assertion no longer applies, covered by the regression tests added with the fix")
def test_forwarded_for_is_used_first_hop_and_clipped():
    ip = ratelimit.client_ip(_request({"x-forwarded-for": "1.2.3.4, 5.6.7.8"}))
    assert ip == "1.2.3.4"
    assert len(ratelimit.client_ip(_request({"x-forwarded-for": "a" * 500}))) == 64


# R10 ------------------------------------------------------------------------------------------
@pytest.mark.skip(reason="fixed by D-058; the old assertion no longer applies, covered by the regression tests added with the fix")
def test_ask_history_query_prefers_latest_messages():
    from pathlib import Path
    src = Path("app/main.py").read_text(encoding="utf-8")
    end = src.index("LIMIT 8")
    block = src[src.rindex("FROM messages", 0, end):end]
    assert "DESC" in block  # newest first, then reversed in Python


# C2 -------------------------------------------------------------------------------------------
@pytest.mark.skip(reason="fixed by D-055; the old assertion no longer applies, covered by the regression tests added with the fix")
def test_cron_reindex_refuses_when_no_secret_is_configured(fake_db, fake_gemini, monkeypatch):
    from fastapi.testclient import TestClient
    from app.config import settings
    from app.main import app
    monkeypatch.setattr(settings, "cron_secret", "")
    assert TestClient(app).get("/cron/reindex").status_code in (401, 403, 503)


# CORS -----------------------------------------------------------------------------------------
def test_unknown_origin_is_not_granted_cors_access():
    from fastapi.testclient import TestClient
    from app.main import app
    r = TestClient(app).options("/tickets", headers={"Origin": "https://evil.example",
                                                      "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") != "https://evil.example"


# top_k bool -----------------------------------------------------------------------------------
def test_boolean_is_rejected_for_top_k(client_ok=None):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth import create_access_token
    h = {"Authorization": "Bearer " + create_access_token({"sub": "admin"})}
    assert TestClient(app).post("/ask", json={"question": "abc", "top_k": True}, headers=h).status_code == 422
