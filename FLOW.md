# FLOW.md — How execution moves through the code

What runs first, what calls what, and in which order. **Any change that adds, removes or renames an
entry point, route, module or call chain must update this file in the same change** (rule in `AGENTS.md`).

Notation: `→` calls · `[DB]` opens a Postgres connection via `app.db.get_conn()` (the *connect* step retries transient failures, except health probes which fail fast; statements never retry — D-032) · `[Gemini]` calls the Gemini API (every request times out after `GEMINI_TIMEOUT_SECONDS`, 25 s, and every call retries transient failures via `app.retry.retry_call` — D-032 — but starts no new attempt once that same time has passed, so a timed-out call is not retried — D-045).

## 1. Entry points

| Trigger | Entry | What happens next |
|---|---|---|
| HTTP request on Vercel | `vercel.json` rewrites `/(.*)` → `/api/index` | `api/index.py` puts the repo root on `sys.path` and imports `app.main.app` (sprint-2 branch) — importing `app.main` first calls `config.ensure_secrets_are_configured()`, which raises (crashing the cold start, every request 500s) if deployed (`settings.vercel` set) with `JWT_SECRET`/`APP_PASSWORD` still at their insecure defaults; a no-op everywhere else (D-063) |
| Local dev | `uvicorn app.main:app --reload` | Same `app` object |
| Browser | `GET /` | `serve_dashboard()` returns `static/index.html`, which loads `static/js/app.js` (§6) |
| Vercel Schedules | Daily `0 3 * * *` (03:00 UTC) → `GET /cron/reindex` (migrated from Vercel Cron Jobs, Phase 14.5, D-054) | `api_cron_reindex()` → `scripts.ingest.reindex_knowledge_base()` (Phase 9.1, D-029) |
| Ingestion | `python scripts/ingest.py` | `main()` in `scripts/ingest.py` → `reindex_knowledge_base()` (§5) |
| DB setup | `scripts/init_db.sql`, run by hand in Neon | Creates the `vector` extension, 5 tables and the HNSW index |
| CI | push or pull request on GitHub | `.github/workflows/tests.yml` → plain `pytest` on Python 3.11 + 3.12, no secrets, full git history (Phase 11.5, D-041) |
| Evaluation | `python -m evals` (`--url`, `--judge`, `--only`, …; Phase 13.2, D-048) | `evals.run.main()` → `golden.validate()` (exit 2 if unsound) → a client: `InProcessClient` (the real `/ask` route via `TestClient`, §4) or `HttpClient` (`/auth/login` then `/ask` over HTTP) → `scoring.score_item()` per answer (a fact is matched by `golden.fact_present()`: the fact or an accepted variant, D-049; `hallucination.find_flags()` compares the answer with the retrieved sources' titles and text, D-051) → optionally `judge.judge_answer()` ([Gemini] once per answer) → `format_summary()` (each question's latency is printed and flagged `SLOW` if over `--slow-seconds`; mean/median/p95/max over answered questions — Phase 13.3, D-050); the whole loop runs `--repeat` times, then `format_stability()` and `report.build_report()` → `report.write_report()` (atomic JSON file in `evals/reports/`, also written on Ctrl-C with `complete: false` — Phase 13.5, D-052) |
| Tests | `pytest` (`pytest.ini` skips `live`-marked tests; `pytest -m live` runs them, D-039) | `tests/*.py`; offline tests use `tests/conftest.py`'s `fake_gemini` / `fake_db` / `no_network`, which replace `genai.Client` and `psycopg.connect` at the root so `get_conn()`, `get_client()` and the rate limiter never reach a real server (Phase 11.1, D-038); `memory_db` keeps the app's tables in memory behind `fake_db`, and `db_backend` runs DB tests on it and (as `live`) on real Postgres (Phase 11.4, D-040) |

## 2. Startup (cold start) — import order

`app/main.py` imports, top to bottom:

1. `app.agent` → `app.crm` → `app.db` → `app.config`
   → **`settings = Settings()` reads env vars / `.env` — the only time config is read**
   → `app.llm` (loads the `google.genai` SDK; no client yet) → `app.rag` → `app.schemas`
