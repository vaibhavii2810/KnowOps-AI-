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
    GET  /cron/reindex              → Scheduled knowledge base re-indexing (new/changed files only)
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.agent import run_agent, triage_ticket_with_agent
from app.auth import (
    create_access_token,
    get_current_user_required,
    verify_operator_credentials,
)
from app.config import ensure_secrets_are_configured, settings

ensure_secrets_are_configured()  # D-063: refuse to boot on Vercel with a default JWT_SECRET/APP_PASSWORD
from app.crm import (
    create_ticket,
    get_crm_stats,
    get_ticket,
    list_tickets,
    update_ticket_status,
)
from app.db import get_conn
from app.llm import chat_completion
from app.logs import RequestLogMiddleware, configure_logging, log_event
from app.metrics import RequestMetricsMiddleware, read_metrics
from app.rag import retrieve_and_format
from app.ratelimit import login_rate_limited, rate_limited
from scripts.ingest import reindex_knowledge_base
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
    MetricsResponse,
    PathId,
    Priority,
    MessageRecord,
    TicketCreateRequest,
    TicketResponse,
    TicketStatus,
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

configure_logging()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # D-062: auth is a Bearer token, never a cookie — no ambient credential to protect.
    # allow_credentials=True together with allow_origins=["*"] makes Starlette echo the request's own Origin
    # back as Access-Control-Allow-Origin (browsers reject a literal "*" alongside credentials) — effectively
    # trusting every origin. False here keeps the wildcard honest: a real "*", no echoed origin, no credentials
    # header at all.
    allow_methods=["*"],
    allow_headers=["*"],
)
# Added last, so it is the outermost middleware: it times and logs everything, CORS preflights included.
app.add_middleware(RequestLogMiddleware)
# Added after RequestLogMiddleware, so it is the outermost layer: it times the whole stack, and its own database
# write happens after the request log line, so counting a request never inflates that request's logged latency.
app.add_middleware(RequestMetricsMiddleware)

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
def login(
    request: LoginRequest,
    _rate_limit: None = Depends(login_rate_limited),
) -> TokenResponse:
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
def create_conversation(
    current_user: dict = Depends(get_current_user_required),
) -> ConversationCreateResponse:
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
def list_conversations_endpoint(
    limit: int = Query(default=20, ge=1, le=100, description="Max sessions to return (1–100)."),
    current_user: dict = Depends(get_current_user_required),
) -> list[dict]:
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
def get_conversation_endpoint(
    conversation_id: PathId,
    current_user: dict = Depends(get_current_user_required),
) -> ConversationDetail:
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
        with get_conn(retry=False) as conn:  # fail fast: this endpoint exists to report an outage
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
# GET /metrics — request count, latency and error rate (Phase 12.4, D-046)
# ---------------------------------------------------------------------------

@app.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Request count, average latency and error rate",
    tags=["System"],
)
def metrics(
    hours: int = Query(default=24, ge=1, le=168, description="Window: the current hour plus the hours before it (1–168)."),
    current_user: dict = Depends(get_current_user_required),
) -> MetricsResponse:
    """
    Totals and a per-route breakdown over the last `hours` hours, counted across all serverless instances.
    Error rate is the share of responses with a 5xx status; 4xx responses are counted separately.
    """
    try:
        return MetricsResponse(**read_metrics(hours))
    except Exception as exc:
        log_event("metrics_read_failed", "error", error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metrics are unavailable — the database could not be read.",
        )


# ---------------------------------------------------------------------------
# POST /ask — RAG with Multi-turn Memory & Citations
# ---------------------------------------------------------------------------

HISTORY_LIMIT = 8  # most recent messages sent to the model as conversation context


def _recent_history(conn, conversation_id: int, limit: int = HISTORY_LIMIT) -> list[dict]:
    """
    The last `limit` messages of a conversation, oldest first (D-058, 2026-11-10 — was the *first*
    `limit` messages, ORDER BY id ASC LIMIT N, so a conversation past that length never saw recent
    turns). Pulled out as its own function so it can be tested directly against real Postgres
    (`tests/test_ask_integration.py`'s @pytest.mark.live test) without a full /ask round trip — the
    offline MemoryDB fake matches this query by a text fragment, not by executing real SQL, so it
    cannot by itself prove the ORDER BY/LIMIT shape is correct (D-040).
    """
    rows = conn.execute(
        """
        SELECT role, content FROM (
            SELECT id, role, content
            FROM messages
            WHERE conversation_id = %s
            ORDER BY id DESC
            LIMIT %s
        ) AS recent
        ORDER BY id ASC
        """,
        (conversation_id, limit),
    ).fetchall()
    return [{"role": r[0], "content": r[1]} for r in rows]


def _build_retrieval_query(question: str, history: list[dict]) -> str:
    """
    Fold the most recent user turn into the retrieval query (bug #22, external bug report, Medium, D-075).

    retrieve() only ever saw the new question on its own, so a pronoun-style follow-up ("what is the first
    step of that procedure?") embeds to something generic and misses the runbook section the conversation is
    actually about — confirmed live: that question alone, right after asking about database failover, scored
    its highest matches (0.65-0.68) against unrelated "first response"/"triage" sections instead of the
    failover procedure, and the model correctly refused given that context. Only the retrieval query changes
    here — chat_completion() still gets the real question and the full history separately, so the answer and
    what it's grounded in stay accurate to what was actually asked; this only widens what gets found.
    """
    if not history:
        return question
    last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
    if not last_user:
        return question
    return f"{last_user} {question}"


