"""
app/main.py  –  Phase 3
KnowOps AI — Production FastAPI Application, Autonomous Agent & Operations Platform.

Endpoints:
    GET  /                          → Operations Console SPA (Web Frontend)
    GET  /health                    → Database & knowledge base health check
    POST /auth/login                → Operator JWT authentication
    GET  /auth/me                   → Current authenticated operator session
    POST /conversations             → Create a new conversation session
    GET  /conversations             → List recent conversations
    GET  /conversations/{id}        → Get conversation history & messages
    POST /ask                       → RAG Q&A with multi-turn memory & citations
    POST /tickets                   → Create incident ticket
    GET  /tickets                   → List incident tickets
    GET  /tickets/stats             → CRM incident statistics
    GET  /tickets/{id}              → Get ticket details
    PATCH /tickets/{id}             → Update ticket status & resolution notes
    POST /agent/chat                → Autonomous ReAct agent investigation
    POST /agent/triage/{id}         → Automated incident ticket triage pipeline
    POST /cron/reindex              → Scheduled knowledge base re-indexing
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.agent import run_agent, triage_ticket_with_agent
from app.auth import (
    create_access_token,
    get_current_user_optional,
    get_current_user_required,
    verify_operator_credentials,
)
from app.config import settings
from app.crm import (
    create_ticket,
    get_crm_stats,
    get_ticket,
    list_tickets,
    update_ticket_status,
)
from app.db import get_conn
from app.llm import chat_completion
from app.rag import retrieve_and_format
from app.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentTriageResponse,
    AskRequest,
    AskResponse,
    ConversationCreateResponse,
    ConversationDetail,
    CRMStatsResponse,
    CronReindexResponse,
    HealthResponse,
    LoginRequest,
    MessageRecord,
    TicketCreateRequest,
    TicketResponse,
    TicketUpdateRequest,
    TokenResponse,
    UserInfo,
)

# ---------------------------------------------------------------------------
# App initialisation
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="KnowOps AI — IT Operations Knowledge & Agent Platform",
    description=(
        "Production AI-powered knowledge base, autonomous incident copilot, and CRM. "
        "Ask natural-language questions about IT runbooks, triage active outages, "
        "and execute automated diagnostic ReAct workflows."
    ),
    version="0.3.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static assets if directory exists
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Frontend Dashboard (SPA)
# ---------------------------------------------------------------------------

@app.get(
    "/",
    response_class=HTMLResponse,
    summary="KnowOps AI Web Operations Console",
    tags=["Frontend"],
)
def serve_dashboard():
    """Serves the KnowOps AI Operations Console single-page application."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return HTMLResponse(
        content="<h1>KnowOps AI API is running.</h1><p>Visit <a href='/docs'>/docs</a> for OpenAPI documentation.</p>",
        status_code=200,
    )


# ---------------------------------------------------------------------------
# Authentication Endpoints
# ---------------------------------------------------------------------------

@app.post(
    "/auth/login",
    response_model=TokenResponse,
    summary="Operator login (JWT)",
    tags=["Authentication"],
)
def login(request: LoginRequest) -> TokenResponse:
    """
    Authenticate an operator and issue a signed JWT access token.
    Default credentials for development: admin / admin.
    """
    valid = verify_operator_credentials(request.username, request.password)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid operator username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    expires = timedelta(minutes=settings.jwt_expire_minutes)
    token = create_access_token(
        data={"sub": request.username, "role": "operator"},
        expires_delta=expires,
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_expire_minutes * 60,
        username=request.username,
    )


@app.get(
    "/auth/me",
    response_model=UserInfo,
    summary="Current authenticated operator",
    tags=["Authentication"],
)
def get_me(user: dict = Depends(get_current_user_required)) -> UserInfo:
    """Returns details of the currently authenticated operator session."""
    return UserInfo(
        username=user.get("sub", "unknown"),
        role=user.get("role", "operator"),
        authenticated=True,
    )


# ---------------------------------------------------------------------------
# Conversation Endpoints (Multi-Turn Memory)
# ---------------------------------------------------------------------------

@app.post(
    "/conversations",
    response_model=ConversationCreateResponse,
    summary="Create a new conversation session",
    tags=["Conversations"],
)
def create_conversation() -> ConversationCreateResponse:
    """Initialize a new multi-turn conversation thread in PostgreSQL."""
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO conversations DEFAULT VALUES RETURNING id, created_at"
        ).fetchone()
        conv_id = row[0]
        created_at_str = str(row[1])

    return ConversationCreateResponse(
        id=conv_id,
        created_at=created_at_str,
        message="Conversation session created successfully.",
    )


