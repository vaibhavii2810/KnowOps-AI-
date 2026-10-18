# FLOW.md — How execution moves through the code

What runs first, what calls what, and in which order. **Any change that adds, removes or renames an
entry point, route, module or call chain must update this file in the same change** (rule in `AGENTS.md`).

Notation: `→` calls · `[DB]` opens a Postgres connection via `app.db.get_conn()` · `[Gemini]` calls the Gemini API.

## 1. Entry points

| Trigger | Entry | What happens next |
|---|---|---|
| HTTP request on Vercel | `vercel.json` rewrites `/(.*)` → `/api/index` | `api/index.py` puts the repo root on `sys.path` and imports `app.main.app` (sprint-2 branch) |
| Local dev | `uvicorn app.main:app --reload` | Same `app` object |
| Browser | `GET /` | `serve_dashboard()` returns `static/index.html`, which loads `static/js/app.js` (§6) |
| Vercel Cron | Daily `0 3 * * *` (03:00 UTC) → `/cron/reindex` | `api_cron_reindex()` (⚠️ cron sends GET, route is POST — see Known issues) |
| Ingestion | `python scripts/ingest.py` | `main()` in `scripts/ingest.py` (§5) |
| DB setup | `scripts/init_db.sql`, run by hand in Neon | Creates the `vector` extension, 5 tables and the HNSW index |
| Tests | `pytest` | `tests/*.py` |

## 2. Startup (cold start) — import order

`app/main.py` imports, top to bottom:

1. `app.agent` → `app.crm` → `app.db` → `app.config`
   → **`settings = Settings()` reads env vars / `.env` — the only time config is read**
   → `app.llm` (loads the `google.genai` SDK; no client yet) → `app.rag` → `app.schemas`
2. `app.auth` → creates `security_bearer = HTTPBearer(auto_error=False)`
3. `app.config`, `app.crm`, `app.db`, `app.llm`, `app.rag`, `app.schemas` — already loaded, cached

Then `app/main.py` itself runs:

4. `app = FastAPI(...)` — Swagger at `/docs`, ReDoc at `/redoc`
5. `CORSMiddleware` (all origins)
6. Mounts `/static` if `static/` exists
7. The route decorators register 16 routes

Nothing touches Postgres or Gemini at startup. DB connections open per call. The Gemini client is
created on first use by `llm.get_client()` (`lru_cache` → one client per process).

## 3. Every request

`CORSMiddleware` → route match → dependencies (`get_current_user_required` on every route below except
`/health`, `/auth/login`, `GET /`, `/static/*`, `/docs`, `/redoc`, `/cron/reindex` — Phase 5.4, D-022 →
`security_bearer` reads `Authorization: Bearer <jwt>`, missing/invalid/expired → 401) → request body
validated against `app/schemas.py` (422 if invalid) → route handler → response serialised through its
`response_model`.

## 4. Route call chains

### `GET /health`
```
health()
  → [DB] COUNT(*) documents, COUNT(*) chunks
  → HealthResponse            (503 if the DB call fails)
```

### `POST /auth/login`
```
login(LoginRequest)
  → auth.verify_operator_credentials(username, password)   compare_digest vs settings.app_username / app_password
  → auth.create_access_token({"sub", "role"}, 60 min)      jwt.encode HS256 + exp / iat / iss="knowops-ai"
  → TokenResponse             (401 if credentials are wrong)
```

### `GET /auth/me`
```
Depends(auth.get_current_user_required)
  → auth.decode_access_token(token)    (401 if missing / expired / invalid)
→ get_me() → UserInfo
```

### `POST /ask` — the main RAG path
```
ask(AskRequest, Depends(auth.get_current_user_required))   ← Phase 5.4: now required, was optional
  1. [DB] create a conversation, or load its history (first 8 messages, oldest first)
  2. rag.retrieve_and_format(question, top_k)
       → rag.retrieve(query, top_k, threshold=0.55)
            → llm.embed_query → llm.embed_text(task_type="RETRIEVAL_QUERY")
                 → llm.get_client() → [Gemini] embed_content, 768 dims
                   (retries 429/503 up to 3×, waiting 2s / 4s / 8s)
            → [DB] cosine search: 1 - (embedding <=> query) >= 0.55, nearest first, LIMIT top_k (HNSW index)
            → list[ChunkResult]
       → rag.format_context_for_llm(chunks) → "Source: <title> › <heading>\n\n<content>" per chunk
     (503 if retrieval fails)
  3. llm.chat_completion(question, context_strings, history)
       → grounded prompt = context block + question, after the history turns
       → [Gemini] generate_content (SYSTEM_INSTRUCTION, temperature 0.2, max 1024 tokens, retries 429/503 ×2)
     (503 if generation fails)
  4. [DB] INSERT the user + model messages (a failure here is printed, not raised)
  5. AskResponse(answer, sources=chunks, question, conversation_id)
```

### Conversations (all `Depends(auth.get_current_user_required)` — Phase 5.4)
```
POST /conversations         → create_conversation()          → [DB] INSERT conversations
GET  /conversations         → list_conversations_endpoint()  → [DB] conversations LEFT JOIN messages (counts)
GET  /conversations/{id}    → get_conversation_endpoint()    → [DB] conversation + messages (404 if missing)
```

### Tickets (mock CRM) (all `Depends(auth.get_current_user_required)` — Phase 5.4)
```
POST  /tickets         → api_create_ticket()    → crm.create_ticket()        → [DB] INSERT (priority forced into P1–P4, default P2)
GET   /tickets         → api_list_tickets()     → crm.list_tickets()         → [DB] SELECT, P1 first, newest first
GET   /tickets/stats   → api_get_ticket_stats() → crm.get_crm_stats()        → [DB] 5 COUNT queries
GET   /tickets/{id}    → api_get_ticket()       → crm.get_ticket()           → [DB] (404 if None)
PATCH /tickets/{id}    → api_update_ticket()    → crm.update_ticket_status() → [DB] UPDATE (bad status → 400, missing → 404)
```
`/tickets/stats` is registered before `/tickets/{ticket_id}` — keep that order or "stats" is parsed as an id.

