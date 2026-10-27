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
