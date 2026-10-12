"""
tests/test_rag.py  –  Phase 2.3
Automated tests for the RAG Retrieval engine and FastAPI endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rag import retrieve, format_context_for_llm, retrieve_and_format
from app.schemas import ChunkResult, AskResponse, HealthResponse


@pytest.fixture
def client():
    return TestClient(app)


def test_health_endpoint(client):
    """GET /health should return 200 with database connected and positive counts."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert data["knowledge_base"]["documents"] >= 4
    assert data["knowledge_base"]["chunks"] >= 60


def test_rag_retrieval_database_failover():
    """retrieve() should return chunks from Disaster Recovery Runbook for failover queries."""
    chunks = retrieve("How do I perform a database failover?", top_k=3)
    assert len(chunks) > 0
    assert any("Disaster Recovery" in c.document_title for c in chunks)
    assert chunks[0].similarity > 0.65
    assert isinstance(chunks[0], ChunkResult)


def test_rag_retrieval_kubernetes_rollback():
    """retrieve() should return chunks from Kubernetes Operations Guide for rollback queries."""
    chunks = retrieve("How do I rollback a Kubernetes deployment?", top_k=3)
    assert len(chunks) > 0
    assert any("Kubernetes" in c.document_title for c in chunks)
    assert chunks[0].similarity > 0.65


def test_format_context_for_llm():
    """format_context_for_llm() should format chunks with document title and heading citations."""
    sample_chunk = ChunkResult(
        chunk_id=1,
        document_title="Sample Runbook",
        document_source="data/docs/sample.md",
        heading="Incident Escalation",
        content="Call the primary on-call engineer at +1-555-0100.",
        similarity=0.88,
    )
    formatted = format_context_for_llm([sample_chunk])
    assert len(formatted) == 1
    assert "Source: Sample Runbook › Incident Escalation" in formatted[0]
    assert "Call the primary on-call engineer" in formatted[0]


def test_empty_query_returns_empty():
    """retrieve() with empty or whitespace-only query should return empty list."""
    assert retrieve("") == []
    assert retrieve("   ") == []
