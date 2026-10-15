# DECISION.md — Why the code is the way it is

Every meaningful decision gets an entry, **with the reason**: why this library, why this design,
why this tradeoff was acceptable. Rules for when to add one are in `AGENTS.md`.

**Source** says where the reasoning comes from:
- *Build guide*: the shared 15-phase plan.
- *User*: decided by Niranjan or Vaishnavi.
- *Inferred*: reconstructed from the code because nobody wrote the reason down. If you know the real
  reason, replace the text and the source.

## Template (newest entries at the bottom)

```
### D-NNN · <short title>
- **Date · by · source:** YYYY-MM-DD · <who> · <Build guide | User | Agent | Inferred>
- **Decision:** what was chosen
- **Why:** the reason
- **Alternatives considered:** what else was possible and why it lost
- **Tradeoff accepted:** what we gave up, knowingly
- **Revisit if:** the condition that should reopen this
```

---

### D-001 · One FastAPI app, deployed as a single Vercel Function
- **Date · by · source:** 2026-10-07 · both · Build guide
- **Decision:** All routes live in one FastAPI app (`app/main.py`), deployed on Vercel Hobby.
- **Why:** Free, zero-config Python deploys, one URL for API, docs and web console. FastAPI gives request
  validation (Pydantic) and Swagger at `/docs` for free.
- **Alternatives considered:** Flask (no built-in validation or OpenAPI); Render/Railway (free tiers sleep or are
  limited); Docker (not available on Hobby).
- **Tradeoff accepted:** Cold starts, no long-running background workers, and Hobby limits.
- **Revisit if:** We need background jobs or the free tier limits get in the way.

### D-002 · Neon Postgres + pgvector instead of a separate vector database
- **Date · by · source:** 2026-10-07 · both · Build guide
- **Decision:** One Postgres database holds tickets, conversations and the vector embeddings.
- **Why:** One system to run, free via the Vercel Marketplace, and SQL joins between chunks and documents.
- **Alternatives considered:** Pinecone / Weaviate / Chroma (another account and another service to keep in sync).
- **Tradeoff accepted:** Less vector-search scale and tuning than a dedicated vector database.
- **Revisit if:** The knowledge base grows to hundreds of thousands of chunks.

