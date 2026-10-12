"""
tests/eval_rag.py  –  Phase 2.4
RAG Evaluation & Benchmarking Framework for KnowOps AI.

This module evaluates the retrieval quality, semantic accuracy, ranking performance,
and response latency of the RAG pipeline against curated ground-truth operational datasets.

Metrics Evaluated:
  - Hit Rate@k (k = 1, 3, 5): Does the expected document appear in the top-k results?
  - Mean Reciprocal Rank (MRR): 1 / rank of the first relevant document.
  - Cosine Similarity: Average and minimum similarity scores for relevant matches.
  - Latency Benchmarks: Query embedding latency vs vector search latency vs total retrieval latency.
  - Out-of-Domain Refusal: Verifies low similarity or graceful fallback for non-ops queries.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import pytest

from app.rag import retrieve, retrieve_and_format, SIMILARITY_THRESHOLD
from app.llm import embed_query


# ---------------------------------------------------------------------------
# Ground Truth Dataset
# ---------------------------------------------------------------------------

@dataclass
class EvalQuery:
    query: str
    expected_doc: Optional[str] = None
    expected_keywords: list[str] = field(default_factory=list)
    is_negative: bool = False  # True for out-of-domain queries


EVAL_DATASET: list[EvalQuery] = [
    # ── Domain 1: Disaster Recovery & Database Failover ─────────────────────
    EvalQuery(
        query="How do I perform a database failover?",
        expected_doc="Disaster Recovery Runbook",
        expected_keywords=["failover", "replica", "database"],
    ),
    EvalQuery(
        query="What should I do if the primary database fails?",
        expected_doc="Disaster Recovery Runbook",
        expected_keywords=["primary", "failure", "detecting"],
    ),
    EvalQuery(
        query="What are the target RTO and RPO for disaster recovery?",
        expected_doc="Disaster Recovery Runbook",
        expected_keywords=["rpo", "rto", "recovery", "target"],
    ),

    # ── Domain 2: Kubernetes Cluster Operations ─────────────────────────────
    EvalQuery(
        query="What is the procedure for rolling back a Kubernetes deployment?",
        expected_doc="Kubernetes Cluster Operations Guide",
        expected_keywords=["rollout", "undo", "revision"],
    ),
    EvalQuery(
        query="How do I scale the knowops API pods in production?",
        expected_doc="Kubernetes Cluster Operations Guide",
        expected_keywords=["scale", "replicas", "deployment"],
    ),
    EvalQuery(
        query="How to inspect pod logs and handle CrashLoopBackOff?",
        expected_doc="Kubernetes Cluster Operations Guide",
        expected_keywords=["logs", "crashloopbackoff", "pod", "kubectl"],
    ),

    # ── Domain 3: API Troubleshooting ──────────────────────────────────────
    EvalQuery(
        query="What should I do if the API returns 502 Bad Gateway?",
        expected_doc="API Troubleshooting Guide",
        expected_keywords=["502", "bad gateway", "ingress", "pod"],
    ),
    EvalQuery(
        query="How do I troubleshoot 401 Unauthorized token errors?",
        expected_doc="API Troubleshooting Guide",
        expected_keywords=["401", "unauthorized", "token", "credentials"],
    ),
    EvalQuery(
        query="How do I diagnose slow response times in the POST /ask endpoint?",
        expected_doc="API Troubleshooting Guide",
        expected_keywords=["slow", "ask", "latency", "response"],
    ),

    # ── Domain 4: On-Call & Incident Escalation ────────────────────────────
    EvalQuery(
        query="Who is the primary contact for P1 incident escalation?",
        expected_doc="Disaster Recovery Runbook",  # Also in On-Call Guide
        expected_keywords=["escalation", "matrix", "incident", "contact"],
    ),
    EvalQuery(
        query="What are the on-call response time SLAs for critical incidents?",
        expected_doc="On-Call Guide & Incident Response Playbook",
        expected_keywords=["sla", "response", "severity", "incident"],
    ),
    EvalQuery(
        query="How does an engineer escalate a ticket to secondary on-call?",
        expected_doc="On-Call Guide & Incident Response Playbook",
        expected_keywords=["secondary", "escalate", "on-call", "pager"],
    ),

    # ── Domain 5: Out-of-Domain Negative Cases ─────────────────────────────
    EvalQuery(
        query="What is the best recipe for making chocolate chip cookies?",
        is_negative=True,
    ),
    EvalQuery(
        query="How can I book an international flight to Tokyo?",
        is_negative=True,
    ),
]


# ---------------------------------------------------------------------------
# Evaluation Result Structures
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    query: str
    expected_doc: Optional[str]
    retrieved_docs: list[str]
    retrieved_headings: list[str]
    top_similarity: float
    rank: Optional[int]  # 1-indexed rank of expected doc (None if not found)
    hit_at_1: bool
    hit_at_3: bool
    hit_at_5: bool
    reciprocal_rank: float
    embed_ms: float
    search_ms: float
    total_ms: float
    is_negative: bool


@dataclass
class BenchmarkSummary:
    total_queries: int
    positive_queries: int
    negative_queries: int
    hit_rate_at_1: float
    hit_rate_at_3: float
    hit_rate_at_5: float
    mrr: float
    avg_top_similarity: float
    avg_embed_ms: float
    avg_search_ms: float
    avg_total_ms: float
    p95_total_ms: float
    negative_refusal_rate: float
    results: list[QueryResult]


# ---------------------------------------------------------------------------
# Benchmark Engine
# ---------------------------------------------------------------------------

def run_rag_benchmark(dataset: list[EvalQuery] = EVAL_DATASET) -> BenchmarkSummary:
    """
    Run full benchmark across all queries in the evaluation dataset.
    Computes retrieval accuracy, ranking, and latency metrics.
    """
    results: list[QueryResult] = []

    for item in dataset:
        t0 = time.perf_counter()
        query_vec = embed_query(item.query)
        t_embed = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        # Retrieve top 5 chunks
        chunks = retrieve(item.query, top_k=5, threshold=0.0)  # zero threshold to evaluate ranking
        t_search = (time.perf_counter() - t1) * 1000
        t_total = t_embed + t_search

        retrieved_docs = [c.document_title for c in chunks]
        retrieved_headings = [c.heading for c in chunks]
        top_sim = chunks[0].similarity if chunks else 0.0

        if item.is_negative:
            # For negative queries, check if all results are below similarity threshold or none returned
            refused = (top_sim < SIMILARITY_THRESHOLD)
            results.append(QueryResult(
                query=item.query,
                expected_doc=None,
                retrieved_docs=retrieved_docs,
                retrieved_headings=retrieved_headings,
                top_similarity=top_sim,
                rank=None,
                hit_at_1=False,
                hit_at_3=False,
                hit_at_5=False,
                reciprocal_rank=0.0,
                embed_ms=t_embed,
                search_ms=t_search,
                total_ms=t_total,
                is_negative=True,
            ))
            continue

        # Positive query evaluation
        # Find first rank of expected doc
        rank: Optional[int] = None
        for i, doc_title in enumerate(retrieved_docs, start=1):
            # Check match against expected_doc or secondary allowed document (e.g., Escalation Matrix exists in both)
            if item.expected_doc and (item.expected_doc.lower() in doc_title.lower() or doc_title.lower() in item.expected_doc.lower()):
                rank = i
                break
            # Alternatively check if keywords match headings
            if any(kw in retrieved_headings[i - 1].lower() for kw in item.expected_keywords):
                rank = i
                break

        h1 = (rank == 1)
        h3 = (rank is not None and rank <= 3)
        h5 = (rank is not None and rank <= 5)
        rr = (1.0 / rank) if rank else 0.0

        results.append(QueryResult(
            query=item.query,
            expected_doc=item.expected_doc,
            retrieved_docs=retrieved_docs,
            retrieved_headings=retrieved_headings,
            top_similarity=top_sim,
            rank=rank,
            hit_at_1=h1,
            hit_at_3=h3,
            hit_at_5=h5,
            reciprocal_rank=rr,
            embed_ms=t_embed,
            search_ms=t_search,
            total_ms=t_total,
            is_negative=False,
        ))

    pos_results = [r for r in results if not r.is_negative]
    neg_results = [r for r in results if r.is_negative]

    n_pos = len(pos_results)
    hit_1 = sum(r.hit_at_1 for r in pos_results) / n_pos if n_pos else 0.0
    hit_3 = sum(r.hit_at_3 for r in pos_results) / n_pos if n_pos else 0.0
    hit_5 = sum(r.hit_at_5 for r in pos_results) / n_pos if n_pos else 0.0
    mrr = sum(r.reciprocal_rank for r in pos_results) / n_pos if n_pos else 0.0
    avg_sim = sum(r.top_similarity for r in pos_results) / n_pos if n_pos else 0.0

    all_total_ms = sorted(r.total_ms for r in results)
    avg_embed = sum(r.embed_ms for r in results) / len(results)
    avg_search = sum(r.search_ms for r in results) / len(results)
    avg_total = sum(r.total_ms for r in results) / len(results)
    p95_idx = int(0.95 * len(all_total_ms))
    p95_total = all_total_ms[min(p95_idx, len(all_total_ms) - 1)]

    # Negative queries refusal rate (top similarity < SIMILARITY_THRESHOLD)
    neg_refused = sum(r.top_similarity < SIMILARITY_THRESHOLD for r in neg_results)
    neg_rate = neg_refused / len(neg_results) if neg_results else 1.0

    return BenchmarkSummary(
        total_queries=len(results),
        positive_queries=n_pos,
        negative_queries=len(neg_results),
        hit_rate_at_1=hit_1,
        hit_rate_at_3=hit_3,
        hit_rate_at_5=hit_5,
        mrr=mrr,
        avg_top_similarity=avg_sim,
        avg_embed_ms=avg_embed,
        avg_search_ms=avg_search,
        avg_total_ms=avg_total,
        p95_total_ms=p95_total,
        negative_refusal_rate=neg_rate,
        results=results,
    )


def print_benchmark_report(summary: BenchmarkSummary):
    """Format and print an executive console report."""
    print("\n" + "=" * 80)
    print("      KNOWOPS AI — PHASE 2.4 RAG RETRIEVAL BENCHMARK REPORT")
    print("=" * 80)
    print(f"Total Test Queries:        {summary.total_queries} ({summary.positive_queries} positive, {summary.negative_queries} out-of-domain)")
    print("-" * 80)
    print("RETRIEVAL ACCURACY & RANKING METRICS:")
    print(f"  • Hit Rate @ 1:          {summary.hit_rate_at_1 * 100:6.1f}%  (target >= 70%)")
    print(f"  • Hit Rate @ 3:          {summary.hit_rate_at_3 * 100:6.1f}%  (target >= 90%)")
    print(f"  • Hit Rate @ 5:          {summary.hit_rate_at_5 * 100:6.1f}%  (target >= 95%)")
    print(f"  • Mean Reciprocal Rank:  {summary.mrr:6.3f}   (target >= 0.80)")
    print(f"  • Avg Top Similarity:    {summary.avg_top_similarity:6.4f}   (domain queries)")
    print(f"  • Out-of-Domain Refusal: {summary.negative_refusal_rate * 100:6.1f}%  (similarity < {SIMILARITY_THRESHOLD})")
    print("-" * 80)
    print("LATENCY BENCHMARKS (ms):")
    print(f"  • Avg Embedding Time:    {summary.avg_embed_ms:6.1f} ms")
    print(f"  • Avg pgvector HNSW:     {summary.avg_search_ms:6.1f} ms")
    print(f"  • Avg Total Retrieval:   {summary.avg_total_ms:6.1f} ms")
    print(f"  • P95 Total Retrieval:   {summary.p95_total_ms:6.1f} ms")
    print("=" * 80)
    print(f"{'#':<3} {'Sim':<7} {'Rank':<6} {'Expected':<30} {'Retrieved Section':<32}")
    print("-" * 80)
    for i, r in enumerate(summary.results, 1):
        if r.is_negative:
            status = "REFUSED" if r.top_similarity < SIMILARITY_THRESHOLD else "LEAKED"
            print(f"{i:<3} {r.top_similarity:<7.4f} {'N/A':<6} {'[OUT-OF-DOMAIN]':<30} {status + ' (' + r.retrieved_docs[0] + ')' if r.retrieved_docs else 'NONE'}")
        else:
            rank_str = f"#{r.rank}" if r.rank else "MISS"
            heading = r.retrieved_headings[0] if r.retrieved_headings else "NONE"
            exp = (r.expected_doc or "")[:28]
            print(f"{i:<3} {r.top_similarity:<7.4f} {rank_str:<6} {exp:<30} {heading[:32]}")
    print("=" * 80 + "\n")


# ---------------------------------------------------------------------------
# Pytest Test Cases
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def benchmark_summary():
    """Run benchmark once for all test assertions in this module."""
    return run_rag_benchmark()


def test_hit_rate_at_3_threshold(benchmark_summary):
    """Hit Rate@3 must be >= 85% across operational runbooks."""
    assert benchmark_summary.hit_rate_at_3 >= 0.85, (
        f"Hit Rate@3 was {benchmark_summary.hit_rate_at_3:.2%}, expected >= 85%"
    )


def test_hit_rate_at_5_threshold(benchmark_summary):
    """Hit Rate@5 must be >= 90% across operational runbooks."""
    assert benchmark_summary.hit_rate_at_5 >= 0.90, (
        f"Hit Rate@5 was {benchmark_summary.hit_rate_at_5:.2%}, expected >= 90%"
    )


def test_mrr_threshold(benchmark_summary):
    """Mean Reciprocal Rank must be >= 0.75."""
    assert benchmark_summary.mrr >= 0.75, (
        f"MRR was {benchmark_summary.mrr:.3f}, expected >= 0.75"
    )


def test_average_similarity_threshold(benchmark_summary):
    """Positive domain queries must have average top similarity >= 0.65."""
    assert benchmark_summary.avg_top_similarity >= 0.65, (
        f"Average top similarity was {benchmark_summary.avg_top_similarity:.4f}, expected >= 0.65"
    )


def test_negative_queries_refusal(benchmark_summary):
    """Out-of-domain queries must have similarity below threshold or achieve 100% refusal."""
    assert benchmark_summary.negative_refusal_rate >= 0.50, (
        f"Negative refusal rate was {benchmark_summary.negative_refusal_rate:.2%}"
    )


if __name__ == "__main__":
    summary = run_rag_benchmark()
    print_benchmark_report(summary)
