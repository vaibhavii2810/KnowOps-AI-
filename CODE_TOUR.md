# CODE_TOUR.md — The code, phase by phase, in plain English

For teammates who know the project but not the code. Each phase answers four things:
**What** (files) · **Why** (the problem it solves) · **Main idea** (one key snippet) · **Try it**.
Phase numbers follow the Build Guide (same as `AGENTS.md`). Deep detail lives in `FLOW.md` (call chains) and
`DECISION.md` (why choices were made) — this file is the gentle first read.

**The whole product in one sentence:** you ask a support question → the app finds the matching runbook
paragraphs → Gemini writes an answer using only those paragraphs → an "agent" can also open/update tickets.

```
Runbooks (.md) ──ingest──▶ Postgres (chunks + numbers) ──search──▶ Gemini answer
                                                      └──▶ Agent ──▶ tickets (CRM)
```

---

## Phase 1 — Accounts & env setup (no logic, just wiring)
- **What:** `requirements.txt` (the libraries), `.env` (secrets), `app/config.py` (reads them).
- **Why:** The app needs a database URL, a Gemini key and login secrets. They live in `.env`, never in git.
- **Main idea** (`app/config.py`): one `Settings` class that reads every variable from `.env`.
  ```python
  class Settings(BaseSettings):
      database_url: str = ""
      gemini_api_key: str = ""
      jwt_secret: str = "dev-secret"      # fallback if .env is missing (known issue, Phase 10)
      ...
  settings = Settings()                   # every other file does: from app.config import settings
  ```
- **Try it:** `python -c "from app.config import settings; print(settings.embed_dim)"` → `768`.

## Phase 2 — Database schema
- **What:** `scripts/init_db.sql` (run once in Neon), `app/db.py` (opens connections).
- **Why:** Everything the app remembers has a table. `vector(768)` lets Postgres store "meaning as numbers".
- **Main idea:**

  | Table | Holds |
  |---|---|
  | `documents` | one row per runbook file (+ a hash to detect edits) |
  | `chunks` | ~500-character pieces of a runbook + their 768 numbers (`embedding`) |
  | `tickets` | the mock CRM: subject, priority P1–P4, status |
  | `conversations`, `messages` | chat history |

  ```python
  # app/db.py — every query opens a short connection like this
  with get_conn() as conn:
      conn.execute("SELECT ...")
  ```
  The `HNSW` index on `chunks.embedding` is what makes "find similar meaning" fast.
- **Try it:** open the Neon SQL editor and run `SELECT count(*) FROM chunks;` (80 expected).

## Phase 3 — KB content + RAG ingestion
- **What:** `data/docs/*.md` (5 runbooks), `scripts/ingest.py`, `embed_document()` in `app/llm.py`.
- **Why:** Search by *meaning* needs the runbooks cut into small pieces, each converted to numbers (an
  "embedding") by Gemini. Small pieces = precise answers.
- **Main idea:** cut at headings, pack paragraphs up to ~500 characters, embed each piece, save it.
  ```python
  # scripts/ingest.py
  for heading, body in split_by_headings(text):     # cut at # / ## / ###
      for piece in pack_paragraphs(body):           # ≤ 500 chars, never mid-paragraph
          ...
  embedding = embed_document(content)               # Gemini: text → 768 numbers
  insert_chunk(conn, doc_id, idx, heading, content, embedding)
  ```
  Re-running doesn't duplicate rows: old chunks of a document are deleted before re-inserting.
- **Try it:** `python scripts/ingest.py` → everything says "unchanged" (Phase 9 skips unchanged files).

## Phase 4 — FastAPI skeleton + Vercel deploy
- **What:** `app/main.py` (all routes), `api/index.py` + `vercel.json` (hosting glue).
- **Why:** FastAPI turns Python functions into web endpoints; Vercel runs it online for free.
- **Main idea:** a route is a decorated function. `/health` is the simplest one.
  ```python
  @app.get("/health")
  def health() -> HealthResponse:
      # counts rows in documents and chunks, so we know DB + KB are alive
  ```
  `api/index.py` just imports `app` so Vercel knows where to start.
- **Try it:** `uvicorn app.main:app --reload`, then open http://127.0.0.1:8000/docs (clickable API page).

## Phase 5 — JWT auth
- **What:** `app/auth.py`, `POST /auth/login` in `main.py`.
- **Why:** The data and agent shouldn't be open to the internet. Login gives a signed token (a "wristband")
  that expires in 60 minutes.