### D-003 · Google Gemini for chat and embeddings (`google-genai` SDK)
- **Date · by · source:** 2026-10-07 · both · Build guide
- **Decision:** `gemini-embedding-001` for embeddings and a Gemini Flash model for answers.
- **Why:** Free tier with no card required; one provider and one key for both jobs.
- **Alternatives considered:** OpenAI (paid); local models (can't run on Vercel Functions).
- **Tradeoff accepted:** Free-tier rate limits (hence the retries in `app/llm.py` and the 0.5 s sleep in
  ingestion). Embeddings are tied to this model: switching models means re-embedding every chunk.
- **Revisit if:** Rate limits hurt users or answer quality isn't good enough.

### D-004 · 768-dimension embeddings
- **Date · by · source:** 2026-10-07 · both · Build guide
- **Decision:** Request 768 dimensions (`output_dimensionality`) instead of the model's full 3072.
- **Why:** pgvector's HNSW index supports at most 2000 dimensions for `vector`; 768 also keeps storage and search fast.
- **Alternatives considered:** 3072 dims without an index (slow), or `halfvec` (more complex).
- **Tradeoff accepted:** A small loss in retrieval quality.
- **Revisit if:** Retrieval quality is measurably poor in the Phase 13 eval.

### D-005 · HNSW index with cosine distance
- **Date · by · source:** 2026-10-07 · both · Build guide
- **Decision:** HNSW index on `chunks.embedding`; queries use `<=>` (cosine distance).
- **Why:** HNSW needs no training step and gives good recall even on a tiny dataset; cosine suits text embeddings.
- **Alternatives considered:** IVFFlat (needs enough data to train its lists, poor on 78 rows).
- **Tradeoff accepted:** Slower index builds and more memory, irrelevant at this size.
- **Revisit if:** Never at this scale.

### D-006 · psycopg 3, one new connection per call, autocommit
- **Date · by · source:** 2026-10 · Niranjan · Inferred
- **Decision:** `app.db.get_conn()` opens a fresh connection for every call and closes it after; autocommit on.
- **Why:** Serverless instances come and go, so an in-process pool isn't reliable; Neon's pooled URL
  (PgBouncer) does the pooling on the server side. Autocommit keeps each statement simple.
- **Alternatives considered:** `psycopg_pool` (adds lifecycle code), SQLAlchemy (heavier than needed).
- **Tradeoff accepted:** Connection latency on each call (`/ask` opens 3 connections). No multi-statement
  transactions unless code adds them explicitly.
- **Revisit if:** Latency matters (Phase 13 flags responses over 5 s).

### D-007 · Settings from env vars via pydantic-settings, with defaults
- **Date · by · source:** 2026-10-07 · both · Build guide
- **Decision:** `app/config.py` reads env vars (or `.env` locally) into a typed `Settings` object.
- **Why:** One typed place for configuration; the same code works locally and on Vercel.
- **Alternatives considered:** Raw `os.getenv` everywhere (untyped, scattered).
- **Tradeoff accepted:** The defaults (`admin`/`admin`, `jwt_secret="dev-secret"`) are used silently if a
  variable is missing in production. See Known issues in `AGENTS.md`.
- **Revisit if:** Phase 10 — production should refuse to start without real secrets.

### D-008 · Self-rolled JWT auth for a single operator
- **Date · by · source:** 2026-10-07 · both · Build guide
- **Decision:** PyJWT, HS256, 60-minute tokens, one username/password from env vars.
- **Why:** No external auth service and nothing to pay for; enough for a personal project with one admin.
- **Alternatives considered:** Clerk / Auth0 (another account, overkill for one user); OAuth (future work).
- **Tradeoff accepted:** One user, no refresh tokens, no way to revoke a token before it expires.
- **Revisit if:** More than one person needs to log in.

### D-009 · DevOps/SRE runbooks instead of the guide's EdTech topic
- **Date · by · source:** 2026-10-15 · Niranjan · User
- **Decision:** The knowledge base and prompts cover DevOps/SRE operations, not EdTech support.
- **Why:** The content, prompts and agent tools had already been built around runbooks; the user chose to keep it.
- **Alternatives considered:** Rewriting everything for EdTech, as the guide suggested.
- **Tradeoff accepted:** Examples in the build guide (grade sync, LMS) don't match the repo.
- **Revisit if:** Never, unless the project's focus changes.

### D-010 · ~500-character chunks: split on headings, then pack paragraphs
- **Date · by · source:** 2026-10-15 · Niranjan · Build guide + User
- **Decision:** Split each doc on `#`–`###` headings, greedily pack whole paragraphs up to 500 chars, hard-split
  only single lines over 500 chars (50-char overlap), drop pieces under 80 chars.
- **Why:** The guide asks for ~500 chars on paragraph/heading boundaries. Never cutting mid-paragraph keeps
  each chunk readable as a citation.
- **Alternatives considered:** Fixed-size windows (cut sentences in half); larger chunks (less precise retrieval).
- **Tradeoff accepted:** More chunks means more embedding calls (78 so far) and less context per chunk.
- **Revisit if:** Answers miss context that spans sections.

### D-011 · Idempotent ingestion keyed on the file path
- **Date · by · source:** 2026-10-15 · Niranjan · Build guide
- **Decision:** `documents` is upserted by `source` (POSIX path relative to the repo); its chunks are deleted and re-inserted.
- **Why:** The guide requires re-runs not to duplicate rows. POSIX paths give the same key on Windows and on Vercel.
- **Alternatives considered:** Content hashing to skip unchanged files (more code).
- **Tradeoff accepted:** Every run re-embeds every chunk, so it costs more Gemini calls and takes longer.
- **Revisit if:** Phase 9 makes `/cron/reindex` re-ingest — then skip unchanged files.

### D-012 · Similarity threshold 0.55 for `/ask`, 0.50 for the agent
- **Date · by · source:** 2026-10 · Vaishnavi · Inferred (from the comment in `app/rag.py`)
- **Decision:** Chunks scoring below 0.55 cosine similarity are dropped; the agent's runbook tool uses 0.50.
- **Why:** Tuning showed out-of-domain questions score about 0.50 and real operational questions score 0.70 or more,
  so 0.55 refuses off-topic questions without losing real ones. The agent uses a lower bar so it can still find leads.
- **Alternatives considered:** No threshold (the model would get irrelevant context and might hallucinate).
- **Tradeoff accepted:** Borderline but valid questions may get "I don't have enough information".
- **Revisit if:** The Phase 13 eval shows false refusals.

### D-013 · Grounding by system prompt and low temperature
- **Date · by · source:** 2026-10-07 · both · Build guide
- **Decision:** The model is told to answer only from the provided context, cite the source, and say it doesn't
  know otherwise; temperature 0.2.
- **Why:** The guide's Done-when for Phase 6 is "refuses out-of-scope questions instead of hallucinating".
- **Alternatives considered:** A second model call to check the answer (slower, more quota).
- **Tradeoff accepted:** It relies on the model following instructions; there's no hard check yet.
- **Revisit if:** Phase 10 prompt-injection tests or the Phase 13 eval find hallucinations.

### D-014 · ReAct loop with JSON-mode prompting instead of native function calling
- **Date · by · source:** 2026-10 · Vaishnavi · Inferred
- **Decision:** `agent.run_agent` asks Gemini for a JSON `{thought, action, args, is_final}` each step and
  dispatches the tool itself; max 5 steps (4 for triage).
- **Why:** Simple to follow and debug, and it returns a full thought/action/observation trace for the UI.
- **Alternatives considered:** Gemini native function calling (schema-checked args, but more SDK-specific code).
- **Tradeoff accepted:** Tool args aren't validated against a schema; one malformed JSON reply ends the loop.
- **Revisit if:** Phase 7 testing shows wrong tool calls or broken loops.

### D-015 · Agent tools are partly simulated and differ from the guide
- **Date · by · source:** 2026-10 · Vaishnavi · Inferred
- **Decision:** Tools are `lookup_runbook`, `get_ticket`, `update_ticket`, `run_system_diagnostics`,
  `execute_recovery_action`. Diagnostics are real only for the database; the other components and every
  recovery action return canned JSON.
- **Why:** Lets the agent demo an SRE investigation without real infrastructure to inspect or change.
- **Alternatives considered:** The guide's four tools (`search_knowledge_base`, `create_ticket`,
  `check_ticket_status`, `escalate_to_human`).