2. `app.auth` → creates `security_bearer = HTTPBearer(auto_error=False)`
3. `app.config`, `app.crm`, `app.db`, `app.llm`, `app.rag`, `app.schemas` — already loaded, cached

Then `app/main.py` itself runs:

4. `app = FastAPI(...)` — Swagger at `/docs`, ReDoc at `/redoc`
5. `logs.configure_logging()` — one JSON handler on the `knowops` logger, writing to stdout (Phase 12.1, D-042)
6. `CORSMiddleware` (all origins, no credentials — D-062), then `logs.RequestLogMiddleware`, then `metrics.RequestMetricsMiddleware` — added last, so it is the outermost layer (Phase 12.4, D-046)
7. Mounts `/static` if `static/` exists
8. The route decorators register 17 routes

Nothing touches Postgres or Gemini at startup. DB connections open per call. The Gemini client is
created on first use by `llm.get_client()` (`lru_cache` → one client per process, with `HttpOptions(timeout=GEMINI_TIMEOUT_SECONDS × 1000)` ms — D-045).

## 3. Every request

`RequestMetricsMiddleware` (Phase 12.4, D-046: starts a timer; skipped when `METRICS_ENABLED` is false) →
`RequestLogMiddleware` (Phase 12.1, D-042: request id from a valid inbound `X-Request-ID` or a new uuid4, stored in a
context variable as one mutable record; timing starts) → `CORSMiddleware` → route match → dependencies (`get_current_user_required` on every route below except
`/health`, `/auth/login`, `GET /`, `/static/*`, `/docs`, `/redoc`, `/cron/reindex` — Phase 5.4, D-022 →
`security_bearer` reads `Authorization: Bearer <jwt>`, missing/invalid/expired → 401; on `/ask`, `/agent/chat` and
`/agent/triage/{id}` the dependency is `ratelimit.rate_limited(bucket)`, which authenticates first and then counts the
request — over the per-minute limit → 429 + `Retry-After`; Phase 10.5, D-036) → request body
validated against `app/schemas.py` and the routes' `Query(...)` bounds (422 if invalid — text is whitespace-stripped
before its length check and NUL bytes are refused; priority/status are case-insensitive enums; `limit` is bounded;
Phase 10.2, D-033) → route handler → response serialised through its
`response_model` → back in `RequestLogMiddleware`: `X-Request-ID` added to the response and one `request` log line
written (method, path, status, latency, `user` — set by the auth dependency via `logs.set_request_user()` — the
`tools` the agent ran via `logs.record_tool_call()`, `vercel_id`, and `error_type` on an unhandled error). Every
`log_event()` during the request (retries, rate-limiter fail-open, blocked tools, …) carries the same `request_id`.
Then, back in `RequestMetricsMiddleware` once the response is done: `metrics.route_label(scope)` picks the label (the
route template from `scope["route"]`; `(unmatched)` for unknown URLs; nothing for `/`, `/metrics`, static files, docs and
CORS preflights) and `record_request()` upserts one `request_metrics` row via `run_in_threadpool` — fail-open, with a
`metrics_unavailable` warning on error.

## 4. Route call chains

### `GET /health`
```
health()
  → [DB] get_conn(retry=False) — fails fast, no connect retries (D-032) — COUNT(*) documents, COUNT(*) chunks
  → HealthResponse            (503 if the DB call fails)
```

### `GET /metrics` (`Depends(get_current_user_required)` — Phase 12.4, D-046)
```
metrics(hours=24 [1–168]) → metrics.read_metrics(hours)
  → [DB] one reused plain connection (no pgvector setup); creates request_metrics on first use
  → SELECT method, route, SUM(requests), SUM(server_errors), SUM(client_errors), SUM(latency_ms_sum), MAX(latency_ms_max)
    FROM request_metrics WHERE hour_start >= <start of the current hour - (hours-1)h> GROUP BY method, route
  → totals + per-route rows: requests, average/max latency, server and client errors, error rate (5xx ÷ requests)
  → MetricsResponse           (503 "Metrics are unavailable" if the database cannot be read)
```

