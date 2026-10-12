"""
app/rag.py  –  Phase 2.3
Retrieval-Augmented Generation (RAG) — semantic search over the knowledge base.

This module is the retrieval layer of the RAG pipeline:
  1. Takes a natural-language user query
  2. Converts it to a 768-d query embedding via Gemini (embed_query)
  3. Runs an approximate nearest-neighbour search against the pgvector HNSW index
  4. Returns the top-k most semantically similar chunks with source metadata

The returned chunks are fed directly into chat_completion() as grounded context
so the LLM can generate accurate, cited answers.

Flow:
    user question
        → embed_query()              (Phase 2.1 – app/llm.py)
        → cosine similarity search   (pgvector HNSW index)
        → ChunkResult list           (this file)
        → chat_completion()          (Phase 2.1 – app/llm.py)
        → grounded answer            (Phase 2.5 – app/main.py /ask)
"""

from __future__ import annotations

from app.db import get_conn
from app.llm import embed_query
from app.schemas import ChunkResult


# Minimum cosine similarity a chunk must reach to be included in results.
# Tuned in Phase 2.4: 0.55 cleanly rejects out-of-domain queries (~0.50)
# while preserving all valid operational queries (which score >= 0.70).
SIMILARITY_THRESHOLD = 0.55


def retrieve(
    query: str,
    top_k: int = 5,
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[ChunkResult]:
    """
    Retrieve the top-k most semantically relevant knowledge-base chunks for a query.

    Args:
        query:     The user's natural-language question.
        top_k:     Maximum number of chunks to return (default 5).
        threshold: Minimum cosine similarity (0–1). Chunks below this are dropped.

    Returns:
        A list of ChunkResult objects sorted by similarity descending.
        Returns an empty list if the knowledge base is empty or no chunk
        meets the similarity threshold.

    Example:
        >>> chunks = retrieve("How do I perform a database failover?", top_k=3)
        >>> for c in chunks:
        ...     print(c.similarity, c.document_title, c.heading)
        0.7147 Disaster Recovery Runbook 4.3 Verification
        0.6967 Disaster Recovery Runbook 4.1 Detecting Primary Database Failure
        0.6804 Disaster Recovery Runbook Change: db.internal → db-replica-01.internal
    """
    if not query or not query.strip():
        return []

    # Step 1: Embed the user query using the RETRIEVAL_QUERY task type
    query_vec = embed_query(query.strip())

    # Step 2: Format the vector as a pgvector literal string
    vec_literal = "[" + ",".join(str(v) for v in query_vec) + "]"

    # Step 3: Run the cosine similarity search via the HNSW index
    # The <=> operator computes cosine distance (0 = identical, 2 = opposite)
    # We convert to similarity with:  similarity = 1 - cosine_distance
    sql = """
        SELECT
            c.id                                                  AS chunk_id,
            d.title                                               AS document_title,
            d.source                                              AS document_source,
            COALESCE(c.heading, '')                               AS heading,
            c.content                                             AS content,
            ROUND((1 - (c.embedding <=> %s::vector))::numeric, 6) AS similarity
        FROM   chunks   c
        JOIN   documents d ON d.id = c.document_id
        WHERE  (1 - (c.embedding <=> %s::vector)) >= %s
        ORDER  BY c.embedding <=> %s::vector
        LIMIT  %s
    """

    with get_conn() as conn:
        rows = conn.execute(
            sql,
            (vec_literal, vec_literal, threshold, vec_literal, top_k),
        ).fetchall()

    # Step 4: Map raw DB rows to typed ChunkResult objects
    results: list[ChunkResult] = [
        ChunkResult(
            chunk_id=row[0],
            document_title=row[1],
            document_source=row[2],
            heading=row[3],
            content=row[4],
            similarity=float(row[5]),
        )
        for row in rows
    ]

    return results


def format_context_for_llm(chunks: list[ChunkResult]) -> list[str]:
    """
    Convert retrieved ChunkResult objects into formatted context strings
    ready to be injected into the LLM prompt.

    Each string includes the source citation (document + section) so the
    LLM can reference it in the answer.

    Args:
        chunks: The list of ChunkResult objects from retrieve().

    Returns:
        A list of formatted context strings, one per chunk.
    """
    context_strings: list[str] = []

    for chunk in chunks:
        # Build a source citation line
        citation = f"Source: {chunk.document_title}"
        if chunk.heading:
            citation += f" › {chunk.heading}"

        formatted = f"{citation}\n\n{chunk.content}"
        context_strings.append(formatted)

    return context_strings


def retrieve_and_format(
    query: str,
    top_k: int = 5,
    threshold: float = SIMILARITY_THRESHOLD,
) -> tuple[list[ChunkResult], list[str]]:
    """
    Convenience wrapper that retrieves chunks AND formats them for the LLM in one call.

    Args:
        query:     The user's natural-language question.
        top_k:     Max chunks to retrieve.
        threshold: Minimum similarity threshold.

    Returns:
        A tuple of (chunk_results, formatted_context_strings).
        chunk_results   → used in the API response as source citations
        formatted_context_strings → fed into chat_completion() as context_chunks
    """
    chunks = retrieve(query, top_k=top_k, threshold=threshold)
    context = format_context_for_llm(chunks)
    return chunks, context
