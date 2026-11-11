"""
tests/test_rag.py  –  Phase 2.3
Automated tests for the RAG Retrieval engine and FastAPI endpoints.
"""

import math

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rag import SIMILARITY_THRESHOLD, correct_typos, retrieve, format_context_for_llm, retrieve_and_format
from app.schemas import ChunkResult, AskResponse, HealthResponse


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.live
def test_health_endpoint(client):
    """GET /health should return 200 with database connected and positive counts."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert data["knowledge_base"]["documents"] >= 4
    assert data["knowledge_base"]["chunks"] >= 60


@pytest.mark.live
def test_rag_retrieval_database_failover():
    """retrieve() should return chunks from Disaster Recovery Runbook for failover queries."""
    chunks = retrieve("How do I perform a database failover?", top_k=3)
    assert len(chunks) > 0
    assert any("Disaster Recovery" in c.document_title for c in chunks)
    assert chunks[0].similarity > 0.65
    assert isinstance(chunks[0], ChunkResult)


@pytest.mark.live
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


def test_empty_query_returns_empty(fake_gemini, fake_db):
    """retrieve() with empty or whitespace-only query should return empty list — without embedding
    anything or querying the database."""
    assert retrieve("") == []
    assert retrieve("   ") == []
    assert fake_gemini.embed_calls == [] and fake_db.executed == []


# --- Phase 11.2: ranking, offline ------------------------------------------------------------
# Ranking happens in Postgres (cosine distance, threshold, ORDER BY, LIMIT). The fake database
# answers retrieve()'s query with the same math in Python, so these tests check that retrieve()
# sends the right vector, threshold and top_k, and keeps the database's order; the SQL-shape test
# pins the clauses that do the ranking in production.

def _unit(vec):
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


def _blend(a, b, weight_a):
    """A unit vector whose cosine similarity to `a` is controlled by weight_a."""
    return _unit([weight_a * x + (1 - weight_a) * y for x, y in zip(a, b)])


def _cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


def _pgvector_search(chunks):
    """Stand-in for retrieve()'s SQL: WHERE 1 - distance >= threshold ORDER BY distance LIMIT top_k."""
    def run(params):
        query_literal, _, threshold, _, top_k = params
        query_vec = [float(x) for x in query_literal.strip("[]").split(",")]
        scored = [(round(_cosine(query_vec, c["embedding"]), 6), c) for c in chunks]
        kept = sorted((s for s in scored if s[0] >= threshold), key=lambda s: -s[0])[:top_k]
        return [(c["id"], c["title"], c["source"], c["heading"], c["content"], sim) for sim, c in kept]
    return run


QUESTION = "How do I perform a database failover?"


@pytest.fixture
def knowledge_base(fake_gemini, fake_db):
    """Four chunks at known similarities to QUESTION: 1.0, ~0.9, ~0.6 and ~0.0."""
    q = fake_gemini.embedding_for(QUESTION)
    unrelated = fake_gemini.embedding_for("unrelated text about billing")
    unrelated = _unit([u - _cosine(unrelated, q) * x for u, x in zip(unrelated, q)])  # orthogonal to q
    chunks = [
        {"id": 4, "title": "Billing FAQ", "source": "billing.md", "heading": "", "content": "Invoices.", "embedding": unrelated},
        {"id": 2, "title": "DR Runbook", "source": "dr.md", "heading": "4.3 Verify", "content": "Check lag.", "embedding": _blend(q, unrelated, 0.69)},
        {"id": 1, "title": "DR Runbook", "source": "dr.md", "heading": "4.2 Failover", "content": "Promote.", "embedding": q},
        {"id": 3, "title": "K8s Guide", "source": "k8s.md", "heading": "Rollback", "content": "Undo.", "embedding": _blend(q, unrelated, 0.43)},
    ]
    fake_db.on("FROM chunks c", _pgvector_search(chunks))
    return chunks


def test_retrieve_ranks_by_similarity_most_similar_first(knowledge_base):
    chunks = retrieve(QUESTION, top_k=10, threshold=0.0)

    assert [c.chunk_id for c in chunks] == [1, 2, 3, 4]
    assert chunks[0].similarity == pytest.approx(1.0)
    similarities = [c.similarity for c in chunks]
    assert similarities == sorted(similarities, reverse=True)
    assert chunks[0].document_title == "DR Runbook" and chunks[0].heading == "4.2 Failover"


def test_retrieve_drops_chunks_below_the_threshold(knowledge_base):
    chunks = retrieve(QUESTION, top_k=10, threshold=0.5)

    assert [c.chunk_id for c in chunks] == [1, 2, 3]
    assert all(c.similarity >= 0.5 for c in chunks)


def test_retrieve_returns_at_most_top_k(knowledge_base):
    assert [c.chunk_id for c in retrieve(QUESTION, top_k=2, threshold=0.0)] == [1, 2]


def test_retrieve_embeds_the_stripped_question_as_a_query(knowledge_base, fake_gemini, fake_db):
    retrieve(f"  {QUESTION}  ", top_k=3, threshold=0.4)

    assert fake_gemini.embed_calls[0]["contents"] == QUESTION
    assert fake_gemini.embed_calls[0]["config"].task_type == "RETRIEVAL_QUERY"
    _, params = fake_db.queries("FROM chunks c")[0]
    sent = [float(x) for x in params[0].strip("[]").split(",")]
    assert sent == pytest.approx(fake_gemini.embedding_for(QUESTION))
    assert params[0] == params[1] == params[3]  # the same query vector in all three places
    assert params[2] == 0.4 and params[4] == 3