### `POST /auth/login`
```
login(LoginRequest, Depends(ratelimit.login_rate_limited))
  → [DB] per-client-IP counters BEFORE the credentials are looked at: 5 attempts/min and 30/hour, every attempt
    counted, right or wrong → 429 + Retry-After (a blocked caller learns nothing about whether a guess was right);
    IP = x-vercel-forwarded-for / x-forwarded-for, trusted only when settings.vercel is set — Vercel overwrites
    them there so clients cannot spoof them; off Vercel the real socket address is used instead (Phase 10.5,
    D-037; D-061 closed the gap where these headers were trusted everywhere)
  → auth.verify_operator_credentials(username, password)   compare_digest (as UTF-8 bytes — non-ASCII input is a 401, not a crash) vs settings.app_username / app_password
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
ask(AskRequest, Depends(ratelimit.rate_limited("ask")))   ← JWT required (Phase 5.4) + 10/min per user (Phase 10.5)
  1. [DB] create a conversation, or load its history via main._recent_history() (latest 8 messages, oldest first — D-058, was the first 8)
  2. main._build_retrieval_query(question, history) → question, with the most recent user turn prepended if
     history is non-empty (D-075, 2026-11-11 — fixes a pronoun follow-up losing retrieval context)
  3. rag.retrieve_and_format(retrieval_query, top_k)
       → rag.retrieve(query, top_k, threshold=0.65)  # D-056, 2026-11-10 — was 0.55
            → llm.embed_query → llm.embed_text(task_type="RETRIEVAL_QUERY")
                 → llm.get_client() → [Gemini] embed_content, 768 dims
                   (retry_call: up to 4 tries on 429 / 408 / any 5xx / network timeouts, exponential backoff
                    with jitter ≈ 1s / 2s / 4s — other 4xx fail fast; Phase 10.1, D-032; no new attempt after
                    GEMINI_TIMEOUT_SECONDS, so a slow call fails once instead of four times — D-045)
            → [DB] cosine search: 1 - (embedding <=> query) >= 0.65, nearest first, LIMIT top_k (HNSW index)
            → list[ChunkResult]
       → rag.format_context_for_llm(chunks) → "Source: <title> › <heading>\n\n<content>" per chunk
     (503 if retrieval fails)
  4. llm.chat_completion(question, context_strings, history)
       → chunks carrying embedded instructions are DROPPED (guardrails.find_injection); the rest are fenced as
         <untrusted_data> → grounded prompt = context block + question, after the history turns (Phase 10.3, D-034)
       → [Gemini] generate_content (SYSTEM_INSTRUCTION, temperature 0.2, max 1024 tokens; same retry_call policy as above, D-032)
     (503 if generation fails)
  5. [DB] INSERT the user + model messages (a failure here is logged as `history_persist_failed`, not raised)
  6. AskResponse(answer, sources=chunks, question, conversation_id)
```

### Conversations (all `Depends(auth.get_current_user_required)` — Phase 5.4)
```
POST /conversations         → create_conversation()          → [DB] INSERT conversations
GET  /conversations         → list_conversations_endpoint()  → [DB] conversations LEFT JOIN messages (counts) (?limit= 1–100)
GET  /conversations/{id}    → get_conversation_endpoint()    → [DB] conversation + messages (404 if missing)
```

### Tickets (mock CRM) (all `Depends(auth.get_current_user_required)` — Phase 5.4)
```
POST  /tickets         → api_create_ticket()    → crm.create_ticket()        → [DB] INSERT (priority is validated P1–P4 → 422 otherwise, default P2)
GET   /tickets         → api_list_tickets()     → crm.list_tickets()         → [DB] SELECT, P1 first, newest first
                         (?status= and ?priority= validated → 422 for unknown values; ?limit= 1–200)
GET   /tickets/stats   → api_get_ticket_stats() → crm.get_crm_stats()        → [DB] 6 COUNT queries (open,
                          in_progress, resolved, closed, total, active P1 — D-065 added closed)
GET   /tickets/{id}    → api_get_ticket()       → crm.get_ticket()           → [DB] (404 if None)
PATCH /tickets/{id}    → api_update_ticket()    → crm.update_ticket_status() → [DB] UPDATE (bad status → 422 at validation, was 400; missing → 404)
```
`/tickets/stats` is registered before `/tickets/{ticket_id}` — keep that order or "stats" is parsed as an id.