- **Tradeoff accepted:** The guide's `create_ticket` and `escalate_to_human` tools are missing (Phase 7.1, and
  9.4 needs `escalate_to_human`). Simulated output can look real in a demo.
- **Revisit if:** Phase 7 — the guide's tools need adding or the difference needs approving.

### D-016 · Mock CRM in Postgres, with extra ticket columns
- **Date · by · source:** 2026-10-15 · Niranjan · Build guide + User
- **Decision:** Tickets live in our own `tickets` table. `priority`, `resolution_notes` and `updated_at` were
  added beyond the guide's columns.
- **Why:** Free and under our control; `app/crm.py` and the triage flow need those columns.
- **Alternatives considered:** HubSpot's free CRM (optional stretch goal, Phase 8.4).
- **Tradeoff accepted:** It isn't a real CRM.
- **Revisit if:** Phase 8.4 is attempted.

### D-017 · Explicit Vercel entrypoint `api/index.py` with a catch-all rewrite
- **Date · by · source:** 2026-10-15 · Vaishnavi · Inferred
- **Decision:** `api/index.py` imports `app.main:app`; `vercel.json` rewrites every path to it and bundles
  `static/` and `data/`.
- **Why:** Makes the function entrypoint unambiguous and ships the web console and runbooks with the function.
- **Alternatives considered:** Vercel's zero-config detection of `app/main.py` (static/data might not be bundled).
- **Tradeoff accepted:** One more file and a rewrite rule to maintain.
- **Revisit if:** Vercel's zero-config detection covers everything.

### D-018 · Deploy through the teammate's existing Vercel project
- **Date · by · source:** 2026-10-15 · Niranjan · User
- **Decision:** Use Vaishnavi's Vercel project `knowops-ai-`, already Git-connected, instead of a second project.
  A trial project in Niranjan's account was deleted.
- **Why:** The Git connection already works there, and one deployment avoids confusion. Hobby plans only build
  commits from the project owner, so the owner's account should hold the project.
- **Alternatives considered:** Niranjan's own project deployed by CLI or connected to a fork.
- **Tradeoff accepted:** Only Vaishnavi can set env vars and see logs unless she invites Niranjan. Commits authored
  by Niranjan may not auto-deploy on Hobby.
- **Revisit if:** Niranjan needs to deploy independently, or Phase 14 needs shared access.

### D-019 · Static web console served by FastAPI
- **Date · by · source:** 2026-10 · Vaishnavi · Inferred
- **Decision:** A plain HTML/CSS/JS console in `static/`, served from `/` and `/static`.
- **Why:** No frontend framework, no build step, and a single deploy.
- **Alternatives considered:** Next.js or React app (a second project to build and deploy).
- **Tradeoff accepted:** Hand-written DOM code in `static/js/app.js`.
- **Revisit if:** The UI grows beyond a few panels.

### D-020 · Cron secret only enforced in production
- **Date · by · source:** 2026-10 · Vaishnavi · Inferred
- **Decision:** `/cron/reindex` rejects a wrong `CRON_SECRET` only when `VERCEL_ENV == "production"`.
- **Why:** Lets the endpoint be tested locally without the secret.
- **Alternatives considered:** Always require the secret.
- **Tradeoff accepted:** Preview deployments accept unauthenticated reindex calls.
- **Revisit if:** Phase 9.2 / Phase 10.

### D-021 · Shared agent context, decision log, flow doc and quiz gate
- **Date · by · source:** 2026-10-15 · Niranjan · User
- **Decision:** `AGENTS.md` is the single source of project status, and `CLAUDE.md` imports it. `/phase-done`
  updates it. `DECISION.md` records reasons, `FLOW.md` records execution flow, and agents quiz the human before
  a code change is accepted.
- **Why:** Two people and two AI tools work on the same repo. After a pull, both should see the same status and
  understand the code that was written for them, not just have it.
- **Alternatives considered:** Separate notes per tool (they drift apart); no quiz (changes get accepted without
  being understood).
- **Tradeoff accepted:** Every code change takes a few extra minutes for the docs and the quiz.
- **Revisit if:** The overhead stops being worth it.