### `POST /agent/chat` — ReAct loop (`Depends(auth.get_current_user_required)` — Phase 5.4)
```
api_agent_chat(AgentChatRequest) → agent.run_agent(prompt, max_steps)
  for step in 1..max_steps:
    → llm.get_client() → [Gemini] generate_content (JSON mode, AGENT_SYSTEM_PROMPT, temperature 0.1)
    → json.loads → {thought, action, args, is_final, final_answer}
    → stop if is_final, no action, or unknown action (a Gemini or JSON error also ends the loop)
    → else AVAILABLE_TOOLS[action](**args):
         lookup_runbook          → rag.retrieve(top_k=3, threshold=0.50)  → [Gemini] + [DB]
         get_ticket              → crm.get_ticket                         → [DB]
         update_ticket           → crm.update_ticket_status               → [DB]
         run_system_diagnostics  → "database": [DB] SELECT 1 + counts · other components: canned JSON (simulated)
         execute_recovery_action → canned JSON (simulated — nothing is executed)
    → thought / action / observation appended to the text transcript for the next step
  if no step gave a final answer → [Gemini] one summary call
→ {task, total_steps, steps, resolution} → AgentChatResponse
```

### `POST /agent/triage/{ticket_id}` (`Depends(auth.get_current_user_required)` — Phase 5.4)
```
api_agent_triage(ticket_id) → agent.triage_ticket_with_agent(ticket_id)
  → crm.get_ticket            (missing → ValueError → 404)
  → builds a goal prompt from the ticket
  → agent.run_agent(prompt, max_steps=4)     (same loop as above)
  → crm.get_ticket again (state after the agent's updates)
→ AgentTriageResponse         (any other error → 500)
```

### `/cron/reindex`
```
api_cron_reindex(Authorization header)
  → if CRON_SECRET is set and header ≠ "Bearer <secret>": 401, but only when VERCEL_ENV == "production"
  → glob data/docs/**/*.md (counted only)
  → [DB] COUNT documents, chunks
→ CronReindexResponse
```
It does **not** call the ingestion code (Known issue, Phase 9.1).

### `GET /`
```
serve_dashboard() → static/index.html (inline fallback HTML if missing); assets served from the /static mount
```

## 5. Offline ingestion — `scripts/ingest.py`

```
main()
  → argparse: --file, --reset, --quiet
  → collect data/docs/**/*.md (or the single --file)
  → [DB] ONE connection for the whole run (--reset deletes all chunks + documents first)
  → for each file: ingest_file(path, conn)
       → extract_frontmatter → extract_title_from_markdown (fallback: filename)
       → source = path relative to repo root, POSIX style
       → upsert_document(source, title) → delete_existing_chunks(doc_id)   ← why re-runs don't duplicate
       → make_chunks(body)
            → split_by_headings (#, ##, ###)
            → pack_paragraphs → split_units → split_text_with_overlap (only for single lines > 500 chars, 50 overlap)
            → drop pieces shorter than 80 chars
       → for each chunk: llm.embed_document → embed_text("RETRIEVAL_DOCUMENT") → [Gemini]
                         → insert_chunk → sleep 0.5 s (free-tier rate limit)
  → print summary
```

## 6. Browser console — `static/js/app.js`

```
DOMContentLoaded → init()
  → setupEventListeners()
  → checkHealth()              GET /health
  → restoreAuthSession()       GET /auth/me   (JWT from localStorage "knowops_jwt")
  → loadRecentConversations()  GET /conversations?limit=15

User actions (Phase 5.4: `authHeaders()` attaches the JWT; each of these bails out to the login modal /
shows a "sign in" message instead of firing the request when `jwtToken` is null, since the route now 401s):
  ask question       → submitQuery()               POST /ask                           (requires JWT)
  log in             → handleLoginSubmit()         POST /auth/login → loadRecentConversations()
  open conversation  → switchConversation()        GET /conversations/{id}             (requires JWT)
  open CRM tab       → loadCrmData()               GET /tickets/stats + GET /tickets   (requires JWT)
  create ticket      → handleCreateTicketSubmit()  POST /tickets                       (requires JWT)
  triage ticket      → executeAgentTriage()        POST /agent/triage/{id}             (requires JWT)
  sign out           → logout()                    clears jwtToken + session list
```
Every call above now sends `Authorization: Bearer <jwt>` via `authHeaders()`.

## 7. Module dependencies

```
api/index.py       → app.main
app.main           → app.agent, app.auth, app.config, app.crm, app.db, app.llm, app.rag, app.schemas
app.agent          → app.crm, app.db, app.llm, app.rag
app.rag            → app.db, app.llm, app.schemas
app.crm            → app.db
app.auth           → app.config
app.llm            → app.config
app.db             → app.config
scripts/ingest.py  → app.db, app.llm
```

## 8. Which code touches which table

| Table | Written by | Read by |
|---|---|---|
| `documents` | `scripts/ingest.py` | `rag.retrieve` (join); counted by `/health`, `/cron/reindex`, agent diagnostics |
| `chunks` | `scripts/ingest.py` | `rag.retrieve` (vector search); counted as above |
| `tickets` | `crm.py` (via `/tickets*` and agent tools) | `crm.py` |
| `conversations` | `/ask`, `POST /conversations` | `/ask`, `GET /conversations*` |
| `messages` | `/ask` | `/ask` (history), `GET /conversations*` |