### `POST /agent/chat` — ReAct loop (`Depends(ratelimit.rate_limited("agent"))` — JWT required, 5/min per user, shared with triage)
```
api_agent_chat(AgentChatRequest) → agent.run_agent(prompt, max_steps)
  run_agent() starts a timer and a `run` record (outcome "completed"), then calls _run_agent_loop() — and in a
  `finally`, even on a crash, writes one `agent_run` log event (Phase 12.2, D-043, see the end of this block)
  for step in 1..max_steps:
    → llm.get_client() → [Gemini] generate_content (JSON mode, AGENT_SYSTEM_PROMPT, temperature 0.1)
      (each call goes through retry_call for 429/5xx/timeouts, D-032; separately retries up to 3x if
       resp.text is empty, e.g. finish_reason=MALFORMED_RESPONSE — D-026;
       exhausted retries or any other exception → non-blank fallback final_answer, is_final=True, and the run's
       outcome becomes "generation_error" with the error type and step)
    → json.loads → {thought, action, args, is_final, final_answer}
    → if no valid action (none, or unknown tool name) → stop here with final_answer
    → else, if the run is *tainted* and the tool is state-changing (create_ticket / update_ticket /
      execute_recovery_action) → NOT executed: observation = "BLOCKED: …", step marked blocked, and the step is
      never treated as final (the model wrote its answer before seeing the block — it gets to answer again)
      (Phase 10.3, D-034)
    → else logs.record_tool_call(action) (so the `request` log line lists it, D-042), then execute the tool FIRST
      (even if is_final is also true — D-027, so a tool call bundled
      with is_final isn't silently dropped), then stop after it if is_final was set; if the output carries
      embedded instructions (guardrails.find_injection) the run becomes tainted from then on
    → else AVAILABLE_TOOLS[action](**args):
         lookup_runbook          → rag.retrieve(top_k=3, threshold=0.50)  → [Gemini] + [DB]
         get_ticket              → crm.get_ticket                         → [DB]
         create_ticket           → crm.create_ticket                      → [DB] (Phase 7.1, D-025)
         update_ticket           → crm.update_ticket_status               → [DB]
         escalate_to_human       → crm.update_ticket_status if ticket_id given → [DB]; steps_taken text is
                                    simulated (On-Call Guide §6 path) — nothing is actually posted/paged (Phase 7.1, D-025)
                                    → notify_n8n_escalation() → [n8n webhook] POST if N8N_ESCALATION_WEBHOOK_URL
                                    is set (best-effort — failure logged, never raised) → n8n/workflow.json's
                                    webhook node → HTTP Request node → Slack (Phase 9.4, D-031)
         run_system_diagnostics  → "database": [DB] (get_conn(retry=False), D-032) SELECT 1 + counts · other components: canned JSON (simulated)
         execute_recovery_action → canned JSON (simulated — nothing is executed)
    → thought / action / observation appended to the text transcript for the next step; the observation is
      wrapped by guardrails.fence() as <untrusted_data> (forged closing tags are stripped)
  if the loop ran every step without a final answer (`for … else`) → outcome "max_steps"
  if no step gave a *non-blank* final answer (checks truthiness, not just key presence — D-026)
    → [Gemini] one summary call on `Task: …` + the step transcript + SUMMARY_INSTRUCTION (plain text, not JSON) —
      not the full history, whose tool list says "Format … as JSON" (D-045); the reply goes through
      plain_text_answer(), which unwraps a JSON/fenced-JSON answer to its final_answer (if it fails: the summary's
      error type is recorded, a canned answer is used)
  if the run was tainted → a code-generated "[Security notice]" listing blocked actions is appended to the
    resolution, whatever the model said
→ {task, total_steps, steps, resolution} → AgentChatResponse
  finally → _log_agent_run(): one `agent_run` event — outcome (completed / max_steps / generation_error / crashed),
    steps, tools, duration, tainted. A clean run stops there (info); anything else — any outcome but completed,
    a failed summary, a tool error, or a tainted run — also logs the trace via trace_for_log() (thought, action,
    args, observation, final answer each clipped; past ~4,000 chars the oldest middle steps are dropped, first and
    last kept). Level warning; error for a crash, which is then re-raised.
```