@app.post(
    "/ask",
    response_model=AskResponse,
    summary="Ask the knowledge base a question",
    tags=["Knowledge Base"],
)
def ask(
    request: AskRequest,
    current_user: dict = Depends(rate_limited("ask")),
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
                history = _recent_history(conn, conv_id)
        else:
            row = conn.execute(
                "INSERT INTO conversations DEFAULT VALUES RETURNING id"
            ).fetchone()
            conv_id = row[0]

    # ── Step 2: Retrieve relevant chunks via RAG ─────────────────────────────
    try:
        chunks, context_strings = retrieve_and_format(
            query=_build_retrieval_query(request.question, history),
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
        log_event("history_persist_failed", "warning", conversation_id=conv_id, error_type=type(exc).__name__)

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
def api_create_ticket(
    request: TicketCreateRequest,
    current_user: dict = Depends(get_current_user_required),
) -> TicketResponse:
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
    status: Optional[TicketStatus] = Query(default=None, description="Filter: open, in_progress, resolved, closed."),
    priority: Optional[Priority] = Query(default=None, description="Filter: P1, P2, P3, P4."),
    limit: int = Query(default=50, ge=1, le=200, description="Max tickets to return (1–200)."),
    current_user: dict = Depends(get_current_user_required),
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
def api_get_ticket_stats(
    current_user: dict = Depends(get_current_user_required),
) -> CRMStatsResponse:
    """Aggregated ticket statistics for operational monitoring."""
    stats = get_crm_stats()
    return CRMStatsResponse(**stats)


@app.get(
    "/tickets/{ticket_id}",
    response_model=TicketResponse,
    summary="Get incident ticket by ID",
    tags=["CRM"],
)
def api_get_ticket(
    ticket_id: PathId,
    current_user: dict = Depends(get_current_user_required),
) -> TicketResponse:
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
def api_update_ticket(
    ticket_id: PathId,
    request: TicketUpdateRequest,
    current_user: dict = Depends(get_current_user_required),
) -> TicketResponse:
    """Update status ('open', 'in_progress', 'resolved', 'closed') and resolution notes."""
    update_kwargs = {"ticket_id": ticket_id, "status": request.status}
    if "resolution_notes" in request.model_fields_set:
        # Present in the body at all — a string sets it, an explicit null clears it (D-071, bug #18).
        # Omitted entirely: don't pass it, so update_ticket_status()'s own UNSET default leaves it alone.
        update_kwargs["resolution_notes"] = request.resolution_notes
    try:
        updated = update_ticket_status(**update_kwargs)
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
def api_agent_chat(
    request: AgentChatRequest,
    current_user: dict = Depends(rate_limited("agent")),
) -> AgentChatResponse:
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
def api_agent_triage(
    ticket_id: PathId,
    current_user: dict = Depends(rate_limited("agent")),
) -> AgentTriageResponse:
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

@app.get(
    "/cron/reindex",
    response_model=CronReindexResponse,
    summary="Scheduled knowledge-base re-indexing",
    tags=["Cron"],
)
def api_cron_reindex(
    authorization: Optional[str] = Header(default=None),
) -> CronReindexResponse:
    """
    Re-runs ingestion for any new or changed files in data/docs/ (Phase 9.1).
    Unchanged files are skipped by content hash — no re-embedding, no Gemini calls.
    Requires CRON_SECRET whenever one is configured, in every environment (Phase 9.2,
    D-030 — superseding D-020's "production only" check now that this endpoint does
    real, costly work instead of just counting rows). A contributor with no
    CRON_SECRET set in their own local .env is unaffected — settings.cron_secret is
    empty by default, so nothing is enforced until it's actually configured. But a
    *deployed* instance (settings.vercel set — Vercel sets this on every Preview and
    Production build) with no CRON_SECRET configured refuses instead of silently
    allowing anyone to trigger it (D-055, closing a real finding: an unset env var in
    production used to be indistinguishable from "developer running locally").
    """
    if not settings.cron_secret:
        if settings.vercel:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="CRON_SECRET is not configured.",
            )
        # else: genuinely local dev with no secret set — unchanged, unenforced (D-030's original intent).
    elif not authorization or not secrets.compare_digest(
        # Encode to bytes first (D-068): compare_digest raises on a non-ASCII *str*, and a raw client can
        # send any byte 0-255 in a header value (ASGI decodes header bytes as latin-1) — the exact crash
        # class already found and fixed once for login (D-033). Bytes have no such restriction.
        authorization.encode("utf-8", errors="replace"),
        f"Bearer {settings.cron_secret}".encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized cron execution.",
        )

    result = reindex_knowledge_base(force=False, verbose=False)

    return CronReindexResponse(
        status="success",
        documents_total=result["documents_total"],
        documents_reindexed=result["documents_reindexed"],
        documents_unchanged=result["documents_unchanged"],
        documents_removed=result["documents_removed"],
        chunks_embedded=result["chunks_embedded"],
        message=(
            f"{result['documents_reindexed']} of {result['documents_total']} runbook file(s) "
            f"reindexed ({result['chunks_embedded']} chunks embedded); "
            f"{result['documents_unchanged']} unchanged and skipped"
            + (f"; {result['documents_removed']} removed (file deleted)." if result['documents_removed'] else ".")
        ),
    )

