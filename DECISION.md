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
- **Tradeoff accepted:** More chunks means more embedding calls (80 so far) and less context per chunk.
- **Revisit if:** Answers miss context that spans sections.

### D-011 · Idempotent ingestion keyed on the file path
- **Date · by · source:** 2026-10-15 · Niranjan · Build guide
- **Decision:** `documents` is upserted by `source` (POSIX path relative to the repo); its chunks are deleted and re-inserted.
- **Why:** The guide requires re-runs not to duplicate rows. POSIX paths give the same key on Windows and on Vercel.
- **Alternatives considered:** Content hashing to skip unchanged files (more code).
- **Tradeoff accepted:** Every run re-embeds every chunk, so it costs more Gemini calls and takes longer.
- **Revisit if:** Phase 9 makes `/cron/reindex` re-ingest — then skip unchanged files.
  **Revisited 2026-10-25 — see D-029: content-hash-based skip added, both for the CLI and `/cron/reindex`.**

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
- **Tradeoff accepted:** Tool args aren't validated against a schema; a malformed JSON reply ends the loop
  (3 retries as of D-026, then a non-blank fallback message — no longer silently blank).
- **Revisit if:** Phase 7 testing shows wrong tool calls or broken loops.
  **Revisited 2026-10-25 — see D-026: found and fixed a live bug where a malformed reply produced a
  blank resolution instead of ending the loop with a message.**

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
  **Revisited 2026-10-25 — see D-025: `create_ticket` and `escalate_to_human` added, closing this gap.**

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
  **Revisited 2026-10-25 — see D-030: now enforced in every environment once the endpoint had real cost.**

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

### D-022 · JWT required on every route except `/health`, `/auth/login`, and the static shell
- **Date · by · source:** 2026-10-17 · Vaishnavi (with Claude) · Build guide
- **Decision:** `Depends(get_current_user_required)` was added to `/conversations*`, `/ask`, `/tickets*`,
  `/agent/chat`, `/agent/triage/{id}`. `/ask` switched from `get_current_user_optional` to required.
  `GET /`, `/static/*`, `/docs`, `/redoc` and `/cron/reindex` stay unauthenticated.
- **Why:** Phase 5.4's literal instruction is "protect every route except `/health` and `/auth/login`", but
  `GET /` only serves the static SPA shell (no data) and must load before a browser can even show the login
  form, so treating it as part of the login surface (like `/auth/login` itself) is necessary, not a loophole.
  `/docs`/`/redoc` are the same kind of shell, served by FastAPI itself. `/cron/reindex` already enforces its
  own `CRON_SECRET` bearer check (D-020) — it's a service-to-service call from Vercel Cron, not an operator,
  so the operator JWT dependency doesn't apply to it.
