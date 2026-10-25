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


# ---------------------------------------------------------------------------
# CRM Ticket Schemas (Phase 3.1)
# ---------------------------------------------------------------------------

class TicketCreateRequest(BaseModel):
    """Payload for POST /tickets."""

    subject: str = Field(
        ...,
        min_length=3,
        max_length=200,
        description="Brief incident subject line.",
        examples=["Primary Database Unreachable: Failover Required"],
    )
    description: str = Field(
        ...,
        min_length=5,
        max_length=5000,
        description="Detailed incident symptoms or stack trace.",
        examples=["Database connection pool exhausted. Ingress reporting 502 Bad Gateway."],
    )
    priority: str = Field(
        default="P2",
        description="Incident priority level: P1, P2, P3, or P4.",
        examples=["P1"],
    )


class TicketUpdateRequest(BaseModel):
    """Payload for PATCH /tickets/{id}."""

    status: str = Field(
        ...,
        description="New ticket status: open, in_progress, resolved, closed.",
        examples=["resolved"],
    )
    resolution_notes: Optional[str] = Field(
        default=None,
        description="Notes or steps taken by operator/agent to resolve.",
        examples=["Promoted db-replica-01.internal to primary. Scaled pods."],
    )


class TicketResponse(BaseModel):
    """Response payload representing an incident ticket."""

    id: int = Field(description="Ticket primary key ID.")
    subject: str = Field(description="Incident subject.")
    description: str = Field(description="Incident description.")
    priority: str = Field(description="Priority: P1, P2, P3, P4.")
    status: str = Field(description="Status: open, in_progress, resolved, closed.")
    created_at: str = Field(description="Creation timestamp.")
    updated_at: str = Field(description="Last update timestamp.")
    resolution_notes: Optional[str] = Field(default=None, description="Resolution notes if resolved.")


class CRMStatsResponse(BaseModel):
    """Response payload for GET /tickets/stats."""

    total_tickets: int
    open: int
    in_progress: int
    resolved: int
    active_p1_incidents: int


# ---------------------------------------------------------------------------
# Autonomous Agent Schemas (Phase 3.2)
# ---------------------------------------------------------------------------

class AgentChatRequest(BaseModel):
    """Payload for POST /agent/chat."""

    prompt: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="Autonomous instruction for the SRE agent.",
        examples=["Investigate why the worker pod is crashing and propose a fix."],
    )
    max_steps: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum ReAct reasoning steps before synthesizing a final resolution.",
    )


class AgentStep(BaseModel):
    """A single ReAct reasoning/action step."""

    step: int
    thought: str = Field(description="Internal reasoning about current state and next move.")
    action: Optional[str] = Field(default=None, description="Tool invoked.")
    args: Optional[dict] = Field(default=None, description="Arguments supplied to the tool.")
    observation: Optional[str] = Field(default=None, description="Result returned from the tool.")
    final_answer: Optional[str] = Field(default=None, description="Synthesized resolution if final step.")


class AgentChatResponse(BaseModel):
    """Response payload for POST /agent/chat."""

    task: str = Field(description="Echo of the original operational task.")
    total_steps: int = Field(description="Number of ReAct steps executed.")
    steps: list[dict] = Field(description="Step-by-step reasoning and tool call trace.")
    resolution: str = Field(description="Comprehensive final resolution report.")


class AgentTriageResponse(BaseModel):
    """Response payload for POST /agent/triage/{ticket_id}."""

    ticket_id: int
    initial_ticket: dict
    updated_ticket: dict
    triage_trace: list[dict]
    resolution_summary: str


# ---------------------------------------------------------------------------
# Cron & Maintenance Schemas (Phase 3.3)
# ---------------------------------------------------------------------------

class CronReindexResponse(BaseModel):
    """Response payload for GET /cron/reindex (Phase 9.1)."""

    status: str
    documents_total: int = Field(description="Markdown files found in data/docs/.")
    documents_reindexed: int = Field(description="Files that were new or had changed content.")
    documents_unchanged: int = Field(description="Files skipped because their content hash matched — no re-embedding needed.")
    chunks_embedded: int = Field(description="Chunks embedded via Gemini in this run (0 if nothing changed).")
    message: str


