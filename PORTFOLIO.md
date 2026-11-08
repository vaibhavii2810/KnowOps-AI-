# PORTFOLIO.md — What each of us built, and the skills it shows

Phase 15.3. This maps the work in this repo to concrete, resume-ready skills — no separate
"original skills list" exists for this project, so the skills below are derived directly from
the stack and the work recorded in [AGENTS.md](AGENTS.md) and [DECISION.md](DECISION.md), not
invented. Every bullet points at something checkable: a file, a test count, or a live result
already on record there. Ownership follows the **Phase status** table in `AGENTS.md`; Phase 10
and 14 were split/shared, so their bullets are kept general rather than attributed to one person.

---

## Niranjan — backend, auth, and retrieval (Phases 2, 4–7; half of 10)

**Database design & vector search**
- Designed the Postgres schema for a RAG + CRM system from scratch (`scripts/init_db.sql`):
  `documents`, `chunks` (with a `vector(768)` column and an HNSW index for approximate-nearest-
  neighbor search), plus `tickets`, `conversations`, `messages` — verified with a real
  insert/select round trip on Neon before any app code touched it.
- Built the retrieval layer (`app/rag.py`): embeds an incoming question, runs cosine-similarity
  search (`<=>`) over the `chunks` table, returns a caller-adjustable top-k (1–20).

**Backend API development (FastAPI)**
- Stood up the FastAPI skeleton and Vercel deployment from zero (`app/main.py`, `app/config.py`
  via pydantic-settings, `app/db.py`): a `GET /health` endpoint that reports live DB and
  knowledge-base counts, deployed as a single Vercel Function.
- Designed and built `POST /ask`: retrieve → build a grounded prompt → call the LLM → return an
  answer with ranked source citations and a `conversation_id` — verified live with both an
  in-scope question (correct, cited answer) and an out-of-scope one (clean refusal, no
  hallucination).

**Authentication & access control**
- Implemented a self-rolled JWT auth system (`app/auth.py`): login against env-var credentials,
  signed tokens, and two FastAPI dependencies (`get_current_user_optional` /
  `_required`) used to gate every data-bearing route while deliberately keeping `/health` and the
  SPA shell open. Verified with 40/40 passing tests and a live check against the deployed API
  (401 with no token, 200 with a valid one).

**LLM / AI agent engineering (tool-calling)**
- Built the ReAct-style agent loop (`app/agent.py`): send conversation + tool schemas to Gemini,
  execute whatever tool it asks for, feed the result back, repeat until a real final answer —
  with a hard step cap so it can never run away.