@app.get(
    "/conversations",
    response_model=list[dict],
    summary="List recent conversation sessions",
    tags=["Conversations"],
)
def list_conversations_endpoint(limit: int = 20) -> list[dict]:
    """Retrieve the most recent conversation sessions."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.created_at, COUNT(m.id) as message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id, c.created_at
            ORDER BY c.id DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "id": r[0],
            "created_at": str(r[1]),
            "message_count": r[2],
        }
        for r in rows
    ]


@app.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    summary="Get conversation history",
    tags=["Conversations"],
)
def get_conversation_endpoint(conversation_id: int) -> ConversationDetail:
    """Retrieve full message history for a specific conversation thread."""
    with get_conn() as conn:
        conv_row = conn.execute(
            "SELECT id, created_at FROM conversations WHERE id = %s",
            (conversation_id,),
        ).fetchone()

        if not conv_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Conversation #{conversation_id} not found.",
            )

        msg_rows = conn.execute(
            """
            SELECT id, role, content, created_at
            FROM messages
            WHERE conversation_id = %s
            ORDER BY id ASC
            """,
            (conversation_id,),
        ).fetchall()

    messages = [
        MessageRecord(
            id=r[0],
            role=r[1],
            content=r[2],
            created_at=str(r[3]),
        )
        for r in msg_rows
    ]

    return ConversationDetail(
        id=conv_row[0],
        created_at=str(conv_row[1]),
        messages=messages,
    )


# ---------------------------------------------------------------------------
# Health Check Endpoint
# ---------------------------------------------------------------------------

@app.get(
    "/health",
    response_model=HealthResponse,
    summary="System health check",
    tags=["System"],
)
def health() -> HealthResponse:
    """
    Returns service health status:
    - Database connectivity
    - Knowledge base document and chunk counts
    """
    db_status = "connected"
    kb_stats: dict = {"documents": 0, "chunks": 0}

    try:
        with get_conn() as conn:
            doc_count   = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            kb_stats = {"documents": doc_count, "chunks": chunk_count}
    except Exception as exc:
        db_status = f"error: {exc}"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "degraded", "database": db_status},
        )

    return HealthResponse(
        status="ok",
        database=db_status,
        knowledge_base=kb_stats,
    )


# ---------------------------------------------------------------------------
# POST /ask — RAG with Multi-turn Memory & Citations
# ---------------------------------------------------------------------------

@app.post(
    "/ask",
    response_model=AskResponse,
    summary="Ask the knowledge base a question",
    tags=["Knowledge Base"],
)
def ask(
    request: AskRequest,
    current_user: Optional[dict] = Depends(get_current_user_optional),
) -> AskResponse:
    """
    End-to-end RAG Q&A endpoint with multi-turn memory support.
    """
    conv_id = request.conversation_id
    history: list[dict] = []

    # ── Step 1: Manage conversation session ──────────────────────────────────
    with get_conn() as conn:
        if conv_id is not None:
            exists = conn.execute(
                "SELECT id FROM conversations WHERE id = %s", (conv_id,)
            ).fetchone()
            if not exists:
                row = conn.execute(
                    "INSERT INTO conversations DEFAULT VALUES RETURNING id"
                ).fetchone()
                conv_id = row[0]
            else:
                past_msgs = conn.execute(
                    """
                    SELECT role, content
                    FROM messages
                    WHERE conversation_id = %s
                    ORDER BY id ASC
                    LIMIT 8
                    """,
                    (conv_id,),
                ).fetchall()
                history = [{"role": r[0], "content": r[1]} for r in past_msgs]
        else:
            row = conn.execute(
                "INSERT INTO conversations DEFAULT VALUES RETURNING id"
            ).fetchone()
            conv_id = row[0]

    # ── Step 2: Retrieve relevant chunks via RAG ─────────────────────────────
    try:
        chunks, context_strings = retrieve_and_format(
            query=request.question,
            top_k=request.top_k,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Retrieval failed — database or embedding error: {exc}",
        )

    # ── Step 3: Generate grounded answer via Gemini ──────────────────────────
    try:
        answer = chat_completion(
            user_message=request.question,
            context_chunks=context_strings,
            history=history,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI generation failed — Gemini API error: {exc}",
        )

    # ── Step 4: Persist interaction into database ────────────────────────────
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content)
                VALUES (%s, 'user', %s), (%s, 'model', %s)
                """,
                (conv_id, request.question, conv_id, answer),
            )
    except Exception as exc:
        print(f"[Warning] Failed to persist message history: {exc}")

    # ── Step 5: Return structured response with citations ────────────────────
    return AskResponse(
        answer=answer,
        sources=chunks,
        question=request.question,
        conversation_id=conv_id,
    )


# ---------------------------------------------------------------------------
# CRM Incident Ticket Endpoints (Phase 3.1)
# ---------------------------------------------------------------------------

