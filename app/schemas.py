"""
app/schemas.py  –  Phase 2.5
Pydantic request / response models for the KnowOps AI REST API.

These schemas enforce strict input validation (FastAPI does this automatically)
and define clean, versioned response shapes for every endpoint.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Authentication Schemas (Phase 2.5)
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    """Payload for POST /auth/login."""

    username: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Operator username.",
        examples=["admin"],
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Operator password.",
        examples=["admin"],
    )


class TokenResponse(BaseModel):
    """Response returned upon successful authentication."""

    access_token: str = Field(description="Signed JWT access token.")
    token_type: str = Field(default="bearer", description="Token scheme type.")
    expires_in: int = Field(description="Token lifetime in seconds.")
    username: str = Field(description="Authenticated operator username.")


class UserInfo(BaseModel):
    """Operator details from JWT session."""

    username: str = Field(description="Operator username.")
    role: str = Field(default="operator", description="Operator role.")
    authenticated: bool = Field(default=True)


# ---------------------------------------------------------------------------
# Conversation & History Schemas (Phase 2.5)
# ---------------------------------------------------------------------------

class MessageRecord(BaseModel):
    """A single turn within a conversation thread."""

    id: int = Field(description="Message ID.")
    role: str = Field(description="Sender role: 'user' or 'model'.")
    content: str = Field(description="Message body text.")
    created_at: str = Field(description="ISO timestamp of message creation.")


class ConversationDetail(BaseModel):
    """Full detail of a conversation thread including historical messages."""

    id: int = Field(description="Conversation ID.")
    created_at: str = Field(description="ISO timestamp of conversation creation.")
    messages: list[MessageRecord] = Field(
        default_factory=list,
        description="Chronological messages in this thread.",
    )


class ConversationCreateResponse(BaseModel):
    """Response upon creating a new conversation thread."""

    id: int = Field(description="New conversation ID.")
    created_at: str = Field(description="ISO timestamp of creation.")
    message: str = Field(default="Conversation created successfully.")


# ---------------------------------------------------------------------------
# RAG / Ask endpoint schemas
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    """Payload for POST /ask — a user submitting a question to the knowledge base."""

    question: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="The natural-language question to answer from the knowledge base.",
        examples=["How do I perform a database failover?"],
    )
    conversation_id: Optional[int] = Field(
        default=None,
        description="Optional conversation ID for multi-turn memory. "
                    "Pass None (or omit) for a fresh single-turn query.",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of knowledge-base chunks to retrieve as context (1–20).",
    )


class ChunkResult(BaseModel):
    """A single retrieved knowledge-base chunk with its source metadata."""

    chunk_id: int = Field(description="Primary key of the chunk row in the database.")
    document_title: str = Field(description="Title of the source document.")
    document_source: str = Field(description="Relative file path of the source document.")
    heading: str = Field(description="Markdown section heading this chunk belongs to.")
    content: str = Field(description="The raw text content of this chunk.")
    similarity: float = Field(
        description="Cosine similarity score (0–1). Higher = more relevant.",
    )


class AskResponse(BaseModel):
    """Response payload for POST /ask."""

    answer: str = Field(description="AI-generated answer grounded in the retrieved context.")
    sources: list[ChunkResult] = Field(
        description="The knowledge-base chunks used to generate the answer, "
                    "ranked by relevance. These are the citations."
    )
    question: str = Field(description="Echo of the original question.")
    conversation_id: Optional[int] = Field(
        default=None,
        description="Conversation ID if this query was part of a multi-turn session.",
    )


# ---------------------------------------------------------------------------
# Health check schema
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Response payload for GET /health."""

    status: str = Field(description="Service status: 'ok' or 'degraded'.")
    database: str = Field(description="Database connectivity: 'connected' or error message.")
    knowledge_base: dict = Field(
        description="Knowledge base stats: document count, chunk count."
    )