def test_retrieve_sql_ranks_by_ascending_cosine_distance(knowledge_base, fake_db):
    """The clauses that do the ranking in production: filter on similarity, ascending distance, limit."""
    retrieve(QUESTION)
    sql = " ".join(fake_db.queries("FROM chunks c")[0][0].split())

    assert "WHERE (1 - (c.embedding <=> %s::vector)) >= %s" in sql
    assert "ORDER BY c.embedding <=> %s::vector LIMIT %s" in sql  # ascending distance = most similar first
    assert "DESC" not in sql.upper()


# --- D-056: SIMILARITY_THRESHOLD re-tuned from 0.55 to 0.65 ----------------------------------
# Bug #2 (external bug report, 2026-11-08, High): off-topic probes ("what is 2+2", "Terraform
# state locking", "AWS S3 lifecycle policy") scored up to 0.583 at the old 0.55 threshold — above
# it — and were retrieved and cited as if relevant. Measured live on 2026-11-10: highest known
# false-positive top score 0.583; lowest known true-positive top score (across all 16 in-scope
# golden questions) 0.699. 0.65 sits in that gap.

def test_similarity_threshold_sits_between_the_measured_false_and_true_positive_bands():
    """Offline guard: nobody can move the constant back toward 0.55 (or past 0.699) without
    re-measuring — the bound itself is the evidence from D-056, not an opinion."""
    assert 0.583 < SIMILARITY_THRESHOLD < 0.699


@pytest.mark.live
@pytest.mark.parametrize("query", [
    "what is 2+2",
    "Terraform state locking",
    "AWS S3 lifecycle policy",
    "best pizza topping",
])
def test_off_topic_questions_get_no_sources_at_the_new_threshold(query):
    """The live counterpart: these exact queries (from the bug report / its live re-measurement)
    used to clear the old 0.55 threshold and are retrieved with it dropped — proving the fix, not
    just the constant's position."""
    assert retrieve(query) == []


@pytest.mark.live
def test_every_in_scope_golden_question_still_retrieves_something():
    """The other side of the same fix: raising the threshold must not start false-refusing the
    golden set. Full fact-level scoring is evals' job (`python -m evals`); this is the fast,
    offline-adjacent regression that the threshold alone didn't silence a real question."""
    from evals.golden import load_golden_set

    starved = [item.id for item in load_golden_set()
               if not item.must_refuse and not retrieve(item.question, top_k=1)]
    assert starved == []


# --- Bug #16 (external bug report, Low, D-077 — revisited after D-069 declined a fix) ----------------------
# A typo'd query used to rank the wrong-but-related runbook section first because neither typo'd word
# matched real heading/title text at all. correct_typos() fixes this without a Gemini call (the latency
# tradeoff that made D-069 decline a fix) by correcting against the knowledge base's own small vocabulary
# (document titles + chunk headings), offline/CPU-only.

_TEST_VOCAB = frozenset({
    "kubernetes", "rollback", "disaster", "recovery", "runbook", "failover", "first", "steps", "escalation",
})


@pytest.mark.parametrize("typo,expected", [
    ("kubernetis rolbak", "kubernetes rollback"),
    ("rollbak the deployment", "rollback the deployment"),
    ("whats the escalaton proccess", "whats the escalation proccess"),  # "proccess" isn't in the vocabulary
])
def test_correct_typos_fixes_known_misspellings(typo, expected):
    assert correct_typos(typo, vocabulary=_TEST_VOCAB) == expected


@pytest.mark.parametrize("already_correct", [
    "How do I perform a database failover?",
    "What is the first step of that procedure?",  # "step" singular must not become "steps"
    "What triggers a 502 error?",
    "What is RTO?",
])
def test_correct_typos_leaves_correctly_spelled_queries_unchanged(already_correct):
    assert correct_typos(already_correct, vocabulary=_TEST_VOCAB) == already_correct


def test_correct_typos_does_not_treat_a_plain_plural_as_a_typo():
    """"step" -> "steps" was a real false positive found while building this (ratio 0.889, higher than the
    real typo "rolbak"->"rollback" at 0.857) — cutoff tuning alone can't separate them, so plural-only
    matches are excluded explicitly."""
    assert correct_typos("the first step", vocabulary=_TEST_VOCAB) == "the first step"


def test_correct_typos_does_not_corrupt_a_real_word_into_an_unrelated_close_one():
    """"fires" -> "first" was a second real false positive (ratio 0.8, right at the original cutoff) —
    the cutoff was raised to 0.82 specifically to exclude this while still catching real typos."""
    assert correct_typos("the alert fires", vocabulary=_TEST_VOCAB) == "the alert fires"


def test_correct_typos_with_empty_vocabulary_is_a_no_op():
    assert correct_typos("kubernetis rolbak", vocabulary=frozenset()) == "kubernetis rolbak"


def test_correct_typos_only_touches_words_it_can_confidently_fix():
    """A word with no close vocabulary match at all (not a typo of anything known) is left alone."""
    assert correct_typos("xyzzyplugh", vocabulary=_TEST_VOCAB) == "xyzzyplugh"


@pytest.mark.live
def test_correct_typos_fixes_the_reported_ranking_regression_live():
    """D-069's original measurement: the DR runbook's rollback section outranked the actually-relevant
    Kubernetes rollback section on the raw typo'd query. Confirms the fix end to end against real
    embeddings, not just the string transform."""
    corrected = correct_typos("kubernetis rolbak")
    assert corrected == "kubernetes rollback"

    results = retrieve(corrected, top_k=5)
    assert results, "expected at least one result"
    assert results[0].document_title == "Kubernetes Cluster Operations Guide"
    assert results[0].heading == "4.3 Rollback"