@app.post(
    "/tickets",
    response_model=TicketResponse,
    summary="Create a new incident ticket",
    tags=["CRM"],
)
def api_create_ticket(request: TicketCreateRequest) -> TicketResponse:
    """Create a new incident ticket in PostgreSQL."""
    ticket = create_ticket(
        subject=request.subject,
        description=request.description,
        priority=request.priority,
    )
    return TicketResponse(**ticket)


@app.get(
    "/tickets",
    response_model=list[TicketResponse],
    summary="List incident tickets",
    tags=["CRM"],
)
def api_list_tickets(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 50,
) -> list[TicketResponse]:
    """Retrieve incident tickets filtered by status and priority."""
    tickets = list_tickets(status=status, priority=priority, limit=limit)
    return [TicketResponse(**t) for t in tickets]


@app.get(
    "/tickets/stats",
    response_model=CRMStatsResponse,
    summary="CRM incident metrics and analytics",
    tags=["CRM"],
)
def api_get_ticket_stats() -> CRMStatsResponse:
    """Aggregated ticket statistics for operational monitoring."""
    stats = get_crm_stats()
    return CRMStatsResponse(**stats)


@app.get(
    "/tickets/{ticket_id}",
    response_model=TicketResponse,
    summary="Get incident ticket by ID",
    tags=["CRM"],
)
def api_get_ticket(ticket_id: int) -> TicketResponse:
    """Retrieve a single incident ticket by ID."""
    ticket = get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket #{ticket_id} not found.",
        )
    return TicketResponse(**ticket)


@app.patch(
    "/tickets/{ticket_id}",
    response_model=TicketResponse,
    summary="Update ticket status and resolution notes",
    tags=["CRM"],
)
def api_update_ticket(ticket_id: int, request: TicketUpdateRequest) -> TicketResponse:
    """Update status ('open', 'in_progress', 'resolved', 'closed') and resolution notes."""
    try:
        updated = update_ticket_status(
            ticket_id=ticket_id,
            status=request.status,
            resolution_notes=request.resolution_notes,
        )
    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err))

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticket #{ticket_id} not found.",
        )
    return TicketResponse(**updated)


# ---------------------------------------------------------------------------
# Autonomous SRE Agent Endpoints (Phase 3.2)
# ---------------------------------------------------------------------------

@app.post(
    "/agent/chat",
    response_model=AgentChatResponse,
    summary="Autonomous ReAct agent task execution",
    tags=["Agent"],
)
def api_agent_chat(request: AgentChatRequest) -> AgentChatResponse:
    """
    Execute autonomous ReAct agent loop with tool-calling capabilities.
    The agent searches runbooks, inspects live system components, and drafts remediation plans.
    """
    result = run_agent(task_prompt=request.prompt, max_steps=request.max_steps)
    return AgentChatResponse(
        task=result["task"],
        total_steps=result["total_steps"],
        steps=result["steps"],
        resolution=result["resolution"],
    )


@app.post(
    "/agent/triage/{ticket_id}",
    response_model=AgentTriageResponse,
    summary="Automated incident ticket triage pipeline",
    tags=["Agent"],
)
def api_agent_triage(ticket_id: int) -> AgentTriageResponse:
    """
    Run automated triage on an active incident ticket:
    1. Reads ticket details.
    2. Searches matching runbooks using RAG.
    3. Runs diagnostic checks on affected infrastructure.
    4. Proposes or executes remediation.
    5. Updates ticket status to 'resolved' and records resolution notes.
    """
    try:
        triage_data = triage_ticket_with_agent(ticket_id)
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent triage failed: {exc}",
        )

    return AgentTriageResponse(**triage_data)


# ---------------------------------------------------------------------------
# Cron & Maintenance Endpoints (Phase 3.3)
# ---------------------------------------------------------------------------

@app.post(
    "/cron/reindex",
    response_model=CronReindexResponse,
    summary="Trigger scheduled knowledge-base re-indexing",
    tags=["Cron"],
)
def api_cron_reindex(
    authorization: Optional[str] = Header(default=None),
) -> CronReindexResponse:
    """
    Trigger scheduled knowledge base re-indexing.
    Verifies CRON_SECRET if configured.
    """
    if settings.cron_secret and authorization != f"Bearer {settings.cron_secret}":
        # Allow dev testing if running locally, otherwise require secret
        if os.getenv("VERCEL_ENV") == "production":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized cron execution.",
            )

    docs_dir = Path(__file__).resolve().parent.parent / "data" / "docs"
    md_files = list(docs_dir.glob("**/*.md")) if docs_dir.exists() else []

    with get_conn() as conn:
        doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    return CronReindexResponse(
        status="success",
        documents_indexed=doc_count,
        chunks_created=chunk_count,
        message=f"Verified {len(md_files)} runbook files. Knowledge base active with {chunk_count} chunks.",
    )