- **Main idea:** log in once, send the token on every request; protected routes check it.
  ```python
  # auth.py — put this on a route to protect it
  def get_current_user_required(auth = Depends(security_bearer)):
      if not auth or not auth.credentials:
          raise HTTPException(401, "Authentication credentials were not provided.")
      return decode_access_token(auth.credentials)   # bad/expired → 401
  # main.py:  def ask(..., user = Depends(auth.get_current_user_required))
  ```
  Username/password come from `.env` (`APP_USERNAME`/`APP_PASSWORD`), compared in constant time.
- **Try it:** in `/docs`, call `/tickets` → 401. Call `/auth/login`, click **Authorize**, retry → 200.

## Phase 6 — RAG retrieval + `/ask`
- **What:** `app/rag.py` (search), `app/llm.py` (Gemini chat), `POST /ask` in `main.py`.
- **Why:** This is the core feature: answers grounded in *our* runbooks, with citations, and an honest
  "I don't know" instead of invented answers.
- **Main idea:** two steps — find, then answer.
  ```python
  # rag.py — "<=>" is pgvector's distance; 1 - distance = similarity (0..1)
  WHERE (1 - (c.embedding <=> %s::vector)) >= 0.55     # too-weak matches are dropped
  ORDER BY c.embedding <=> %s::vector LIMIT 5
  ```
  ```python
  # llm.py — the rule that keeps Gemini honest
  "Answer using ONLY the context sections provided. If not found, say: 'I don't have enough information…'"
  ```
  Threshold 0.55 was tuned: real questions score ≥ 0.70, off-topic ones ≈ 0.50.
- **Try it:** `/ask` with "How do I fail over the database?" (cited answer) vs "Best pizza topping?" (refusal).

## Phase 7 — Agent + tool-calling
- **What:** `app/agent.py`, `POST /agent/chat`, `POST /agent/triage/{id}`.
- **Why:** Q&A only *talks*. The agent can *do*: look up runbooks, file tickets, escalate to a human.
- **Main idea:** a loop called ReAct (Reason → Act → Observe), capped at `max_steps` so it can't run forever.
  ```python
  for step_num in range(1, max_steps + 1):
      step_data = json.loads(gemini_reply)        # {"thought", "action", "args", "is_final", ...}
      observation = AVAILABLE_TOOLS[action](**args)   # run the chosen tool
      conversation_history += f"Observation: {observation}"   # feed result back, go again
  ```
  7 tools sit in `AVAILABLE_TOOLS`. Only the **database** diagnostic is real; the others are simulated.
  Rule in the prompt: *escalating to a human beats creating a ticket* for outages/security breaches.
- **Try it:** `/agent/chat` with "my /ask requests keep timing out, log a ticket" and read the `steps` list.

## Phase 8 — Mock CRM / tickets
- **What:** `app/crm.py`, `/tickets*` routes, the `tickets` table.
- **Why:** The agent needs somewhere to file work; a Postgres table stands in for a real CRM (HubSpot).
- **Main idea:** plain create/read/update functions. Bad input is corrected, not trusted.
  ```python
  priority = priority.upper() if priority.upper() in VALID_PRIORITIES else "P2"   # P1–P4 only
  INSERT INTO tickets (...) VALUES (...) RETURNING id, subject, ...               # save and return it
  ```
  The agent's `create_ticket` tool is a thin wrapper over this same function.
- **Try it:** `POST /tickets`, then `GET /tickets/{id}` and see the same ticket come back.

## Phase 9 — Automation (cron + n8n) — partly done
- **What:** `GET /cron/reindex` in `main.py`, `reindex_knowledge_base()` in `scripts/ingest.py`,
  `n8n/incident_triage_workflow.json`.
- **Why:** If someone edits a runbook, the search index should update itself without manual work.
- **Main idea:** fingerprint each file; only re-embed files whose fingerprint changed.
  ```python
  content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
  if existing and not force and existing[1] == content_hash:
      return {..., "unchanged": True}      # skip: no Gemini calls, no writes
  ```
  Vercel Cron calls the route daily at 03:00 UTC; it needs the `CRON_SECRET` bearer token.
- **Try it:** `python scripts/ingest.py` twice — the second run reports every document "unchanged".

---

## Phases 10–15 (not built yet)
Add a section here when each phase is done (the `/phase-done` step is a good moment):
10 error handling & security · 11 testing & CI · 12 logging · 13 AI evaluation · 14 final deployment · 15 docs.

## How to read the code yourself (suggested order)
`config.py` → `db.py` → `schemas.py` → `rag.py` → `llm.py` → the `/ask` route in `main.py` → `crm.py` → `agent.py`.
