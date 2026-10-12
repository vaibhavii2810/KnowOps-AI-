"""
app/main.py  –  Phase 2.5
KnowOps AI — Production FastAPI Application & Operations Platform.

Endpoints:
    GET  /                          → Operations Console SPA (Web Frontend)
    GET  /health                    → Database & knowledge base health check
    POST /auth/login                → Operator JWT authentication
    GET  /auth/me                   → Current authenticated operator session
    POST /conversations             → Create a new conversation session
    GET  /conversations             → List recent conversations
    GET  /conversations/{id}        → Get conversation history & messages
    POST /ask                       → RAG Q&A with multi-turn memory & citations
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.auth import (
    create_access_token,
    get_current_user_optional,
    get_current_user_required,
    verify_operator_credentials,
)
from app.config import settings
from app.db import get_conn
from app.llm import chat_completion
from app.rag import retrieve_and_format
from app.schemas import (
    AskRequest,
    AskResponse,
    ConversationCreateResponse,
    ConversationDetail,
    HealthResponse,
    LoginRequest,
    MessageRecord,
    TokenResponse,
    UserInfo,
)

# ---------------------------------------------------------------------------
# App initialisation
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="KnowOps AI — IT Operations Knowledge Platform",
    description=(
        "Production AI-powered knowledge base and operations assistant. "
        "Ask natural-language questions about IT runbooks, incident playbooks, "
        "and Kubernetes infrastructure — get grounded, cited answers in seconds."
    ),
    version="0.2.5",
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
def list_conversations(limit: int = 20) -> list[dict]:
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
def get_conversation(conversation_id: int) -> ConversationDetail:
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

    1. Retrieves recent conversation history if conversation_id is supplied.
    2. Performs vector retrieval over pgvector HNSW index.
    3. Synthesizes a grounded answer using Gemini LLM.
    4. Persists the user question & answer into PostgreSQL messages table.
    5. Returns grounded answer and source citations.
    """
    conv_id = request.conversation_id
    history: list[dict] = []

    # ── Step 1: Manage conversation session ──────────────────────────────────
    with get_conn() as conn:
        if conv_id is not None:
            # Check if conversation exists
            exists = conn.execute(
                "SELECT id FROM conversations WHERE id = %s", (conv_id,)
            ).fetchone()
            if not exists:
                # Create it if it doesn't exist
                row = conn.execute(
                    "INSERT INTO conversations DEFAULT VALUES RETURNING id"
                ).fetchone()
                conv_id = row[0]
            else:
                # Load last 8 turns of history
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
            # Create a new conversation thread
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
        # Log persistence failure, but don't fail the user response
        print(f"[Warning] Failed to persist message history: {exc}")

    # ── Step 5: Return structured response with citations ────────────────────
    return AskResponse(
        answer=answer,
        sources=chunks,
        question=request.question,
        conversation_id=conv_id,
    )