- **Alternatives considered:** Protecting `GET /` too (breaks the console before anyone can log in, since the
  JWT has to come from somewhere); adding JWT *and* keeping `CRON_SECRET` on `/cron/reindex` (two secrets to
  manage for one caller, no added safety since Cron isn't an operator).
- **Tradeoff accepted:** The SPA shell and generated docs are visible to anyone; no data lives there, so that's
  acceptable. `static/js/app.js` now gates `/ask`, conversations, tickets and agent triage on `jwtToken` and
  shows the login modal instead of firing a request that 401s.
- **Revisit if:** `GET /` or `/docs` start returning anything sensitive.

### D-023 · `top_k` default 5, caller-configurable 1–20, instead of a fixed 4–6
- **Date · by · source:** 2026-10-18 · Vaishnavi (with Claude) · Inferred
- **Decision:** `rag.retrieve(top_k=5)` is the default (inside the guide's suggested 4–6), but
  `AskRequest.top_k` (`app/schemas.py`) lets the caller pass 1–20, and `/ask` forwards it unchanged.
- **Why:** A fixed 4–6 is a reasonable default, not a hard requirement — letting the operator widen or
  narrow retrieval (e.g. a complex multi-step runbook vs. a single fact) is more useful than hard-coding it,
  and the default still satisfies Phase 6.1 as written.
- **Alternatives considered:** Clamping `top_k` server-side to 4–6 regardless of what the caller sends.
- **Tradeoff accepted:** A caller can ask for up to 20 chunks, which costs more context/tokens per answer
  than the guide anticipated; the `static/js/app.js` dropdown only ever offers sane values.
- **Revisit if:** Large `top_k` values measurably hurt answer quality or latency.

### D-024 · The Vercel app and a local `.env` can use separate Neon databases
- **Date · by · source:** 2026-10-20 · Vaishnavi (with Claude) · User
- **Decision:** Vercel's `DATABASE_URL` points at its own Neon database (separate from the one first used locally).
  Each has its own tables, chunks and tickets and must be ingested separately.
- **Why:** Found while verifying Phase 6: the live app showed 78 old chunks and 6 tickets while the local database
  had 80 chunks and 59 test tickets. Keeping them apart stops test runs from filling the live database with junk.
- **Alternatives considered:** One shared database (simpler, no drift, but tests write into live data).
- **Tradeoff accepted:** Knowledge-base changes must be ingested into each database by hand, or the live app
  serves stale answers (this is how the chunker bug stayed hidden on the live site).
- **Revisit if:** Phase 9 makes `/cron/reindex` really re-ingest, or Phase 14 sets up a staging/prod split.

### D-025 · Added `create_ticket` and `escalate_to_human` agent tools (Phase 7.1)
- **Date · by · source:** 2026-10-25 · Vaishnavi (with Claude) · Build guide
- **Decision:** `app/agent.py` gains `tool_create_ticket` (wraps `crm.create_ticket`) and
  `tool_escalate_to_human` (simulated — follows the On-Call Guide's escalation path: post to `#incidents`,
  page the on-call EM via PagerDuty, call VP Engineering for P1; if given a `ticket_id` it sets that ticket's
  status to `open` and appends an escalation note). Both are registered in `AVAILABLE_TOOLS` and documented
  in `AGENT_SYSTEM_PROMPT`.
- **Why:** Closes the gap D-015 flagged and Phase 7.1 names directly: the guide's done-when test for Phase 7
  requires "log a ticket" and ticket-related prompts to trigger a matching tool, which no existing tool did.
- **Alternatives considered:** Renaming `lookup_runbook`→`search_knowledge_base` and `get_ticket`→
  `check_ticket_status` to match the guide's exact names too — skipped: it's a cosmetic rename touching tests,
  `FLOW.md`, and the PDF generator script for no functional gain, since the guide's done-when criterion tests
  behavior, not tool names.
- **Tradeoff accepted:** Tool names still don't match the guide's `search_knowledge_base` /
  `check_ticket_status` naming (D-015's remaining deviation). `escalate_to_human`'s "page the EM" / "call VP
  Engineering" steps are simulated text, not a real PagerDuty call, consistent with the other recovery tools.
- **Revisit if:** The guide's exact tool names are required (e.g. an external caller matches on them), or
  escalation needs to actually page someone.

### D-026 · Retry 3x on a malformed/empty Gemini response in the agent loop
- **Date · by · source:** 2026-10-25 · Vaishnavi (with Claude) · Inferred (found live while testing Phase 7.2)
- **Decision:** `agent.run_agent`'s per-step Gemini call now retries up to 3 times when `resp.text` is empty
  (observed `finish_reason=MALFORMED_RESPONSE`), instead of silently parsing `resp.text or "{}"`. The post-loop
  "did we get a final answer" check now tests `s.get("final_answer")` (truthy) instead of `"final_answer" in s`
  (key presence).
- **Why:** Found while live-testing a multi-tool task ("log a P1 ticket, then escalate it"): Gemini's JSON mode
  intermittently returns `MALFORMED_RESPONSE` with no text at all — not an exception. The old code parsed that
  into a blank thought/action/final_answer, which satisfied `"final_answer" in s` (the key existed, just empty)
  so the synthesis fallback never ran, and `run_agent()` returned `resolution=""`. Reproducing the exact failing
  prompt 3x in isolation showed the same prompt succeeds on a later call — it's transient, not a prompt-design
  problem, so a short retry (matching the existing 429/503 retry pattern in `app/llm.py`) is the fix.
- **Alternatives considered:** Switching to Gemini native function calling (bigger change, D-014's call to make
  separately); giving up after one malformed reply with a blank answer (the original, broken behavior).
- **Tradeoff accepted:** Worst case, 3x the Gemini calls for one step before falling back to the existing
  generic "Completed triage based on available runbook knowledge" message — still possible to see in the trace
  if Gemini is malformed on all 3 attempts (observed once live). `run_agent()` never returns a blank resolution
  now, but it may still give up on a specific tool call the task asked for.
- **Revisit if:** The malformed-response rate stays high enough that 3 retries routinely isn't enough, or the
  extra Gemini calls meaningfully affect free-tier quota.

### D-027 · Execute a tool call even when Gemini also sets is_final=true in the same reply
- **Date · by · source:** 2026-10-25 · Vaishnavi (with Claude) · Inferred (found live while testing Phase 7.4)
- **Decision:** `agent.run_agent`'s loop now executes any valid requested tool call before checking `is_final`.
  Previously `if is_final or not action or action not in AVAILABLE_TOOLS: ... break` exited the step before the
  tool-execution block, so a reply that set both `action` and `is_final: true` never ran the tool at all.
- **Why:** Found live triaging a ticket: Gemini's step-4 reply was `{"action": "update_ticket", "args": {...
  "status": "resolved" ...}, "is_final": true, "final_answer": "Incident #108 has been successfully...
  resolved."}`. The old code saw `is_final=true`, broke immediately, and recorded that final_answer — but the
  ticket's actual status in Postgres stayed `open` with no resolution notes, because `update_ticket` never ran.
  The agent reported success with complete confidence while doing nothing. Reproduced 3x after the fix: all 3
  triage runs now show the ticket genuinely `resolved` in the database, re-fetched independently of the API
  response.
- **Alternatives considered:** Prompting the model more strictly never to combine `action` and `is_final` in
  one reply (unreliable — nothing stops a future reply from doing it anyway; the code must be correct
  regardless of what the model sends). Rejecting/retrying a reply that combines both (wastes a step and a
  Gemini call when the model's intent — run this tool, then I'm done — is actually clear and executable).
- **Tradeoff accepted:** None found — this closes a correctness gap with no new downside; the final answer
  now reflects a tool call that genuinely happened instead of one that didn't.
- **Revisit if:** A future tool has side effects that shouldn't run on a step the model also calls final (none
  of the current tools fit that — they're all meant to run exactly when requested).

### D-028 · Escalation takes priority over ticketing in AGENT_SYSTEM_PROMPT
- **Date · by · source:** 2026-10-25 · Vaishnavi (with Claude) · Inferred (found live while testing Phase 7.5)
- **Decision:** `AGENT_SYSTEM_PROMPT`'s rules now say explicitly that `escalate_to_human` must be called first
  — before `create_ticket`, diagnostics, or remediation — whenever the situation matches the On-Call Guide's
  "escalate immediately" criteria, and that it doesn't need an existing ticket (`ticket_id=null` is valid).
- **Why:** Testing each tool individually (Phase 7.5) found that a textbook "escalate immediately" prompt
  ("confirmed unauthorized access to the production database... escalate immediately") made the agent call
  `create_ticket` instead of `escalate_to_human`. The two rules added for D-025 (create_ticket for new
  incidents; escalate_to_human for the on-call criteria) didn't say which one wins when both apply, and the
  model defaulted to the rule listed first. Reproduced 3x before the fix (all 3 chose `create_ticket`), fixed
  3x after (all 3 correctly chose `escalate_to_human` with `ticket_id: null`).
- **Alternatives considered:** Leaving both tools as equally valid and accepting the model's choice (rejected —
  the On-Call Guide's whole point of "don't wait" is defeated if the agent files a ticket first); having
  escalate_to_human internally call create_ticket (unneeded complexity — `ticket_id=null` already covers "no
  ticket exists yet" cleanly).
- **Tradeoff accepted:** None found.
- **Revisit if:** A real incident needs both a ticket AND an escalation and the ordering actually matters
  operationally (today the prompt doesn't forbid calling `create_ticket` afterward in a later step).

### D-029 · `GET /cron/reindex` actually re-ingests, skipping unchanged files by content hash
- **Date · by · source:** 2026-10-25 · Vaishnavi (with Claude) · Build guide
- **Decision:** `documents` gained a `content_hash` column (SHA-256 of the raw file, migrated on both the
  local and the Vercel-connected databases — D-024). `scripts/ingest.py`'s `ingest_file()` now compares a
  file's hash to what's stored before re-chunking/re-embedding it, and skips entirely (no DB writes, no
  Gemini calls) when they match. A new `reindex_knowledge_base()` function wraps the whole-directory sweep and
  is shared by both the CLI (`main()`) and the API. `/cron/reindex` changed from `POST` (counts rows only) to
  `GET` (actually calls `reindex_knowledge_base()`), fixing both Known issues the guide names for 9.1 and 9.3
  in one change, since they were really the same gap (the route never did real work, under the wrong method).
- **Why:** This was D-011's own stated revisit trigger, and the guide's 9.1 wording ("re-runs ingestion for
  any *new or changed* files") requires change detection, not a blind full re-embed every night. Re-embedding
  all 80 chunks nightly would cost Gemini free-tier quota for no reason on nights nothing changed, and risks
  the Vercel Hobby function's execution time limit. Verified live: editing one runbook and calling
  `reindex_knowledge_base()` re-embedded only that file (16 chunks) while the other 4 were skipped; restoring
  the file's original content correctly detected the change back; a second call with nothing changed made
  zero Gemini calls (2.3s vs. 2+ minutes for a full re-embed).
- **Alternatives considered:** File mtime instead of a content hash (unreliable — git checkouts and Vercel
  deploys don't preserve mtimes); a separate "last reindexed" timestamp column compared against file mtime
  (same problem); always doing the full `--reset` sweep nightly (the original behavior, explicitly the thing
  D-011 flagged as a cost to revisit).
- **Tradeoff accepted:** A file edited and reverted within the same day re-triggers a real re-embed (the hash
  differs from what's stored, then differs again back) — correct but not free; not worth optimizing for. The
  very first run after this migration necessarily re-embeds everything once (every existing row's hash starts
  empty), confirmed live before falling back to the fast skip path on every run after.
- **Revisit if:** `data/docs/` grows large enough that even a single changed file's re-embed risks the
  function timeout — then move ingestion off the request path (a queue, or a separate longer-running job).

### D-030 · `CRON_SECRET` enforced in every environment, not just production
- **Date · by · source:** 2026-10-25 · Vaishnavi (with Claude) · Build guide
- **Decision:** `GET /cron/reindex` now rejects a missing or wrong `CRON_SECRET` whenever one is configured
  (`settings.cron_secret` non-empty), dropping D-020's `VERCEL_ENV == "production"` gate entirely. A
  contributor with no `CRON_SECRET` in their own local `.env` is unaffected, since the check only fires once
  the secret is actually set.
- **Why:** D-020 was an acceptable tradeoff when this endpoint only counted rows — an unauthenticated call cost
  nothing. Phase 9.1 changed that: the endpoint now runs real ingestion (Gemini calls, database writes).
  Verified live before the fix: an unauthenticated `GET /cron/reindex` against the `sprint-2` Preview
  deployment succeeded and triggered the first full re-embed — exactly the "triggered by randoms" scenario
  9.2 exists to prevent, demonstrated for real, not hypothetically.
- **Alternatives considered:** Keeping the production-only gate and accepting the Preview exposure (rejected —
  the whole point of 9.2 is that this can't happen); requiring the secret unconditionally, even with none
  configured (rejected — would make local dev without a `.env` entry impossible to test, for no safety gain
  since nothing is being protected if no secret exists to protect it with).
- **Tradeoff accepted:** None found — this closes a real, now-demonstrated gap with no new downside.
- **Revisit if:** Never, unless a future deployment target can't set environment variables per-environment.

### D-031 · `escalate_to_human` posts to an n8n webhook, which notifies Discord/Slack
- **Date · by · source:** 2026-10-27 · Vaishnavi (with Claude) · Build guide
- **Decision:** `tool_escalate_to_human` now POSTs its escalation payload (reason, steps taken, ticket
  id/priority if any) to `N8N_ESCALATION_WEBHOOK_URL` when that env var is set. `n8n/workflow.json` (new —
  separate from the existing `n8n/incident_triage_workflow.json`) is a webhook node at path
  `escalate-to-human` wired to an HTTP Request node posting a formatted message to a Slack webhook URL.
  The call is best-effort: a missing/unreachable webhook is logged and swallowed, never raised, so the agent
  tool itself always succeeds regardless of whether n8n happens to be running.
- **Why:** This is the literal Phase 9.4 requirement — a webhook that fires specifically when
  `escalate_to_human` runs, not the unrelated alert-ingestion workflow that already existed. Made best-effort
  because the guide has n8n running locally via `npx n8n` (free, no Docker); it won't be running in most
  deployed environments, and a missing on-call notification channel shouldn't ever break the escalation path
  it's supposed to support.
- **Alternatives considered:** Reusing `n8n/incident_triage_workflow.json` and adding a branch for this case
  (rejected — that workflow is a different trigger, alert-in rather than escalation-out, and the guide asks
  for one workflow with this specific trigger); making the webhook call required/blocking (rejected — would
  mean a down n8n instance silently breaks `escalate_to_human`, the opposite of what an escalation path should
  do under failure).
- **Tradeoff accepted:** The Slack URL in `n8n/workflow.json` is a placeholder (`.../mock/webhook/...`), same
  convention as the existing workflow file — whoever runs this for real swaps it for an actual Slack/Discord
  webhook URL. Verified the mechanism end-to-end with a real local HTTP listener (not n8n itself): the
  backend's POST arrives with the exact JSON shape (`reason`, `steps_taken`, `ticket_id`, `ticket_priority`)
  the workflow's Slack message template expects.
- **Revisit if:** n8n is actually run and connected for real — confirm the imported workflow fires correctly
  against a live n8n instance, not just the HTTP-listener simulation.

### D-032 · One shared retry/backoff helper for Gemini and Postgres (`app/retry.py`)
- **Date · by · source:** 2026-10-27 · Vaishnavi (with Claude) · Build guide
- **Decision:** `app/retry.py` provides `retry_call(fn, is_transient=..., label=...)`: up to 4 attempts,
  exponential backoff (~1s, 2s, 4s, capped at 8s) with 0.5–1.0× jitter. Every Gemini call site (`embed_text`,
  `chat_completion`, and both agent calls) goes through it with `is_transient_gemini_error` — 429, 408, any 5xx,
  and network timeouts/connection errors retry; other 4xx (bad key, malformed request) fail fast. `get_conn()`
  retries only the **connect** step, on `psycopg.OperationalError` except wrong-password/authorization errors.
  `get_conn(retry=False)` skips the retry; `GET /health` and the agent's database diagnostic use it, because
  their job is to *report* an outage — see the tradeoff below.
  Errors that exhaust retries re-raise unchanged, so every existing `except` block and HTTP status mapping keeps
  working as before.
- **Why:** The audit for Phase 10.1 found uneven coverage: `app/llm.py` had two copy-pasted loops that only
  recognised 429/503 (by string-matching the error text, and confirmed against the committed code: a plain 500
  was raised after one attempt); `app/agent.py`'s two Gemini calls had no retry for real API errors at all
  (a live 429 during Phase 7.5 testing went straight to the fallback message); Postgres had none. One
  implementation with an explicit "is this worth retrying?" predicate removes the duplication and the string
  matching, and lets permanent failures fail fast instead of spending the serverless function's time budget.
- **Alternatives considered:** The `tenacity` library (a new dependency for ~30 lines of logic); retrying every
  SQL statement (rejected — see tradeoff); leaving the inline loops and just widening their status list
  (keeps the duplication and the agent gap).
- **Tradeoff accepted:** DB retries cover connection establishment only, not statements. The connection
  is autocommit, so an INSERT whose response was lost may already be committed; re-running it would create a
  duplicate ticket or message. A transient failure *mid-query* therefore still surfaces as an error instead of
  being retried. Also: a daily-quota 429 (free tier) won't recover on retry, so it costs ~7s of backoff before
  failing — acceptable because per-minute 429s are the common case and do recover. Worst-case added latency per
  failing call is ≈ 1+2+4 = 7s. Measured, not assumed: with the DB down, `/health` first took ~6.7s of
  backoff to answer 503 (a monitor with a 5s timeout would see a hang, not a 503), which is why the two
  health probes opt out. HTTP status codes and error text for every route are unchanged — enforced by
  `tests/test_retry.py` (exhausted retries still map to the same 503s; permanent errors still fail fast).
- **Revisit if:** Mid-query DB failures show up in logs (Phase 12) — then add idempotency keys and retry
  statements — or if the 7s worst case runs into the function timeout.

### D-033 · Strict request validation, plus fixes for the crashes it surfaced (Phase 10.2)
- **Date · by · source:** 2026-10-27 · Vaishnavi (with Claude) · Build guide
- **Decision:** `app/schemas.py` gained shared input types: free text is whitespace-stripped *before* its length
  check and rejects NUL bytes; `priority` and ticket `status` are case-insensitive `Literal` enums;
  `conversation_id` is bounded to a valid int4. The two list routes bound `limit` (`/tickets` 1–200,
  `/conversations` 1–100) and validate the `status`/`priority` filters. `verify_operator_credentials` now compares
  UTF-8 bytes. Contract changes: invalid ticket status on `PATCH` is **422 (was 400)**; invalid priority on
  `POST /tickets` is **422 (was silently coerced to P2)**; unknown `?status=`/`?priority=` filters are **422 (was an
  empty 200)**; `?limit=` out of range is 422.
- **Why:** The phase's done-when is "a bad request never crashes the API", so rather than only confirming Pydantic
  models exist I fuzzed all routes (76 hostile requests, Gemini stubbed). **6 returned HTTP 500**: NUL bytes in
  ticket subject/description/notes and in the `status` filter (Postgres cannot store NUL), and a negative `limit`
  on both list routes. A further probe found **login with any non-ASCII character was a 500** (`secrets.compare_digest`
  raises `TypeError` on non-ASCII `str`) — an unauthenticated crash on a public endpoint. Silent failures too:
  a whitespace-only subject created a blank ticket, `priority: "banana"` was quietly stored as P2, and a
  whitespace-only `/ask` question would have spent a Gemini call. The permanent test file
  (`tests/test_input_validation.py`, 57 cases) fails 31 of 57 against the previous code and passes against this.
- **Alternatives considered:** A catch-all handler mapping `psycopg.DataError` to 422 (rejected — it would also hide
  genuine server bugs as client errors); validating only the bodies, as the guide's wording literally says
  (rejected — the crashes were in query params and in auth); bounding path ids (skipped — they don't crash, a
  bad id is already a 404); stripping login passwords (rejected — spaces can be legitimate there).
- **Tradeoff accepted:** The 400→422 and silent-coercion→422 changes are a breaking change for any client that sent
  bad values; checked that the web console only sends `P1`–`P4` and `limit=15`/`50`, and nothing else in the repo calls
  these endpoints. The agent's tools call `app/crm.py` directly, not HTTP, so they still coerce an invalid priority
  to P2 — not changed here. Enum matching is case-insensitive on purpose so `p1` and `Resolved` keep working.
- **Revisit if:** Another client needs the old lenient behaviour, or a new free-text field is added (it must use
  the shared `_clean_text` type or it reintroduces the NUL crash).

### D-034 · Prompt-injection guardrails: fence untrusted text, drop poisoned chunks, block state-changing tools on tainted runs (Phase 10.3)
- **Date · by · source:** 2026-11-03 · Vaishnavi (with Claude) · Build guide
- **Decision:** New `app/guardrails.py`. (1) `fence()` wraps untrusted text — runbook chunks, ticket content, tool
  output — in `<untrusted_data>` tags and `neutralize()` strips any look-alike tag so the text cannot close the fence;
  both system prompts now say fenced text is data, never instructions. (2) `find_injection()` is a deterministic
  detector (5 narrow patterns: override-instructions, reveal-prompt, alert-style fake authority, persona switch,
  "assistant, you must…"). A flagged **knowledge-base chunk is dropped** before it reaches Gemini. A flagged **ticket
  or tool output marks the agent run tainted**, after which `create_ticket`, `update_ticket` and
  `execute_recovery_action` are not executed (`STATE_CHANGING_TOOLS`); `escalate_to_human` stays available because
  paging a human is the right response to a suspected attack. (3) A blocked step is never treated as final, and a
  code-generated `[Security notice]` is appended to any tainted run's resolution.
- **Why:** The guide asks for 3–5 injection cases and that the agent not comply. I measured instead of assuming: against
  live Gemini, 5 cases (direct prompt-reveal, poisoned KB chunk, persona switch, injected ticket, poisoned tool output);
  **case E hijacked the agent 1 of 3 times** (a poisoned runbook result made it call `execute_recovery_action` on a
  plain "how do I roll back" question). It is intermittent and model-dependent, so tests that call the real model can
  neither prove the fix nor stay stable (and Gemini's free-tier 429s made several runs inconclusive). The defences
  therefore enforce the property in code, and the tests use a scripted **hijacked** model that obeys every injected
  instruction and show the state-changing tool still does not run. Also found, in the first version of this very fix:
  the model wrote "the ticket status has been updated to 'resolved'" in the same step as the blocked `update_ticket`,
  before it saw the block — the operator would have been told a blocked action succeeded. Hence the non-final rule and
  the code-generated notice. A flagged-ticket run now answers honestly ("the update could not be completed").
- **Alternatives considered:** Fencing + prompt rule alone (relies on the model obeying it — the thing that failed
  1/3 on case E); blocking *all* tools on a tainted run (rejected: `escalate_to_human` is the safe response and
  read-only tools are harmless); a second LLM call to classify injections (extra quota, latency and its own failure
  modes — the free tier already returns 429s); broad regexes (rejected: my first `fake-authority` pattern flagged
  "the system override switch is on the PDU panel", and a false positive here silently blocks real remediation —
  patterns now target text addressed to the AI, and `tests/test_prompt_injection.py` asserts that none of the seed
  runbooks, whole or chunked, is flagged).
- **Tradeoff accepted:** The detector is a heuristic, not a proof. A reworded, translated or encoded attack gets past
  it, and then fencing plus the prompt rule are the only defence (the case that failed 1/3). A flagged ticket can no
  longer be auto-resolved by triage — it needs a human, by design. `escalate_to_human` can still be triggered by
  injected text (nuisance, not damage). A dropped chunk still appears in `/ask`'s `sources` list although the model
  never saw it. A direct attack typed by the authenticated operator into their own `/ask` is only defended at the
  model level (two live tests, which skip on 429 rather than pass). Tools still run with model-supplied arguments.
- **Revisit if:** A real attack gets past the detector (add its pattern and a test); a new state-changing tool is
  added (it must join `STATE_CHANGING_TOOLS`); the simulated recovery actions become real; or the agent is exposed to
  anyone who is not the single trusted operator.

### D-035 · Standing secrets-hygiene tests, and a broader `.gitignore` (Phase 10.4)
- **Date · by · source:** 2026-11-03 · Vaishnavi (with Claude) · Build guide
- **Decision:** `.gitignore` now also ignores `.env.*` (except `.env.example`), `*.pem`, `*.key`, `.vercel/` and
  `.DS_Store`. `tests/test_secrets_hygiene.py` asserts, on every test run: `.env` and its variants are ignored and only
  `.env.example` is tracked; no `.env*` file was ever committed on any branch; `.env.example` holds only placeholders; no
  common secret format (Google/Gemini-style/Neon keys, JWTs, AWS/GitHub/Slack/OpenAI-style tokens, private keys, DB URLs
  with a real password) appears in any tracked file — PDFs included, by decompressing their streams — or in any line ever
  added on any ref; and, where a local `.env` exists, none of its secret values appears anywhere in history (the test
  reports only the variable name).
- **Why:** The phase asks to confirm `.env` is ignored and check history for committed keys. The check came back clean
  (23 commits, all refs, 7 secret values, 8 PDFs), but a one-off scan goes stale at the next commit, and the repo is
  **public**, so one slipped key would be exposed immediately. The `.gitignore` gaps were real: `vercel env pull` writes
  `.env.local`/`.env.production` (which a bare `.env` rule does not match), and the Vercel CLI writes `.vercel/`.
- **Alternatives considered:** gitleaks/trufflehog (new dependency or binary for a ~14k-line repo; the regex set here
  covers the providers this project uses, and a pre-commit tool can be added later); a git pre-commit hook (`.git/hooks`
  is not versioned, so teammates would not get it — the CI run planned for Phase 11.5 will enforce these tests
  instead); a loose `password = …` regex (it flags ordinary code — the first run's 4 hits were all `api_key=settings.…`).
- **Tradeoff accepted:** Format-based scanning cannot catch a secret with no recognisable shape (e.g. a short human-chosen
  password), and the value-based test only knows the values in the local `.env`. The scan covers local refs and
  `origin/*`; it does not cover unreachable objects, other clones/forks, or GitHub pull-request refs. If a history test
  ever fails, the fix is to **rotate the key** — a later commit that deletes it leaves it readable, and the test stays red
  until history is rewritten. Secrets printed in an assistant/chat transcript are not git leaks and are not detected.
- **Revisit if:** a provider is added whose keys have a new format (add it to `SECRET_FORMATS` with a scanner self-test
  case), or CI exists and a real secret scanner is worth adding to it. Worth enabling on the repo itself: GitHub →
  Settings → Code security → Secret scanning and Push protection (free for public repos).

### D-036 · Rate limits kept in Postgres, on one reused connection, failing open (Phase 10.5)
- **Date · by · source:** 2026-11-03 · Vaishnavi (with Claude) · Build guide
- **Decision:** `app/ratelimit.py` counts requests per user (the JWT `sub`) and bucket in a `rate_limits` table — a
  fixed one-minute window, upserted with `ON CONFLICT … DO UPDATE SET hits = hits + 1 RETURNING hits`. Defaults: `/ask`
  10/min; `/agent/chat` and `/agent/triage/{id}` 5/min **sharing one bucket** (`RATE_LIMIT_ASK_PER_MINUTE`,
  `RATE_LIMIT_AGENT_PER_MINUTE`; `0` disables). Authentication runs first, so an unauthenticated caller gets 401 and uses
  nothing; over the limit is 429 with `Retry-After`, and `X-RateLimit-Limit/Remaining` ride on every limited response.
  The limiter keeps **one plain psycopg connection** open per process, reconnects once if it has gone stale, and creates
  its own table on first use. If the counter cannot be reached the request is **allowed** and a warning is logged.
- **Why:** The guide says "a simple per-user counter is enough". It lives in Postgres, not memory, because the API runs as
  serverless instances that restart and run side by side: an in-memory counter resets on every cold start and each
  instance counts separately, so the real limit would be N times the configured one — and a stolen token is exactly the
  case where someone fires concurrent requests to spin up instances. `/agent/triage` is in the agent bucket because it runs
  the same ReAct loop; limiting only `/agent/chat` would leave a free way round it. Measured, not assumed: my first
  version used `get_conn()` and added **~1.2s to every limited request** (a fresh connection to the remote Neon DB, of
  which ~0.8s is pgvector registration the limiter never needs). A reused plain connection costs **~56 ms** after a
  one-time ~540 ms connect. Fail-open because this protects cost and quota, it is not access control: a counter fault
  must not take `/ask` down by itself.
- **Alternatives considered:** In-memory counters (zero latency and no schema, but per-instance and reset on cold
  start); `slowapi` or another library (new dependency, and its default storage is in-memory); a Redis/Upstash counter
  (another service and account); a fresh `get_conn()` per check (rejected on the measured latency); a connection pool
  (needs `psycopg_pool`, and one connection behind a lock is enough at this traffic).
- **Tradeoff accepted:** A fixed window allows up to 2× the limit across a minute boundary. One shared connection
  serialises limiter queries behind a lock (~56 ms each — fine for one operator, a bottleneck at real concurrency). The
  defaults are guesses to tune against the real Gemini quota (Phase 12 monitoring will show it). Failing open means that
  during a database outage the limit is off — acceptable, since `/ask` needs the database too. **Not covered:**
  `/auth/login` is still unlimited, so the public login can be brute-forced; with the Vercel password still `admin` that
  is the bigger exposure (see Known issues).
- **Revisit if:** Traffic grows beyond one operator (switch to a pool or a proper store); the default limits trip during
  normal use or fail to protect the Gemini quota; or a limiter is wanted on `/auth/login` (same table, keyed by client IP).

### D-037 · Login rate limit, per client IP, two windows, no per-username lockout (follow-up to Phase 10.5)
- **Date · by · source:** 2026-11-03 · Vaishnavi (with Claude) · User (D-036 left `/auth/login` as the biggest open exposure)
- **Decision:** `POST /auth/login` gets `login_rate_limited`: **5 attempts per minute and 30 per hour per client IP**
  (`RATE_LIMIT_LOGIN_PER_MINUTE`, `RATE_LIMIT_LOGIN_PER_HOUR`; 0 disables), on the same Postgres counter table as D-036.
  Every attempt counts — right or wrong, and malformed bodies too — and the check runs **before** the credentials are
  looked at, so a blocked caller gets 429 even with the correct password. The IP comes from `x-vercel-forwarded-for`,
  then `x-forwarded-for`, `x-real-ip`, then the socket.
- **Why:** With `/ask` and the agent limited, the unauthenticated login was the one endpoint left where a guess costs an
  attacker nothing, on a public site whose Vercel password is still the default `admin`. The per-IP key is trustworthy
  *on Vercel*: its docs say `x-forwarded-for` is overwritten and external IPs are not forwarded, specifically to prevent
  spoofing. Two windows because they catch different things: 5/min stops a burst, 30/hour stops slow guessing that
  stays under the per-minute limit (a test shows the hourly cap blocking when the per-minute limit is off). Answering 429
  before checking credentials removes the oracle where the right password would still succeed after the limit.
- **Alternatives considered:** A per-**username** lockout (rejected: with one operator it lets an attacker lock the real
  user out just by sending bad logins — a denial of service on login); counting only failed attempts (rejected: needs
  a peek-then-increment step and gives an attacker the same number of free tries either way); progressive delays (state
  and latency for little gain at this size); a CAPTCHA (a new service and UI).
- **Tradeoff accepted:** It does **not** stop a distributed attack from many IP addresses, and it does **not** make `admin`
  a safe password — it only makes guessing slow. The headers are trusted because Vercel sets them; run behind another
  proxy (or locally) and a client can send them itself, so the limit is only as strong as the proxy in front. A shared
  office/NAT address shares one allowance. A legitimate user fumbling the password 5 times in a minute waits up to 60 s.
- **Revisit if:** The app is hosted somewhere that does not overwrite these headers; a second operator is added; or logs
  (Phase 12) show distributed guessing.

### D-038 · Shared offline fakes for Gemini and Postgres, patched at their roots, with a network guard (Phase 11.1)
- **Date · by · source:** 2026-11-06 · Vaishnavi (with Claude) · Build guide (11.1: "fixtures that mock the Gemini client and the database")
- **Decision:** `tests/conftest.py` gains three fixtures. `fake_gemini` replaces `genai.Client` itself and clears
  `get_client()`'s `lru_cache` before and after; it returns deterministic unit-vector embeddings and scripted replies
  (text, a dict for the agent's JSON mode, an exception, or `None` for a MALFORMED_RESPONSE), recording every call.
  `fake_db` replaces `psycopg.connect` (and skips `register_vector`); SQL fragments map to scripted tuple rows, every
  statement is recorded, and the rate limiter's cached connection is reset so a fake can't leak into a later test.
  `no_network` blocks every non-loopback socket connect and every real `psycopg.connect`; both fakes pull it in.
  Blocked attempts are also **recorded and fail the test at teardown**.
- **Why:** The guide's Phase 11 "Done when" is *no real API calls during tests*, and CI (11.5) will have no `.env`,
  database or Gemini key. Patching at the root (`genai.Client`, `psycopg.connect`) instead of each module's imported
  name means every current and future caller is covered — `app/agent.py` imports `get_client` by name, and a mutation
  check showed the old per-module style (patch `llm.get_client` only) let the agent reach Google's API
  (`172.217.117.4:443`). Teardown checking matters because the app swallows some errors on purpose (agent loop,
  rate-limiter fail-open, best-effort webhook); a second mutation check showed a swallowed real connect is still caught.
  The fake DB is a script, not a SQL engine, because the app only ever uses `conn.execute(sql, params).fetchone()/
  .fetchall()` with tuple rows.
- **Alternatives considered:** A real Postgres + pgvector service container in CI (truer to production, but slower,
  needs schema setup, and is not what the guide asks for — still an option for a later integration job);
  an in-memory SQL engine such as SQLite (doesn't speak pgvector's `<=>` or Postgres SQL); `unittest.mock.MagicMock`
  everywhere (accepts any call, so a wrong attribute or a forgotten fake passes silently); a third-party
  network blocker such as `pytest-socket` (a new dependency, and it can't see libpq's C-level connections anyway).
- **Tradeoff accepted:** The fake DB does not check SQL — a typo'd query or wrong column order passes unless a test
  asserts on `fake_db.queries(...)`; cosine ranking is Postgres's job, so offline tests can only check that the
  database's order and the `threshold`/`top_k` params are respected. Unscripted statements return no rows rather than
  failing. Loopback and Unix sockets stay allowed. Existing live tests are untouched until 11.2/11.4 move them over.
- **Revisit if:** The app starts using cursors, transactions or dict rows; a real-SQL bug slips past the fakes (then add
  a Postgres service-container job); or a new external service is added (give it a fake too).

### D-039 · Tests that need real services are marked `live` and excluded from plain `pytest` (Phase 11.2)
- **Date · by · source:** 2026-11-06 · Vaishnavi (with Claude) · Build guide (Phase 11 "Done when": `pytest` passes
  with no real API calls) + Agent (the opt-in marker was recommended and not objected to)
- **Decision:** New `pytest.ini` registers a `live` marker and sets `addopts = -m "not live"`. Tests that only make
  sense against the real Neon database or Gemini — retrieval *quality* (failover → DR runbook, k8s rollback → K8s guide),
  live `/health` counts, the real ticket tools, the live D-027 regression and the real `/cron/reindex` — are marked
  `live` and run with `pytest -m live` (a later `-m` replaces the default). Each got an offline counterpart where one
  makes sense: RAG ranking against a fake that does the same cosine/threshold/LIMIT math plus a test pinning the SQL's
  ranking clauses; `tool_lookup_runbook` and the database diagnostic on `fake_db`; dispatch of all 7 tools with spies
  (`tests/test_agent_dispatch.py`); an offline twin of the D-027 bundled-`is_final` test.
- **Why:** The guide's "Done when" is about plain `pytest`, so the default must be the offline set; making the live set
  opt-in (rather than deleting it) keeps the real end-to-end checks available before a deploy. Live checks of retrieval
  quality are evaluation, not unit tests — they belong with Phase 13. Excluding by default also stops the default run
  from writing test tickets into whatever database `.env` points at (often the live one, see Deployment).
- **Alternatives considered:** Delete the live tests (loses the only real end-to-end checks); an env var such as
  `RUN_LIVE=1` with `skipif` (works, but a marker is the pytest-native way and shows up in `-m` selection and
  `--markers`); leave everything in the default run and only filter in CI (then plain `pytest` breaks the guide's
  criterion and keeps hitting the live DB locally).
- **Tradeoff accepted:** Live tests now run only when someone asks for them, so a real-service regression is caught
  later (before a deploy, if `pytest -m live` is part of the routine — Phase 14 smoke test). The offline ranking test
  can't catch a wrong SQL operator by behaviour, only by the SQL-shape test. As of 11.2, 47 unmarked tests in 8 files
  still reach Postgres (and 3 reach the network) in the default run — they move in 11.4 before CI (11.5).
- **Revisit if:** CI gets a real Postgres service container (some `live` tests could then run there), or the live set
  grows big enough to need its own scheduled job.

### D-040 · An in-memory copy of the app's tables (`MemoryDB`), with every DB test also run against real Postgres (Phase 11.4)
- **Date · by · source:** 2026-11-06 · Vaishnavi (with Claude) · Agent (needed for the Phase 11 "Done when")
- **Decision:** `tests/conftest.py` gains `memory_db`: the `tickets`, `conversations`, `messages`, `documents`, `chunks`
  and `rate_limits` tables kept in Python on top of `fake_db`, answering exactly the statements the app sends (including
  `retrieve()`'s vector search with the same cosine/threshold/`LIMIT`, the CRM's priority ordering, `ON DELETE CASCADE`
  for chunks, and the limiter's upsert). State carries across statements, so create → fetch → update works. Any statement
  it does not recognise is recorded and **fails the test at teardown**. A parametrized `db_backend` fixture runs each
  database-dependent test twice: on `memory_db` by default, and against the real Postgres from `.env` as a `live`
  variant. `test_crm.py`, `test_api_v2_5.py`, `test_rate_limit.py`, `test_input_validation.py` and the ingest test use
  `db_backend`; `test_retry.py`'s `/ask` tests and `test_auth_protection.py` use `memory_db` directly; the two live-model
  prompt-injection tests are `live`.
- **Why:** 47 tests in the default run still reached Postgres (and 3 the network) after 11.2, so plain `pytest` broke the
  guide's "no real API calls" and CI would have nothing to connect to. These tests check *behaviour across statements*
  (a ticket created then fetched, a counter that climbs to its limit), which scripted per-statement rows can't express
  without rewriting every test. Keeping the same test bodies and adding a real-Postgres variant means the fake is checked
  against the real database whenever someone runs `pytest -m live`, instead of being trusted.
- **Alternatives considered:** Mark all 47 `live` (CI would then not test the CRM, conversations or rate limiter at all);
  rewrite each with scripted rows (loses the round-trip checks, and much more churn); a Postgres service container in CI
  (real SQL, but slower, needs schema setup and secrets-free bootstrapping — still the right next step if the fake ever
  misleads us); SQLite (no pgvector, different SQL).
- **Tradeoff accepted:** `MemoryDB` matches statements by fragment and does not parse SQL. A changed statement that keeps
  its fragment is answered as before — e.g. flipping `ORDER BY id ASC` to `DESC` on the history query, or reordering a
  `SELECT`'s columns, goes unnoticed offline (both confirmed by mutation checks) and is caught only by the `live` variant.
  `test_unicode_and_sql_looking_text_is_stored_verbatim` proves parameterisation only in its `live` run. Two tests
  (`test_crm_stats_direct`, `test_api_list_tickets_endpoint`) relied on leftover rows in the shared live database and
  now create the tickets they assert on.
- **Revisit if:** The app's SQL changes often enough that keeping `MemoryDB` in step is a chore, or a bug reaches
  production that the fake hid — then move the DB tests to a Postgres service container in CI.

### D-041 · GitHub Actions runs the offline suite on every push, with no secrets, on Python 3.11 and 3.12 (Phase 11.5)
- **Date · by · source:** 2026-11-06 · Vaishnavi (with Claude) · Build guide (11.5: "a GitHub Actions workflow that runs
  `pytest` on every push")
- **Decision:** `.github/workflows/tests.yml` runs plain `pytest` (so `live` tests stay excluded via `pytest.ini`) on
  every push and pull request, on `ubuntu-latest`, Python 3.11 and 3.12. It sets **no secrets or env vars**, has
  read-only `contents` permission, cancels superseded runs on the same ref, and checks out **full history**
  (`fetch-depth: 0`). `pytest.ini` gains `pythonpath = .`. The cron-secret test now sets its own `CRON_SECRET`, and an
  offline twin of the live `/cron/reindex` test ingests the real `data/docs/` into `memory_db`; `fake_gemini` zeroes
  ingestion's 0.5 s free-tier pause.
- **Why:** No secrets proves the "no real API calls" half of the Phase 11 "Done when" on a machine with nothing to
  connect to, and means a fork or PR can't exfiltrate anything. 3.11 is the team's local venv and 3.12 is Vercel's Python
  runtime, so both are covered. Full history matters because `tests/test_secrets_hygiene.py` runs `git log --all`; on
  the default shallow clone it would scan one commit and pass without checking anything. A local CI simulation (fresh
  clone, no `.env`, `env -i`, fresh 3.12 venv with the latest dependencies) found that plain `pytest` could not
  `import app` — local runs only worked through `python -m pytest`, which adds the current directory itself — hence
  `pythonpath = .`. The cron test had asserted that `.env` contains `CRON_SECRET`, which CI never has; the reindex twin
  went from 40 s to 0.05 s once the pacing meant for real Gemini was skipped.
- **Alternatives considered:** Running `live` tests in CI with repository secrets (spends Gemini quota and writes to the
  live database on every push, and leaks are possible from PR workflows); a Postgres service container (deferred, see
  D-040); pinning dependency versions (not done: `requirements.txt` is unpinned, and CI installing the latest each run
  surfaces upstream breakage early — but it can also turn CI red with no code change).
- **Tradeoff accepted:** CI never exercises real Neon/Gemini — `pytest -m live` stays a manual step (a candidate for the
  Phase 14 smoke test). Unpinned dependencies can break CI on an upstream release. In CI the app falls back to the
  default `jwt_secret="dev-secret"` (D-007), so PyJWT emits `InsecureKeyLengthWarning`s — expected there, irrelevant to
  production, which sets `JWT_SECRET` in Vercel.
- **Revisit if:** A dependency release breaks CI (then pin), CI gets slow, or the team wants live checks before every
  deploy (then a separate, manually triggered `live` workflow with secrets restricted to `main`).
- **Partly superseded by D-044** (2026-11-06): the "unpinned dependencies" tradeoff — an unpinned release broke
  production, not CI, so dependencies are now pinned.

### D-042 · Structured JSON logs on stdout, one `request` line per request, correlated by a request id (Phase 12.1)
- **Date · by · source:** 2026-11-06 · Vaishnavi (with Claude) · Build guide (12.1: "structured JSON logging (request id,
  user, latency, which tools were called)")
- **Decision:** New `app/logs.py` on the standard `logging` module: a `knowops` logger with one handler that writes one
  JSON object per line to stdout (`ts`, `level`, `event`, `request_id`, then the event's own fields). A pure ASGI
  `RequestLogMiddleware`, added as the outermost middleware, gives each request an id (an inbound `X-Request-ID` is kept
  only if it matches `^[A-Za-z0-9._-]{8,64}$`, otherwise a uuid4), returns it as `X-Request-ID`, and writes one `request`
  line with method, path, status, latency, user, the tools the agent ran, Vercel's `x-vercel-id`, and the error type on
  an unhandled error (level: info < 400, warning 4xx, error 5xx). (Since D-046 it is the second-outermost middleware, just inside the request counter.) All 8 `print()` calls became named events
  (`retrying`, `rate_limiter_unavailable`, `kb_chunk_dropped`, `history_persist_failed`, `n8n_webhook_failed`,
  `tool_blocked`, `run_tainted`, `ticket_tainted`) that carry the same `request_id`. New optional `LOG_LEVEL` (INFO).
- **Why:** Vercel collects stdout as runtime logs and its log search reads JSON fields, so one line per event is enough —
  no log service, nothing new to pay for. The per-request state lives in a context variable as one *mutable* record:
  FastAPI runs sync dependencies and routes in a threadpool with a *copy* of the context, so a value set there (the user
  from the JWT, the tools from the agent loop) would never reach the middleware — a mutation check that hands the
  context a copy loses both. A pure ASGI middleware instead of `@app.middleware("http")` avoids `BaseHTTPMiddleware`'s
  extra task and its known streaming/context pitfalls. The inbound id is validated because it is copied into a header
  and the logs: a forged value with a quote or newline could otherwise inject a fake log line.
- **Alternatives considered:** `structlog` or `python-json-logger` (a dependency for ~100 lines we own and test);
  OpenTelemetry or a hosted log service (more setup than the guide asks for, and Vercel's runtime logs are free);
  keeping `print()` with a prefix (not searchable by field, no request id).
- **Tradeoff accepted:** The `request` line logs the path but not the query string, body, headers or question text, so a
  log alone can't replay a request — deliberately, so a token, password or user's data never lands in the logs (a test
  checks for each). Exception text is kept short (120 chars) and dropped entirely for the n8n webhook, whose URL could
  carry a secret. Hobby keeps runtime logs for 1 hour only. Logging goes through a lock-protected handler, a little
  per-line overhead (not measured separately; a whole offline `/agent/chat` test request, logging included, took ~1 ms).
- **Revisit if:** Logs need to outlive Vercel's retention (add a log drain), or per-request detail needs to grow beyond
  what fits on one readable line (Phase 12.2 adds the agent trace on failure only).

### D-043 · Every agent run logs one `agent_run` event; anything but a clean run includes its bounded trace (Phase 12.2)
- **Date · by · source:** 2026-11-06 · Vaishnavi (with Claude) · Build guide (12.2: "log the full tool-call trace when the
  agent loop fails or hits its iteration cap")
- **Decision:** `run_agent()` is now a thin wrapper around the unchanged loop (`_run_agent_loop`). It times the run and,
  in a `finally`, writes one `agent_run` event: `outcome` (`completed`, `max_steps`, `generation_error`, `crashed`),
  steps, `max_steps`, tools, `duration_ms`, `tainted`, plus `error_type`/`error_step`, `summary_error_type` and
  `tool_errors` when they apply. A clean run logs that summary at info. Any other run also logs `trace` —
  thought ≤200, args ≤200, observation ≤300 and final answer ≤200 characters per step, the whole trace ≤~4,000
  characters by dropping the oldest middle steps (first and last always kept, `omitted_steps` says how many) — at
  warning, or error for a crash, which is still re-raised. The API response is unchanged.
- **Why:** The loop deliberately turns every problem into a "final answer" (D-026), so from outside a generation error
  or a capped run looked like success; the only record was the HTTP response, gone once it was sent. The guide's Phase
  12 "Done when" is seeing exactly what the agent did from the logs. "Fails" is read broadly — a failed summary, a tool
  error and a tainted (possible prompt-injection) run are all moments someone will want the trace. Logging it only then
  keeps normal traffic readable. The `finally` means a crash keeps the steps it got through; before, a 500 lost them.
  The budget exists because Vercel truncates long log messages (its log API has a `messageTruncated` field; the exact
  limit isn't documented in what was found), and a cut line would lose the end of the run — where a failure usually is.
- **Alternatives considered:** A log line per step (many lines per run, and a step's line means little without its run);
  logging the full trace for every run (noisy, and longer lines); storing traces in Postgres (more schema and cost for a
  debugging aid that Phase 13's eval can revisit).
- **Tradeoff accepted:** The trace includes the agent's tool arguments and observations, clipped. They can echo user
  text (for example a ticket subject the agent writes into `create_ticket`) — a deliberate exception to D-042's "no
  user text", since the guide asks for what the agent *did*. The task prompt itself is never logged. Clipping means a
  long observation is only partly visible; the full one is still in the API response. The ~4,000-character budget is a
  guess pending Phase 12.3's look at real Vercel logs.
- **Revisit if:** Phase 12.3 shows Vercel truncating these lines (lower the budget) or showing much more (raise it), or
  traces need keeping longer than Vercel's 1-hour Hobby retention.
- **Checked 2026-11-06 (12.3 follow-up):** a live `agent_run` line *displayed* as `… (truncated)` through the Vercel MCP
  log tool, but Vercel stored it whole: a full-text search for `synthesized`, a word only in the line's last step, matched
  it (a nonsense word matched nothing). The cut is the tool's display; the budget stays as it is.

### D-044 · Pin every dependency to an exact, live-tested version (hotfix found by Phase 12.3)
- **Date · by · source:** 2026-11-06 · Vaishnavi (with Claude) · Agent (production outage found while verifying 12.3)
- **Decision:** `requirements.txt` pins the ten top-level packages to the exact versions in the local venv that passed
  `pytest -m live` against real Neon + Gemini (`google-genai==2.28.0`, `fastapi==0.142.2`, …). Upgrades are deliberate:
  bump a version, run `pytest` and `pytest -m live`, then deploy. `.env.example`'s `GEMINI_CHAT_MODEL` default changes
  from the retired `gemini-2.5-flash` to `gemini-flash-lite-latest`, matching `app/config.py` and both environments.
  Partly supersedes D-041's "unpinned dependencies" tradeoff.
- **Why:** The first real request in Phase 12.3 logged `agent_run outcome=generation_error error_type=ClientError` —
  `404 NOT_FOUND: models/gemini-flash-lite-latest is not found for API version v1` — and `/ask` returned 503 on
  production. `google-genai` 3.0.0 was released that day; every fresh Vercel build installed it, and it calls Gemini's
  stable `v1` API, where the `-latest` alias doesn't exist (2.28.0 uses `v1beta`, where it does — the same model name
  works there, checked with the real API). CI stayed green because it is offline by design (D-041): the fakes never
  reach Google, so no CI run could see this. The agent answered HTTP 200 with a fallback text, so without 12.2's
  `agent_run` event the outage would have looked like a normal answer. Verified: a fresh Python 3.12 venv installed
  from the pinned file gets 2.28.0, uses `v1beta`, and a real `chat_completion` call succeeds; the offline suite passes
  on it (324).
- **Alternatives considered:** `google-genai<3` (still lets a 2.x minor change behaviour unseen); forcing
  `api_version="v1beta"` in `get_client()` (works around this one symptom, but the next major release could change
  something else); switching to a model name that exists on `v1` (untested against our prompts and JSON mode, and it
  would still leave builds unreproducible); a lock file with every transitive dependency (more reproducible still —
  a candidate if a transitive package ever breaks us; for now top-level pins).
- **Tradeoff accepted:** No automatic security or bug-fix updates; someone has to bump versions on purpose. Transitive
  dependencies (e.g. `pydantic`, `starlette`) are still resolved freshly within the pinned packages' ranges. The deeper
  gap stays: nothing checks the *deployed* app against real Gemini automatically — that is the Phase 14 smoke test.
- **Revisit if:** A transitive dependency breaks a build (move to a full lock file), or a pinned package has a security
  fix to take.

### D-045 · A capped run's summary is asked for in plain text; every Gemini request times out, and a slow call is not retried (Phase 12 follow-up)
- **Date · by · source:** 2026-11-06 · Vaishnavi (with Claude) · Agent (both seen in Phase 12.3's live logs)
- **Decision:** (1) The summary call after a capped agent run no longer reuses the full conversation history, whose tool
  list ends "Format your thought and next action as JSON". It gets `Task: …` + the step transcript + `SUMMARY_INSTRUCTION`
  (plain text, Markdown fine, no JSON), and its reply goes through `plain_text_answer()`, which unwraps a JSON object
  (bare or in a code fence) to its `final_answer` (or `thought`) and leaves every other text alone. (2) `get_client()`
  sets `HttpOptions(timeout=…)` from the new `GEMINI_TIMEOUT_SECONDS` (25), and `retry_call` gains `budget_s`: no new
  attempt once that many seconds have passed since the first began, backoff included. All four Gemini call sites pass the
  timeout as their budget; the Postgres connect is unchanged. Spending the budget logs `retry_budget_spent`.
- **Why:** Live, a capped run's answer to the user began `` ```json {"thought": … `` — the model followed the JSON
  instruction it was handed. Plain-text instructions fix the cause; the unwrap guards against the model doing it anyway.
  Live, one `/ask` took 96.7 s, ~83 s in a single Gemini call, because no request had a timeout. A timeout alone would not
  help: the SDK raises `httpx.ReadTimeout`, which `retry_call` treats as transient, so a slow model would be retried up to
  4 × 25 s. With the budget, a timed-out call fails once (`/ask` → its existing 503, "The read operation timed out", after
  ~25 s), while fast 429/5xx failures still get all their retries. Worst case per call stays under ~2 × the timeout.
  Checked against the real API: the SDK's timeout is in milliseconds; normal embed and chat calls take ~0.5 s and ~1.1 s.
- **Alternatives considered:** A separate summary system prompt only (the JSON instruction is in the *history*, not the
  system prompt — it would not have helped); JSON mode for the summary too, then extracting `final_answer` (works, but the
  summary is prose by nature); counting a timeout as non-transient (then a brief network blip gets no retry either);
  a global request deadline across all calls in a request (more plumbing; per-call budgets bound it well enough).
- **Tradeoff accepted:** A genuinely slow but successful Gemini answer (> 25 s) now becomes an error — the user gets a 503 to
  retry instead of a very long wait. `/ask` makes two Gemini calls, so its worst case is still ~2 × 2 × 25 s.
  `plain_text_answer` keeps a JSON reply that has neither `final_answer` nor `thought` as raw text.
- **Revisit if:** Logs show many `retry_budget_spent` events on calls that would have succeeded (raise the timeout), or a
  capped run's answer still comes back structured.

### D-046 · `GET /metrics`: hourly request counters in Postgres, written after every API request (Phase 12.4, stretch)
- **Date · by · source:** 2026-11-06 · Vaishnavi (with Claude) · Build guide (12.4: "a simple `/metrics` endpoint: request
  count, average latency, error rate")
- **Decision:** New `app/metrics.py`. `RequestMetricsMiddleware` (pure ASGI, the outermost middleware) counts every API
  request after its response is done into table `request_metrics` — one row per (hour, method, route) holding the request
  count, 5xx count, 4xx count, summed latency and max latency — with one upsert, on one reused plain connection, failing
  open (a warning, never a broken request). Routes are labelled with their **template** (`/tickets/{ticket_id}`), unknown
  URLs share one `(unmatched)` label, and the web console `/`, `/metrics` itself, static files, `/docs`, `/redoc`,
  `/openapi.json` and CORS preflights are not counted. `GET /metrics?hours=24` (1–168, JWT required) returns totals and a
  per-route breakdown: requests, average and max latency, server errors, client errors, and error rate. **Error rate is
  5xx responses ÷ requests**; 4xx (401, 422, 429, 404) are reported separately because they are mostly callers' mistakes.
  The window is the current partly-elapsed hour plus the `hours - 1` before it. New optional `METRICS_ENABLED` (true);
  the table self-creates (also in `scripts/init_db.sql`); rows older than 30 days are pruned on ~1% of writes. An outage
  on the *read* side returns 503, not zeros.
- **Why:** Same argument as the rate limiter (D-036): serverless instances restart and run side by side, so in-memory
  counters would reset on every cold start and each instance would count only its own traffic. Postgres is already
  shared. Hourly sums are exact for count, average and error rate, and cost a handful of rows per hour. Labelling by
  template (found in `scope["route"]`, checked empirically) keeps the table bounded: a scanner requesting random URLs
  makes one `(unmatched)` row instead of one per URL (a test sends five and checks for one). The middleware sits outside
  the log middleware so the counting write — after the response — is in neither the logged nor the counted latency.
  Verified against real Postgres, because `memory_db` does not parse SQL: the upsert and the aggregate query returned
  the hand-calculated totals (average 162.5 ms, max 300 ms, 1 server + 1 client error over two hours), and a
  previous-hour row fell outside a 1-hour window.
- **Alternatives considered:** In-memory counters (simplest; wrong across instances and after every cold start);
  deriving metrics from Vercel's logs (not reachable from inside the app, 1-hour retention on Hobby); a per-request row
  (exact percentiles, but unbounded growth and a heavier read); batching counts in memory and flushing every few seconds
  (cheaper per request, but a serverless instance can freeze with counts unwritten); Prometheus or a hosted service (new
  infrastructure the guide doesn't ask for).
- **Tradeoff accepted:** Every counted request pays one Postgres write — measured ~65 ms once the connection is open
  (~555 ms for the first request in a process, which also creates the table). It happens after the response is produced,
  but on a serverless runtime the invocation (and so the caller) may still wait for it. Sums and a max are stored, so
  **no percentiles** (no p95). Hourly granularity. A fault means requests go uncounted for as long as it lasts (visible
  as `metrics_unavailable` warnings). `/health` is counted, so a monitor pinging it adds to the totals; per-route rows
  show it separately. Counting is off in the test suite by default, so a test can never write to a real database.
- **Revisit if:** The 65 ms matters (batch the writes, or sample), p95 is needed (store a histogram per hour), or traffic
  grows enough that one hot row per route per hour contends (shard by instance).