### `POST /agent/triage/{ticket_id}` (`Depends(ratelimit.rate_limited("agent"))` — same bucket as /agent/chat: it runs the same loop)
```
api_agent_triage(ticket_id) → agent.triage_ticket_with_agent(ticket_id)
  → crm.get_ticket            (missing → ValueError → 404)
  → builds a goal prompt from the ticket, with subject/description fenced as untrusted data; if they carry
    embedded instructions the run starts tainted (guardrails.find_injection — Phase 10.3, D-034)
  → agent.run_agent(prompt, max_steps=4, taint_reason=…)     (same loop as above)
  → crm.get_ticket again (state after the agent's updates)
→ AgentTriageResponse         (any other error → 500)
```

### `GET /cron/reindex` (Phase 9.1, D-029 — was POST and counted rows only; now GET and really re-ingests)
```
api_cron_reindex(Authorization header)
  → if CRON_SECRET is unset and settings.vercel (deployed with no secret configured): 503, before any [DB]/[Gemini] (D-055)
  → if CRON_SECRET is set and header ≠ "Bearer <secret>": 401, in every environment (Phase 9.2, D-030) —
    compared with secrets.compare_digest as UTF-8 bytes, not `!=` (D-068), same pattern as login above
  → scripts.ingest.reindex_knowledge_base(force=False)
       → glob data/docs/**/*.md
       → [DB] ONE connection for the whole run
       → for each file: ingest_file(path, conn, force=False)
            → compute_content_hash(raw file text) → [DB] compare against documents.content_hash
            → match → skip (no re-chunk, no [Gemini], no writes) → {"unchanged": True}
            → no match (new file or changed) → upsert_document (new hash) → delete_existing_chunks →
              make_chunks → per chunk: [Gemini] embed_document → insert_chunk → {"unchanged": False}
       → {documents_total, documents_reindexed, documents_unchanged, chunks_embedded, chunks_skipped, summaries}
→ CronReindexResponse
```

### `GET /`
```
serve_dashboard() → static/index.html (inline fallback HTML if missing); assets served from the /static mount
```

## 5. Offline ingestion — `scripts/ingest.py`

```
main()
  → logs.configure_logging() (run as a script, app.main never loads; Phase 12.2)
  → argparse: --file, --reset, --quiet
  → --file given → ingest_file(path, conn, force=True)   (explicit single-file ingest, always re-embeds)
  → otherwise     → reindex_knowledge_base(force=args.reset)   (--reset wipes documents+chunks first, forcing
                     every file; a normal run has force=False — see the shared function below)
  → print summary (documents reindexed vs. unchanged, chunks embedded)
```