- Found and fixed two concrete LLM-integration bugs under live load: (1) Gemini's JSON mode
  occasionally returning a malformed response with no usable text, which had been silently
  turned into a blank "success" — fixed with a retry plus a truthiness check instead of a
  key-presence check; (2) a reply bundling a tool call with `is_final: true` in the same step,
  which skipped the tool entirely while still reporting success (caught by re-querying Postgres
  directly and finding the claimed change hadn't happened) — fixed by always executing the tool
  before honoring `is_final`. Both are now permanent regression tests, not just live incidents.
- Diagnosed and fixed a prompt-priority bug where a "confirmed security breach" prompt
  triggered ticket creation instead of escalation, by making the system prompt state which tool
  wins when both apply.

**Security hardening (Phase 10, shared)**
- Co-built the production hardening pass: retry/backoff on every external call, pydantic
  validation turning malformed input into clean 422s instead of 500s, and prompt-injection
  defenses measured against a real attack (a poisoned tool result that hijacked the live agent
  1 time in 3 before the fix).

---

## Vaishnavi (with Claude Code) — content, ops, testing, and evaluation (Phases 3, 8–9, 11–13, 15; half of 10)

**Technical writing for AI grounding**
- Authored 5 DevOps/SRE runbooks as the system's entire knowledge base (`data/docs/`) and built
  the ingestion pipeline (`scripts/ingest.py`): a heading/paragraph-aware chunker (~500 chars),
  a Gemini embedding wrapper, and idempotent loading into Postgres — 80 chunks ingested, with a
  real bug found and fixed where code-fenced comments were mistaken for document headings and
  silently dropped runbook commands.

**API & product development (mock CRM)**
- Built the ticketing system end-to-end (`app/crm.py`, `POST/GET/PATCH /tickets*`): verified not
  just via the API's own responses but by querying Postgres directly to confirm rows were really
  written, including a fully natural-language path ("my requests keep timing out, log a ticket")
  through the live agent with no tool named in the prompt.

**Workflow automation**
- Built scheduled re-indexing (`GET /cron/reindex`) that only re-embeds changed files by content
  hash, found and closed a real authentication bypass on it in Preview before launch, and wired
  a best-effort Slack escalation via an n8n webhook that never breaks the agent if n8n is down.
- **Later migrated the scheduling mechanism itself** from Vercel's legacy Cron Jobs to its newer
  Schedules product, after finding the old dashboard kept no run history — set up and used the
  Vercel CLI (`vercel schedules ls/invoke/executions`) to independently confirm the new config
  and trigger a provably successful run (D-054).

**Testing & quality engineering**
- Built the project's entire offline test infrastructure from scratch: fake Gemini/Postgres
  fixtures, a network guard that fails any test making a real connection, and an in-memory
  `MemoryDB` that mirrors real Postgres behavior closely enough to be checked against it
  automatically. Result: the suite went from **2m19s with live API calls to ~2 seconds with
  none**, and stayed at **zero real network connections**, verified by a per-test connection
  inventory, not just an assumption.
- Grew the suite to 578 offline tests plus 109 marked `live`, wired into GitHub Actions on two
  Python versions, and used mutation testing as a standing verification habit throughout — not
  just "tests pass" but "tests fail when the code is deliberately broken."
- Independently fuzzed every route with 76 hostile requests and found 6 real 500-level crashes
  (NUL bytes, negative limits) plus a 7th found separately — login crashing on any non-ASCII
  character, from a stdlib function that raises instead of returning false — before any of them
  could reach a real user.

**Observability (logging & monitoring)**
- Designed structured JSON logging with a request id threaded through every log line and
  response header (`app/logs.py`), plus a bounded step-by-step trace logged automatically
  whenever an agent run fails or hits its cap — verified live by sending one real request and
  reading exactly what the agent did back out of Vercel's own runtime logs.
- That verification step **found a real production outage** (an unpinned dependency silently
  broke `/ask` and the agent after an upstream release) that had been invisible until the new
  logging existed to show it — fixed by pinning dependencies and verified live again afterward.
- Built a Postgres-backed `GET /metrics` endpoint (request count, average latency, error rate
  per route) as a stretch goal, measured its own write cost, and used its first real numbers to
  surface a genuine performance finding (multi-second database latency) that's now tracked as a
  known issue rather than hidden.

**AI evaluation engineering**
- Built an evaluation harness from the ground up (`evals/`): a 19-question golden set that is
  *itself* machine-validated against the source documents (so a wrong test can't silently pass),
  a scoring pipeline with exact-fact matching and accepted wording variants, an opt-in LLM-judge
  second opinion, per-question latency with a slowness flag, and five heuristic hallucination
  checks (uncited answers, phantom citations, unsupported numbers, unsupported code, answering
  something that should have been refused).
- Ran it live against a real production-adjacent system and used the results to find and fix two
  flaws in the golden set itself (a mislabeled fact, a brittle exact-phrase match), landing at a
  reproducible **19/19 accuracy** baseline with the judge agreeing on every answer — then built
  `--repeat N` and a saved JSON report specifically because a single AI eval run is a sample, not
  proof, and that needed to be demonstrable, not just stated.

**Documentation**
- Maintains the project's living status record (`AGENTS.md`), a full decision log with
  explicit tradeoffs (`DECISION.md`), and a call-chain map kept true on every change (`FLOW.md`)
  — the documentation behind every verification claim in this file.

---

## Shared (Phase 14 — deployment & final integration)

- Ran a full production smoke test (login → ask → create ticket → check ticket → trigger
  reindex) against the live deployed URL, all verified with real HTTP responses rather than
  assumed from local tests passing.
- Confirmed and hardened the production configuration itself: which secrets exist in which
  environment, and a real gap found and recorded rather than silently fixed without a record
  (Preview's Gemini key was scoped to one git branch only).

## How to use these bullets

Each one above already names the file and the evidence behind it, so a resume bullet can keep
the headline claim and drop the file reference — for example: *"Built and load-bearing-tested a
ReAct tool-calling agent for Gemini, fixing two silent-failure bugs found under live traffic
before they reached a monitoring system — went from invisible to logged, fixed, and
regression-tested."* The full, checkable version of every claim here lives in
[AGENTS.md](AGENTS.md) and [DECISION.md](DECISION.md).
