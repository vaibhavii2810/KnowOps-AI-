"""
app/llm.py  –  Phase 2.1
Gemini client initialisation, embedding generation, and chat completion helpers.
"""

import time
from functools import lru_cache
from typing import Optional

from google import genai
from google.genai import types

from app.config import settings


# ---------------------------------------------------------------------------
# Client — module-level singleton (one HTTP connection pool per process)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    """Return a cached Gemini client, initialised with the configured API key."""
    return genai.Client(api_key=settings.gemini_api_key)


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def embed_text(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
    """
    Embed a single string using gemini-embedding-001.

    Args:
        text:      The string to embed.
        task_type: Gemini task-type hint.
                   Use "RETRIEVAL_DOCUMENT" when indexing docs,
                   "RETRIEVAL_QUERY"    when embedding user queries.

    Returns:
        A list of floats with length settings.embed_dim (768 by default).
    """
    client = get_client()
    for attempt in range(4):
        try:
            response = client.models.embed_content(
                model=settings.gemini_embed_model,
                contents=text,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=settings.embed_dim,  # truncate to 768 for pgvector HNSW
                ),
            )
            return response.embeddings[0].values
        except Exception as exc:
            err_code = getattr(exc, 'code', getattr(exc, 'status_code', None))
            if attempt < 3 and (err_code in (429, 503) or '503' in str(exc) or '429' in str(exc)):
                wait = 2 ** (attempt + 1)
                time.sleep(wait)
                continue
            raise


def embed_query(text: str) -> list[float]:
    """Convenience wrapper for query-time embedding."""
    return embed_text(text, task_type="RETRIEVAL_QUERY")


def embed_document(text: str) -> list[float]:
    """Convenience wrapper for document-indexing embedding."""
    return embed_text(text, task_type="RETRIEVAL_DOCUMENT")


# ---------------------------------------------------------------------------
# Chat completion
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTION = (
    "You are an expert technical-support assistant for KnowOps. "
    "Answer the user's question using ONLY the context sections provided. "
    "If the answer is not found in the context, say: "
    "'I don't have enough information in the knowledge base to answer that.' "
    "Always be concise, accurate, and professional. "
    "Cite the source document title when it is available."
)


def chat_completion(
    user_message: str,
    context_chunks: list[str],
    history: Optional[list[dict]] = None,
    system_instruction: str = SYSTEM_INSTRUCTION,
) -> str:
    """
    Generate a grounded answer from Gemini 2.5 Flash.

    Args:
        user_message:    The end-user's question.
        context_chunks:  Retrieved knowledge-base excerpts (RAG context).
        history:         Optional prior conversation turns
                         [{"role": "user"|"model", "content": "..."}].
        system_instruction: Override the default system prompt if needed.

    Returns:
        The model's text reply as a plain string.
    """
    client = get_client()

    # Build the grounded prompt
    context_block = "\n\n---\n\n".join(context_chunks) if context_chunks else "No context available."
    grounded_user_msg = (
        f"### Context from the knowledge base\n\n{context_block}\n\n"
        f"### User question\n\n{user_message}"
    )

    # Build conversation turns
    contents: list[types.Content] = []

    if history:
        for turn in history:
            role = "user" if turn["role"] == "user" else "model"
            contents.append(
                types.Content(role=role, parts=[types.Part(text=turn["content"])])
            )

    # Append the current grounded turn
    contents.append(
        types.Content(role="user", parts=[types.Part(text=grounded_user_msg)])
    )

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=settings.gemini_chat_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,        # low temperature → factual, consistent
                    max_output_tokens=1024,
                ),
            )
            return response.text or ""
        except Exception as exc:
            # Retry on transient 503 / 429 errors with exponential backoff
            err_code = getattr(exc, 'code', getattr(exc, 'status_code', None))
            if attempt < 2 and (err_code in (429, 503) or '503' in str(exc) or '429' in str(exc)):
                wait = 2 ** (attempt + 1)
                time.sleep(wait)
                continue
            raise