`reindex_knowledge_base(force, verbose)` — shared by `main()` above and `GET /cron/reindex` (Phase 9.1, D-029):
```
reindex_knowledge_base(force, verbose)
  → collect data/docs/**/*.md
  → [DB] ONE connection for the whole run (force=True deletes all chunks + documents first)
  → for each file: ingest_file(path, conn, verbose, force)
       → extract_frontmatter → extract_title_from_markdown (fallback: filename)
       → source = path relative to repo root, POSIX style
       → compute_content_hash(raw_text) → [DB] get_stored_document(source)
       → hash matches an existing row and not force → SKIP: no chunking, no [Gemini], no writes
           → return {..., "unchanged": True}
       → otherwise:
            → upsert_document(source, title, content_hash) → delete_existing_chunks(doc_id)
                 ← content_hash is why an unchanged re-run is a no-op; the delete+reinsert is why a
                   changed re-run doesn't duplicate rows
            → make_chunks(body)
                 → split_by_headings (#, ##, ###; `#` lines inside ``` code fences are ignored — shell comments)
                 → pack_paragraphs → split_units → split_text_with_overlap (only for single lines > 500 chars,
                   50 overlap)
                 → a piece shorter than 80 chars is merged into a neighboring piece in the same heading,
                   never dropped (D-060, was dropped outright — a short but real section could vanish)
            → for each chunk: llm.embed_document → embed_text("RETRIEVAL_DOCUMENT") → [Gemini]
                              → insert_chunk → sleep 0.5 s (free-tier rate limit)
            → return {..., "unchanged": False}
  → after the loop: [DB] diff stored document sources against the files just processed — any stored
    source with no matching file (a deleted runbook) is DELETE FROM documents (cascades to its chunks,
    ON DELETE CASCADE) — D-059, "documents_removed" in the result; a no-op when force=True (already wiped)
  → aggregate: {documents_total, documents_reindexed, documents_unchanged, chunks_embedded, chunks_skipped}
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
app.main           → app.agent, app.auth, app.config, app.crm, app.db, app.llm, app.logs, app.metrics, app.rag, app.ratelimit, app.schemas,
                     scripts.ingest (Phase 9.1, D-029 — so GET /cron/reindex can call reindex_knowledge_base())
app.agent          → app.crm, app.db, app.guardrails, app.llm, app.logs, app.rag, app.retry
app.rag            → app.db, app.llm, app.schemas
app.crm            → app.db
app.auth           → app.config, app.logs
app.llm            → app.config, app.guardrails, app.logs, app.retry
app.db             → app.config, app.retry
app.retry          → app.logs (+ httpx, psycopg, google.genai.errors)
app.logs           → app.config (stdlib logging/contextvars only — Phase 12.1, D-042)
app.metrics        → app.config, app.logs (+ psycopg directly: ONE reused plain connection, like ratelimit — Phase 12.4, D-046)
app.guardrails     → (none — stdlib only)
app.ratelimit      → app.auth, app.config, app.logs (+ psycopg directly: ONE reused plain connection, no pgvector setup — D-036)
scripts/ingest.py  → app.db, app.llm
evals/golden.py    → scripts.ingest (DOCS_DIR, split_by_headings — so golden-set sections are the chunker's sections; Phase 13.1, D-047)
evals/run.py       → evals.client, evals.golden, evals.judge, evals.report, evals.results, evals.scoring
evals/report.py    → app.config, evals.golden, evals.results, evals.scoring (+ git via subprocess for the commit hash — Phase 13.5, D-052)
evals/client.py    → app.config (+ app.main, app.auth imported lazily by InProcessClient) · httpx for HttpClient
evals/judge.py     → app.config, app.guardrails, app.llm, app.retry   (Phase 13.2, D-048)
```

## 8. Which code touches which table

| Table | Written by | Read by |
|---|---|---|
| `documents` | `scripts/ingest.py` | `rag.retrieve` (join); counted by `/health`, `/cron/reindex`, agent diagnostics |
| `chunks` | `scripts/ingest.py` | `rag.retrieve` (vector search); counted as above |
| `tickets` | `crm.py` (via `/tickets*` and agent tools) | `crm.py` |
| `conversations` | `/ask` (including each question of an in-process `python -m evals` run), `POST /conversations` | `/ask`, `GET /conversations*` |
| `messages` | `/ask` | `/ask` (history), `GET /conversations*` |
| `rate_limits` | `app.ratelimit` (upsert per request on `/ask`, `/agent/*`; self-creates the table) | `app.ratelimit` |
| `request_metrics` | `app.metrics` (one upsert per counted API request, from `RequestMetricsMiddleware`; self-creates the table; ~1% of writes prune rows older than 30 days) | `GET /metrics` |
