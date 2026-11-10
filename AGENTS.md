# Agent Context — AI Support & Knowledge Ops Platform (KnowOps AI)

Shared context for every coding agent in this repo (Antigravity reads this file natively;
Claude Code reads it via `CLAUDE.md`). It is the single source of truth for project status.

> **Rules for every agent (details in [Rules for every code change](#rules-for-every-code-change)):**
> 1. **Log decisions** with their reasons in [`DECISION.md`](DECISION.md).
> 2. **Keep [`FLOW.md`](FLOW.md) true** whenever entry points, routes or call chains change.
> 3. **Quiz the human before a code change counts as accepted.** No pass, no acceptance.
> 4. **When a chunk or phase is finished**, run the [Phase completion protocol](#phase-completion-protocol).
>    Humans can trigger it with `/phase-done <phase>` (Antigravity and Claude Code).

## Project

FastAPI backend that answers DevOps/SRE support questions from a runbook knowledge base (RAG with
citations) and runs a ReAct agent that can search the KB, create/check/triage tickets, and escalate.
A small web console is served at `/`.

Stack (all free tier): FastAPI on Vercel (Hobby) · Neon Postgres + pgvector · Google Gemini
(chat + `gemini-embedding-001`, 768 dims) · self-rolled JWT · CRM mocked in Postgres ·
Vercel Cron + local n8n.

Team: **Niranjan** and **Vaishnavi** (Vaishnavi works with Antigravity).

## Phase numbering — read this first

The plan is the shared **Build Guide (15 phases)**. Always use build-guide numbering.
Code comments and the `Phase_*_Report.pdf` files use an older *sprint* numbering
(e.g. `app/auth.py – Phase 2.5`, `app/agent.py – Phase 3.2`) that does **not** match the guide.

## Phase status

Legend: ✅ done · 🟡 partial / code exists but not verified against the guide · ⬜ not started

| # | Build-guide phase | Owner | Status |
|---|---|---|---|
| 1 | Accounts & env setup | Both | ✅ Done |
| 2 | DB schema | Niranjan | ✅ Done |
| 3 | KB content + RAG ingestion | Vaishnavi | ✅ Done |
| 4 | FastAPI skeleton + Vercel deploy | Niranjan | ✅ Done |
| 5 | JWT auth | Niranjan | ✅ Done |
| 6 | RAG retrieval + `/ask` | Niranjan | ✅ Done |
| 7 | Agent + tool-calling | Niranjan | ✅ Done |
| 8 | Mock CRM / tickets | Vaishnavi | ✅ Done |
| 9 | Automation (cron + n8n) | Vaishnavi | ✅ Done — all 5 chunks live; scheduled cron run confirmed in the Vercel dashboard (reported by Vaishnavi, 2026-11-03) |
| 10 | Error handling & security | Split 50/50 | ✅ Done |
| 11 | Testing & QA | Vaishnavi | ✅ Done — plain `pytest` makes zero real calls; green on GitHub Actions (3.11 + 3.12) for `main` and `sprint-2` at `6111862` (D-038–D-041) |
| 12 | Logging & monitoring | Vaishnavi | ✅ Done — JSON logs + request id (D-042), `agent_run` trace (D-043), checked in Vercel's runtime logs (12.3, which exposed an outage fixed by pinning deps, D-044); `GET /metrics` (12.4, stretch, D-046) deployed and verified live |
| 13 | AI eval harness | Vaishnavi | ✅ Done — 13.1 golden set (D-047), 13.2 `python -m evals` runner, keyword scoring + opt-in judge (D-048), 13.3 per-question latency + slow flag (D-050), 13.4 likely-hallucination flags (D-051), 13.5 JSON report + `--repeat` (D-052); committed baseline `evals/reports/baseline-2026-11-07.json` (3 runs: 18/19, 19/19, 19/19); **every question is over 5 s** (median ~5.8 s in-process, 14 s deployed). The older `tests/eval_rag.py` is retrieval-only |
| 14 | Deployment & final integration | Both | ✅ Done — all 5 chunks verified live (2026-11-08) |
| 15 | Docs & wrap-up | Vaishnavi | 🟡 Partial — 15.1 (README), 15.3 (PORTFOLIO.md) and 15.4 (Future work) done; 15.2 (demo recording) still needs a human |

### Completed phase details

**Phase 1 — Accounts & env setup** ✅
Vercel, Neon (via Vercel Marketplace), Google AI Studio and GitHub accounts exist; `.venv` + `requirements.txt`
install cleanly; local `.env` has every variable in `.env.example`.

**Phase 2 — DB schema** ✅
`scripts/init_db.sql` run on real Neon: `documents`, `chunks` (`vector(768)` + HNSW index), `tickets`,
`conversations`, `messages`; pgvector enabled; manual insert/select round-trip verified.
`tickets` also has `priority`, `resolution_notes`, `updated_at` (needed by `app/crm.py`).

**Phase 3 — KB content + RAG ingestion** ✅
5 DevOps/SRE runbooks in `data/docs/`; paragraph-packing chunker (~500 chars); `scripts/ingest.py`
ingested 5 docs / 80 chunks into Neon (80 after the 2026-10-20 code-fence fix, was 78); re-running doesn't duplicate rows (`tests/test_ingest.py`).

**Phase 4 — FastAPI skeleton + Vercel deploy** ✅
- 4.1 `app/main.py` with FastAPI app and `GET /health` (reports DB + KB counts)
- 4.2 `app/config.py` (pydantic-settings, reads env / `.env`)
- 4.3 `app/db.py` (Neon connection, pgvector registered)
- 4.4 `requirements.txt`
- 4.5 Repo deploys through Vaishnavi's Vercel project **`knowops-ai-`**, Git-connected to
  `vaibhavii2810/KnowOps-AI-` (see Deployment)
- 4.6–4.7 Env vars and the live `/health` check are on that same project

**Phase 5 — JWT auth** ✅
- 5.1 `APP_USERNAME`, `APP_PASSWORD`, `JWT_SECRET` in `.env` and Vercel (Preview + Production)
- 5.2 `app/auth.py`: `POST /auth/login` checks env-var credentials, returns a signed JWT
- 5.3 `get_current_user_optional` / `get_current_user_required` FastAPI dependencies verify the bearer token
- 5.4 `Depends(get_current_user_required)` added to `/conversations*`, `/ask` (was optional, now required),
  `/tickets*`, `/agent/chat`, `/agent/triage/{id}`. `GET /`, `/static/*`, `/docs`, `/redoc` stay open (the SPA
  shell has no data and must load before anyone can log in); `/cron/reindex` keeps its own `CRON_SECRET` check
  instead (service call from Vercel Cron, not an operator) — see D-022. `static/js/app.js` sends the JWT on
  every now-protected call and gates those actions behind the login modal when logged out.
- 5.5 `tests/test_auth_protection.py` (new) plus updates to `tests/test_crm.py` / `tests/test_api_v2_5.py`
  (via a shared `auth_headers` fixture in `tests/conftest.py`) prove 401 with no token and 200 with a valid
  one, locally (40/40 pytest) and live — checked directly against the `sprint-2` Vercel deployment
  (commit `b03a462`): `/tickets`, `/conversations`, `/ask` all 401 without a token, login succeeds, `/tickets`
  with the token returns 200.

**Phase 6 — RAG retrieval + `/ask`** ✅
- 6.1 `app/rag.py` `retrieve()`: embeds the question, cosine search (`<=>`) on `chunks`; default `top_k=5`,
  caller-adjustable 1–20 (D-023)
- 6.2 `app/llm.py` `SYSTEM_INSTRUCTION` + `chat_completion()`: context-only prompt, cite the source title,
  fixed "I don't have enough information…" refusal
- 6.3 `POST /ask` in `app/main.py` (JWT required): retrieve → Gemini → answer + `sources` (title, heading,
  similarity) + `conversation_id`
- 6.4 / 6.5 checked live on the `sprint-2` deployment: the failover question returns the full procedure citing
  Disaster Recovery Runbook › 4.2; "best pizza topping" is refused with no sources
- Bug found and fixed on the way: `scripts/ingest.py` `split_by_headings` treated `# comments` inside ``` fences
  as headings, dropping the runbook commands (so `/ask` refused the failover question). Now ignores fenced
  lines; KB re-ingested to 80 chunks; regression tests in `tests/test_ingest.py`.

**Phase 7 — Agent + tool-calling** ✅
- 7.1 Added `create_ticket` and `escalate_to_human` tools (D-025), closing the gap D-015 flagged. All 7 tools
  registered: `lookup_runbook`, `get_ticket`, `create_ticket`, `update_ticket`, `escalate_to_human`,
  `run_system_diagnostics`, `execute_recovery_action`
- 7.2 `run_agent()`'s loop verified live (send conversation+tools → Gemini → execute tool → feed result back →
  repeat). Found and fixed a real bug: Gemini's JSON mode occasionally returns `finish_reason=MALFORMED_RESPONSE`
  with no text, which the old code silently turned into a blank resolution; now retries 3x and the "got a final
  answer" check tests truthiness, not key presence (D-026)
- 7.3 Hard cap verified: `max_steps` bounds the `for` loop (API-level `ge=1, le=10`; `run_agent` default 5,
  triage 4). Forced a multi-tool-hungry task with `max_steps=2` — confirmed it stops exactly there and still
  synthesizes a non-blank answer
- 7.4 `/agent/chat` + `/agent/triage/{id}` (the guide's own "or a new /agent/chat" option, not a deviation) — JWT
  required, confirmed live. Found and fixed a second real bug: a Gemini reply bundling a tool call with
  `is_final: true` in the same step skipped tool execution entirely while still reporting success (a live
  triage call claimed a ticket was resolved when it wasn't, confirmed by re-fetching from Postgres). Now the
  tool always executes before the loop honors `is_final` (D-027)
- 7.5 All 7 tools tested individually with a targeted prompt, live. Found and fixed a prompt-priority gap: a
  "confirmed security breach, escalate immediately" prompt called `create_ticket` instead of
  `escalate_to_human`, because D-025's two new rules didn't say which wins. `AGENT_SYSTEM_PROMPT` now states
  escalation takes priority over ticketing (D-028); reproduced 3x before the fix, fixed 3x after
- Two deterministic regression tests added (`tests/test_agent.py`) covering the malformed-response and
  bundled-is_final bugs, so neither depends on reproducing a live Gemini flake again

**Phase 8 — Mock CRM / tickets** ✅
- 8.1 `app/crm.py` verified directly against Postgres: `create_ticket()` genuinely inserts a row (confirmed
  with a raw SQL query, not just the function's own return value); the lookup function is named `get_ticket()`
  rather than the guide's `check_ticket_status()` — same naming gap already weighed and declined in D-025, no
  new decision needed
- 8.2 `POST /tickets` / `GET /tickets/{id}` verified end-to-end over HTTP: 401 without a token, 200 with one,
  create → fetch round trip returns the same ticket, 404 for a nonexistent id, 422 on a missing required field
- 8.3 Natural-language end-to-end test (no tool named in the prompt), through the real `/agent/chat` HTTP
  endpoint: "my requests to /ask keep timing out, log a ticket" (EdTech example adapted to this project's
  DevOps/SRE domain per D-009) → agent called `create_ticket` → row confirmed independently via raw SQL
  (id, subject, status all correct). Ticket *lookup* by natural language was already proven the same way in
  Phase 7.5 ("what is the status of ticket #137?" → `get_ticket`), so both halves of the done-when criterion
  are covered
- 8.4 *(stretch, optional per the guide — not attempted)*: swap the mock CRM for HubSpot's free tier

**Phase 9 — Automation (cron + n8n)** ✅
- 9.1 `GET /cron/reindex` (was `POST`, counted rows only) now actually re-ingests new/changed `data/docs/`
  files via `scripts.ingest.reindex_knowledge_base()`, skipping unchanged ones by content hash (D-029).
  Verified live on both Preview and Production: editing one runbook re-embedded only that file; a no-op run
  took 2.3s with zero Gemini calls.
- 9.2 `CRON_SECRET` is now enforced in every environment, not just production (D-030) — found and fixed a
  real gap: an unauthenticated call against the live Preview deployment succeeded and triggered a real
  re-embed before the fix.
- **9.2 addendum (2026-11-10, D-055):** an external bug report (bug #1, High) found that D-030's check —
  `if settings.cron_secret and authorization != ...` — silently did nothing when `cron_secret` was *empty*,
  which was the documented, intended behavior for local dev but equally true for a real deployment that simply
  never had `CRON_SECRET` set. Fixed: a new `settings.vercel` field (reads the `VERCEL` env var Vercel sets
  automatically on every Preview/Production build, never set locally) now distinguishes the two; a deployed
  instance with no secret configured gets a 503 instead of silently running. Local dev with no secret is
  unchanged. 2 new tests in `tests/test_agent.py` (one per branch); 3 mutation checks (the deployed-no-secret
  branch removed, the wrong status code, the local-dev branch always refusing) each fail them. 580 passed,
  109 live deselected.
- 9.3 `vercel.json`'s daily cron (`0 3 * * *` → `/cron/reindex`) is syntactically correct and, as of
  2026-10-27, actually deployed to Production for the first time (`main` was fast-forwarded to `sprint-2`).
  Manually confirmed the endpoint behaves exactly as Vercel Cron's own invocation would (`GET`, `Authorization:
  Bearer $CRON_SECRET` — Vercel auto-attaches this header for a project env var literally named
  `CRON_SECRET`, confirmed via Vercel's own docs). **Dashboard confirmation (2026-11-03):** Vaishnavi reported the
  scheduled run confirmed in the Vercel Cron Jobs tab. The assistant could not see this itself — Hobby keeps only 1h
  of runtime logs and the dashboard isn't reachable from its tools — so it rests on that report.
- 9.4 Added `n8n/workflow.json` (new, separate from the existing `incident_triage_workflow.json`): a webhook
  node at `escalate-to-human` → an HTTP Request node posting to Slack. `tool_escalate_to_human` in
  `app/agent.py` now POSTs to `N8N_ESCALATION_WEBHOOK_URL` when configured (best-effort — n8n being down
  never breaks the escalation tool itself) (D-031). Verified end-to-end against a real local HTTP listener
  (not n8n itself, which wasn't actually run) — the payload shape matches what the workflow's Slack template
  expects.
- 9.5 `n8n/workflow.json` is exported and in the repo, satisfying that half of the guide's done-when directly.
- 7 new tests (3 for the webhook behavior, matching the pattern already used for 9.1/9.2's live-bug fixes).

**Phase 10 — Error handling & security** ✅
- 10.1 Done. New `app/retry.py` (`retry_call` + transient-error predicates) now wraps all 4 Gemini call sites
  (`embed_text`, `chat_completion`, agent step, agent summary) and the Postgres connect step in `get_conn()`
  (D-032). Audit found: `app/llm.py` only retried 429/503 via string matching (a plain 500 was never retried —
  verified against the committed code), the agent's Gemini calls had no retry for API errors, Postgres had none.
  Statements are deliberately not retried (autocommit + non-idempotent INSERTs). `/health` and the agent's
  DB diagnostic use `get_conn(retry=False)` so they report an outage immediately (measured: ~6.7s hang
  otherwise). 28 tests in `tests/test_retry.py` (instant — sleep is patched), including ones proving HTTP
  status codes/error text are unchanged; 80/80 pass.
- 10.2 Done. Fuzzed all routes with 76 hostile requests: **6 returned HTTP 500** (NUL bytes in ticket text and
  the status filter; negative `limit` on both list routes) and **login with any non-ASCII character was a 500**
  (`secrets.compare_digest` raises on non-ASCII `str`). Fixed all of them and tightened validation: whitespace-only
  text, NUL bytes, unknown priority/status and out-of-range `limit` are now clear 422s (D-033). Contract changes:
  invalid `PATCH` status is 422 (was 400); invalid priority on create is 422 (was silently P2); unknown list filters
  are 422. 57 tests in `tests/test_input_validation.py` (31 fail against the old code); 137/137 pass.
- 10.3 Done. Measured first: of 5 attack cases against live Gemini, **E (a poisoned `lookup_runbook` result) hijacked
  the agent into calling `execute_recovery_action` 1 time in 3** (intermittent; the other cases held; some runs were
  inconclusive because of Gemini 429s). New `app/guardrails.py` (D-034): untrusted text is fenced as `<untrusted_data>`
  with forged closing tags stripped; a narrow detector for instruction-like text drops flagged runbook chunks before
  the model sees them and *taints* an agent run (poisoned ticket or tool output), which then cannot execute
  `create_ticket`/`update_ticket`/`execute_recovery_action` (`escalate_to_human` stays allowed). Found and fixed a
  flaw in my own first version: the model wrote "ticket resolved" in the same step as the blocked call, so the
  operator was told something false — blocked steps are no longer final and a code-generated security notice is
  appended. 33 tests in `tests/test_prompt_injection.py` (scripted hijacked model, no quota); 170/170 pass.
  Detector is a heuristic — see D-034 for what it does not catch.
- 10.4 Done. `.env` is gitignored and was never committed on any branch. Scanned all 23 commits on every ref
  (13,726 added lines): none of the 7 real secret values from `.env` (Gemini key, JWT/cron secrets, admin password, both
  Neon passwords) appears anywhere, no known key format matches (the 4 loose hits were code like `api_key=settings…`,
  and the DB-URL hits were `.env.example`'s `user:password@host`), and the 8 PDFs (decompressed) are clean. Hardened:
  `.gitignore` now covers `.env.*` (so `vercel env pull` output can't be committed), `*.pem`, `*.key`, `.vercel/`,
  `.DS_Store`. 13 standing tests in `tests/test_secrets_hygiene.py` (0.3s; simulated leaks make them fail); 183/183 pass.
  The repo is public — see D-035 for what the scan does not cover.
- 10.5 Done. New `app/ratelimit.py` (D-036): per-user fixed-window counter in Postgres, 10 req/min on `/ask` and 5/min
  on the agent endpoints (`/agent/chat` and `/agent/triage` share one bucket — triage runs the same loop), configurable
  via `RATE_LIMIT_ASK_PER_MINUTE` / `RATE_LIMIT_AGENT_PER_MINUTE` (0 disables). Over the limit → 429 + `Retry-After`;
  `X-RateLimit-*` headers on every limited response; 401 still comes first and uses nothing. Stored in the database,
  not memory, because serverless instances restart and run side by side. Fail-open if the counter is unreachable.
  Measured and fixed a latency problem in my first version: `get_conn()` costs ~1.2s against the remote Neon DB
  (≈0.8s is `register_vector`), so the limiter keeps one plain connection open — ~56 ms per check, with one automatic
  reconnect when it goes stale. Self-creates its table (no manual prod migration). 16 tests in `tests/test_rate_limit.py`
  (frozen clock; removing the route wiring or introducing an off-by-one fails them); 199/199 pass.
- **Phase 10 done-when check:** the 45 permanent hostile requests (and the 76-request fuzz before them) return no 5xx,
  with the limiter on; the 5 injection cases are blocked by the guardrails even for a fully hijacked model
  (D-034). Residual risk is recorded there: the detector is a heuristic.

**Phase 11 — Testing & QA** ✅
- 11.1 Done. `tests/conftest.py` now has `fake_gemini`, `fake_db` and `no_network` (D-038). The fakes replace
  `genai.Client` and `psycopg.connect` at the root, so `get_client()` in `app/llm.py` *and* `app/agent.py`,
  `get_conn()` and the rate limiter all get them without per-module patching. `no_network` blocks non-loopback sockets
  and real Postgres connections, and fails the test at teardown even if the app swallowed the error. 12 tests in
  `tests/test_fixtures.py` (0.09s, fully offline) cover embeddings, chat, the agent loop, `retrieve()`, `/health` and
  the rate limiter on the fakes, plus the guard. Two mutation checks: patching only `llm.get_client` (the old style)
  let the agent reach Google's API and the guard caught it; a swallowed real connect left uncleared fails at teardown.
  220/220 pass.
- 11.2 Done. New `pytest.ini`: tests needing the real DB/Gemini are marked `live` and excluded from plain `pytest`;
  run them with `pytest -m live` (D-039). **Auth** (`tests/test_auth.py`, now under `no_network`): the expired-token test
  asserts the exact 401/detail/`WWW-Authenticate` (it accepted any exception mentioning "401" or "expired"); added
  tampered payload, another secret, `alg: none`, HS512 with the right secret, wrong/missing issuer, garbage tokens, and
  401s on `/auth/me` for missing/`Basic`/malformed headers and an expired token. **RAG ranking** (`tests/test_rag.py`):
  the fake DB answers `retrieve()`'s query with the same cosine/threshold/ORDER BY/LIMIT math over chunks at known
  similarities (1.0, ~0.91, ~0.60, 0); tests check order, threshold, `top_k`, the vector/params sent, and pin the SQL's
  ranking clauses; the 3 live quality checks are now `live`. **Agent dispatch** (new `tests/test_agent_dispatch.py`,
  20 tests): all 7 tools dispatched with their exact args via spies (plus a check that the case list matches
  `AVAILABLE_TOOLS`), observation fed back fenced, list/scalar args, unknown/missing action, tool error → observation,
  wrong keyword → observation, bundled `is_final` (offline D-027 twin), `max_steps` cap + one summary call, history
  carried forward. `tests/test_agent.py`: ticket/cron tests that write to the real DB are `live`; `lookup_runbook`,
  the DB diagnostic and the n8n webhook test moved onto `fake_db` (the webhook test had been creating a real ticket;
  2.2s → instant). 5 mutation checks (issuer check removed, ranking `DESC`, threshold/`top_k` swapped, positional
  dispatch removed, `max_steps` off-by-one) each fail the new tests. Default run: 254 passed, 9 live deselected;
  `pytest -m live`: 9/9 pass.
- Found and fixed on the way: 11.1's `tests/test_fixtures.py` used a made-up database URL with a short fake password,
  which the 10.4 secrets scanner (rightly) flags; switched to the `.env.example` placeholder form and amended the unpushed 11.1 commit
  (now `e755b83`) so the false positive never enters history.
- 11.3 Done. New `tests/test_ask_integration.py`: a full `POST /ask` round trip through the real route, JWT check,
  rate limiter (switched on), conversation handling, `retrieve()`, citation formatting, prompt building and message
  persistence — only Gemini and Postgres are fakes. Checks the answer, ranked `sources`, new `conversation_id` and
  `X-RateLimit-Remaining`; one embed call (`RETRIEVAL_QUERY`) and one grounded chat call carrying both fenced citations
  and the question; the DB statements in order (limiter table + hit, new conversation, vector search with `top_k`,
  saved turn with the right params). A second test covers the follow-up branch: an existing `conversation_id` loads
  its history, which reaches the model before the new question, and no new conversation is created. 6 mutation
  checks on `app/main.py` (question/answer swapped when saved, history not sent, citations dropped, caller's `top_k`
  ignored, context not sent, limiter unwired) each fail it. Offline, 0.04s. Default run: 256 passed, 9 live deselected.
- Found and fixed on the way: the 11.2 `AGENTS.md` text quoted the fake URL it was describing, so the hygiene scanner
  flagged `AGENTS.md`; reworded and amended the unpushed 11.2 commit (now `cd8d639`). Both slips passed a full run
  because `tests/test_secrets_hygiene.py` scans only tracked files — run it after `git add`, before committing.
- 11.4 Done. **Edge cases** (new `tests/test_edge_cases.py`, 47 tests): empty knowledge base — `/health` 200 with zero
  counts, `/ask` answers with no sources and the model is told "No context available." while the turn is still saved,
  `retrieve()` and the agent's runbook lookup return nothing; malformed JSON (truncated, array, bare string, number,
  `null`, trailing garbage) on all 5 JSON routes is a 422 on `body` before any DB or Gemini work; an expired JWT gets the
  exact 401 on all 12 protected routes with the limiter on and nothing counted, plus a completeness test that fails if a
  route is added without being listed as protected or deliberately open. **No more real calls**: new `memory_db` keeps the
  app's tables in memory (vector search, CRM ordering, cascades, the limiter's upsert) and fails a test that sends a
  statement it doesn't understand; `db_backend` runs each DB test on it and, as a `live` variant, on real Postgres (D-040).
  The 47 tests that reached Postgres now use it; two CRM tests had relied on leftover rows in the live DB and now create
  their own; the 2 live-model injection tests are `live`. A per-test connection inventory of the default run records
  **zero** real network or Postgres connections: 301 passed in 1.8s (was 2m19s). `pytest -m live`: 109/109 pass against real Neon + Gemini, so `MemoryDB` matches Postgres on every
  test run on both (a first live run had 1 failure + 2 errors, all a Neon connection dropped mid-statement; they passed on
  re-run and a second full run was clean — statements are not retried by design, D-032). Mutation checks: removing
  auth from `/tickets/stats` and a blank context block on an empty KB each fail; a statement `MemoryDB` has never seen
  fails at teardown with what to add; a changed statement that keeps its fragment (e.g. history `ORDER BY` flipped) is
  **not** caught offline — only the `live` variant can (D-040).
- 11.5 Done (code). New `.github/workflows/tests.yml`: plain `pytest` on every push and PR, Python 3.11 + 3.12, **no secrets**,
  read-only permissions, full git history so the 10.4 history scan really scans (D-041). Found by simulating CI locally
  (fresh clone with no `.env`, `env -i`, fresh 3.12 venv with the latest dependencies): plain `pytest` couldn't `import app`
  — only `python -m pytest` worked — fixed with `pythonpath = .` in `pytest.ini`. The cron-secret test now sets its own
  secret instead of asserting `.env` has one; a new offline twin of the live `/cron/reindex` test ingests the real
  `data/docs/` into `memory_db` and checks the second run skips every file (40 s → 0.05 s once `fake_gemini` zeroes the
  free-tier pause). Simulated CI: 301 passed, 1 skipped (needs a `.env`), 109 live deselected, on both versions.
- **Phase 11 done-when check (2026-11-06):** `pytest` passes locally (302 passed, 109 live deselected, ~2s, zero real
  network/Postgres connections per a per-test inventory) and in CI: the first GitHub Actions runs for `6111862` passed
  on Python 3.11 and 3.12, on both `sprint-2` (run 42227593073) and `main` (run 42227612601), with no secrets
  configured. `pytest -m live` (109/109) is the manual check against real Neon + Gemini.
- Pushing needed a GitHub token with the `workflow` scope (GitHub refuses workflow-file changes without it); the
  first push was rejected until the token was updated.

**Phase 12 — Logging & monitoring** ✅
- 12.1 Done. New `app/logs.py` (D-042): every log line is one JSON object on stdout (`ts`, `level`, `event`,
  `request_id`, fields) — what Vercel collects as runtime logs. `RequestLogMiddleware` (second-outermost since 12.4 added the request counter around it) gives each request an
  id (a valid inbound `X-Request-ID` is kept, anything else replaced), returns it as `X-Request-ID`, and logs one
  `request` line: method, path, status, latency, user, the agent's `tools`, `vercel_id`, and `error_type` on a 500.
  Auth records the user (`set_request_user`), the agent loop records each tool it runs or blocks (`record_tool_call`);
  both run in FastAPI's threadpool, so the request context holds one mutable record rather than plain values. All 8
  `print()` calls are now named events carrying the request id; the n8n webhook failure logs only the error type (its
  URL can carry a secret). Never logged: bodies, query strings, headers, tokens, passwords, question text. New optional
  `LOG_LEVEL`. 10 tests in `tests/test_logging.py` (offline, 0.07s) — one line + header per request, distinct ids,
  hostile inbound id replaced (no forged line), user and 401 level, the agent's tools on the line, events sharing the id,
  a 500 logged with its type, `vercel_id`, no secrets/bodies/query strings, long fields cut and newlines escaped. 5
  mutation checks (user not recorded, tools not recorded, any inbound id trusted, events losing the id, the context
  given a copy) each fail them. 312 passed, 109 live deselected.
- 12.2 Done. Every agent run writes one `agent_run` event (D-043): `run_agent()` now wraps the unchanged loop
  (`_run_agent_loop`) and logs from a `finally`, so a crash is logged with the steps it got through and still re-raised.
  Outcome is `completed`, `max_steps` (found with `for … else`), `generation_error` (the `except` that used to turn a
  Gemini/JSON failure into a normal-looking answer) or `crashed`, plus steps, tools, duration, tainted, error type/step,
  failed summary and tool-error count. A clean run logs that summary (info); anything else adds the trace — each field
  clipped, the whole ≤~4,000 chars by dropping the oldest middle steps — at warning, error for a crash. The API
  response is unchanged. 12 tests in `tests/test_agent_logging.py` (offline, 0.04s): one per outcome, failed summary,
  tool error, tainted run, clipping/truncation, and an `/agent/chat` request showing the event shares the request id
  and leaves out the prompt. 5 mutation checks (cap not detected, generation errors not recorded, crash logged as clean,
  tool errors/tainted/failed summary treated as clean, truncation keeping the oldest steps) each fail them.
  Also fixed a 12.1 gap: the JSON handler was only set up by `app.main`, so `python scripts/ingest.py` (which never
  loads it) would have shown retry notices as a bare `retrying`; its `main()` now calls `configure_logging()`.
  324 passed, 109 live deselected.
- 12.3 Done. Deployed `b19e654` (CI green on 3.11 + 3.12, both branches), then one real `/agent/chat` request on
  `knowops-ai.vercel.app` with `X-Request-ID: kops-12-3-1bfd6d939735` (echoed back). In Vercel's Production runtime logs
  (via the Vercel MCP `get_runtime_logs`, `stream=stdout`) both lines appear as JSON under that id: the `request` line
  (`/agent/chat` 200, 513.6 ms, user `admin`, `vercel_id`) and an `agent_run` warning with its trace. The guide's
  "Done when" — seeing exactly what the agent did from one request in Vercel's logs — holds. Notes: Vercel's full-text
  `query` did not match the hyphenated request id (listing recent logs did); the Gemini SDK also writes two plain-text
  lines per call (`AFC is enabled…`, httpx's `HTTP Request: POST …` — no key in it).
- **Found by 12.3: production `/ask` and the agent were down** (D-044). The `agent_run` line said
  `outcome=generation_error`, `404 NOT_FOUND: models/gemini-flash-lite-latest is not found for API version v1`, and `/ask`
  returned 503. Cause: `google-genai` 3.0.0, released 2026-11-06, was installed by every fresh Vercel build (unpinned
  `requirements.txt`) and calls `v1`, where the `-latest` alias doesn't exist; 2.28.0 uses `v1beta`. CI was green
  because it is offline by design. The agent had answered HTTP 200 with fallback text, so only the new log showed it.
  Fix: `requirements.txt` pinned to the live-tested versions; verified in a fresh 3.12 venv (2.28.0, `v1beta`, real
  `chat_completion` works, 324 offline tests pass). **Deployed as `31ef047` and verified live (2026-11-06 17:06 UTC):**
  CI green on both branches; `/ask` 200 with 5 sources (top: Disaster Recovery Runbook › 4.2 Manual Failover Steps);
  `/agent/chat` 200 running `lookup_runbook` → `run_system_diagnostics` → `create_ticket`; Vercel logs show Gemini calls
  going to `/v1beta/` with 200 OK. That verification run filed a real ticket ("Worker pod OOMKilled CrashLoopBackOff")
  in the production CRM.
- Three more things seen in the same logs, now resolved: (1) a capped run's summary came back as raw JSON — the summary
  call got the history's "Format … as JSON" instruction; it now gets the task + transcript + a plain-text instruction,
  and `plain_text_answer()` unwraps JSON if the model does it anyway (D-045); (2) `/ask` took 96.7 s, ~83 s in one Gemini
  call with no timeout — every Gemini request now times out after `GEMINI_TIMEOUT_SECONDS` (25) and `retry_call`'s new
  `budget_s` stops a timed-out call being retried, so `/ask` fails with a clear 503 in ~25 s instead (D-045); (3) the
  `agent_run` line *displayed* `… (truncated)`, but a search for a word only in its last step matched it, so Vercel
  stored it whole — no change needed (D-043 note). 19 new tests (`tests/test_retry.py`, `tests/test_agent_dispatch.py`);
  5 mutation checks each fail them; a real embed + chat call still works with the timeout (0.5 s, 1.1 s). 343 passed.
  **Deployed as `5dc81ce` and verified live (2026-11-06 17:26 UTC):** CI green on both branches; a read-only capped
  `/agent/chat` run (`max_steps=1`, no ticket) returned a plain-text answer ("To roll back a Kubernetes deployment, you
  can check the revision history using `kubectl rollout history …`", not JSON), and Vercel's log shows its `agent_run`
  with `outcome=max_steps` and the full trace; `/ask` 200 with 5 sources in 14.4 s. The 25 s timeout itself has not been
  triggered live (only tested with a fake clock).
- 12.4 Done (stretch; deployed as `80d779d` and verified live). New `app/metrics.py` and `GET /metrics?hours=24` (1–168, JWT
  required) — D-046. `RequestMetricsMiddleware` (outermost) counts every API request into table `request_metrics`: one
  row per (hour, method, route) with the request count, 5xx count, 4xx count, summed and max latency, via one upsert on a
  reused plain connection, failing open. Routes are counted by **template** (`/tickets/{ticket_id}`); unknown URLs share
  `(unmatched)`, so hostile URLs cannot grow the table; the console `/`, `/metrics` itself, static files, docs and CORS
  preflights are not counted. The endpoint returns totals and a per-route breakdown: requests, average/max latency, server
  errors, client errors and **error rate = 5xx ÷ requests** (4xx are reported separately). Counters live in Postgres, not
  memory, for the same reason as the rate limiter (serverless instances restart and run side by side). New optional
  `METRICS_ENABLED`; the table self-creates and is in `scripts/init_db.sql`; rows older than 30 days are pruned on ~1% of
  writes. 27 tests in `tests/test_metrics.py` (offline, 0.09s): counting by template, hostile paths → one row, 5xx vs 4xx,
  console/static/docs/preflights/`/metrics` not counted, disabled switch, exact totals/averages/error rate, empty window,
  window edges, pruning, auth, bounds on `hours`, missing table, a read outage → 503, a counter fault → request still
  succeeds with a warning that carries the request id, connection reuse + one reconnect. 8 mutation checks (raw URL instead
  of template, 4xx counted as errors, wrong average, window off by one, `/metrics` counting itself, static counted as
  unmatched, fault breaking the request, switch ignored) each fail them. `memory_db` gained the new statements; metrics are
  **off by default in every test** (autouse fixture) so no test can write to a real database. Because `memory_db` doesn't
  parse SQL, the real upsert and aggregate were also run against the local Neon database with unique route labels (cleaned
  up afterwards): the two-hour totals matched the hand calculation (average 162.5 ms, max 300, 1 server + 1 client error).
  Measured cost: ~65 ms per counted request (~555 ms for the first request in a process, which creates the table).
  371 passed, 109 live deselected.
  **Verified live (2026-11-06, `80d779d`, CI green on both branches and both Python versions):** I sent a known mix to
  `knowops-ai.vercel.app` — `/health` ×1, `/tickets/stats` ×2 (one 200, one 401), two unknown URLs, `/tickets/999999`, plus
  the console, a static file and `/docs` — and `GET /metrics?hours=1` grew by exactly that: +1, +2 (0 server errors, 1 client
  error), +2 under `(unmatched)`, +1 under `/tickets/{ticket_id}`, while `/`, `/docs` and `/metrics` stayed uncounted. No
  `metrics_unavailable` warnings in Vercel's logs. **Cost:** client-side, `GET /auth/me` (no database call) took a median
  400 ms before and 323 ms after (12 requests each, noise about ±100 ms) — no measurable difference, so the ~65 ms write
  measured locally is hidden by network jitter or overlapped by the platform; not proven to be zero.
  **A finding from the first numbers:** database-backed routes are slow on Production — `/health` 4.5 s, `/tickets/{id}`
  4.3 s, `/tickets/stats` 2.5 s, `/auth/login` 0.9 s on average — while `/auth/me` is 1.9 ms server-side (see Known issues).
- **Phase 12 done-when check (2026-11-06):** "you can look at a single request in Vercel's logs and see exactly what the
  agent did" holds — proven live in 12.3 (request id `kops-12-3-1bfd6d939735`) and again for the 12.2 fixes (`kops-d045-agent-01`).
  12.4 (the guide's optional stretch) is also live and verified, as above.

**Phase 13 — AI evaluation harness** ✅
- 13.1 Done. New `evals/` package (D-047): `evals/golden_set.json` — **19 items**: 16 in-scope questions covering all 5 runbooks
  (DR 4, Kubernetes 5, incident playbooks 3, on-call 2, API 2; kinds numeric / procedure / command / factual / diagnosis / list)
  and **3 that must be refused** (cookies, the 2022 World Cup, and a near-domain trap: Terraform for EKS). Each in-scope item has
  a `source_doc` + `source_section` (the heading the app's chunker produces, matching `/ask`'s `sources[].heading`), a reference
  answer and 2–5 `expected_facts` (47 in all) for the keyword scoring in 13.2. `evals/golden.py` loads it and `validate()` proves,
  offline, that every fact is in the cited section's text and in its own reference answer, that doc/section exist, that ids and
  questions are unique, that each runbook has ≥2 questions, and that each refusal item's `absent_terms` appear in no runbook.
  28 tests in `tests/test_golden_set.py` (0.06 s) — the shipped set is valid, `normalize()` ignores Markdown/dash/quote/case
  differences without making different facts match, and deliberately broken sets show the validator catches each kind of defect (wrong or missing fact, unknown doc or section, duplicates, bad kind/id/question, wrong set size, a thin runbook, a refusal item that became answerable, a malformed refusal item).
  8 mutation checks — runbook RTO changed, a heading renamed, escalation wording changed, a refused term (`terraform`) added to the
  docs, a mistyped fact, and the validator's three checks removed — each fail the tests. (My first mutation run silently applied
  nothing because the helper script had been cleared; it was caught by noticing every result was an unchanged "28 passed", and
  redone with a helper that fails loudly.) 399 passed, 109 live deselected.
- Known limit, recorded in D-047: short numeric facts are a weak check (g01's `4 hours` / `1 hour` also appear in the severity table).
- 13.2 Done. `python -m evals` (D-048; new `evals/run.py`, `client.py`, `scoring.py`, `judge.py`, `results.py`, `__main__.py`). It
  validates the golden set first (an unsound one is never scored), then asks each question through the real `/ask` — **in-process**
  by default (the route via `TestClient`, database and Gemini key from `.env`, limiter and request counter off only while open) or
  over HTTP with `--url` (logs in, waits 7 s between questions, honours `Retry-After`). An in-scope answer **passes only if it contains
  every expected fact**; coverage, whether the expected runbook section was cited (hit rate, mean reciprocal rank), false refusals
  and answered-when-it-should-refuse are reported; `--judge` adds a Gemini verdict (correct / partial / incorrect, answer fenced
  as untrusted data) beside the keyword one without changing it; `--only g01,g05`, `--top-k`, `--delay`, `--quota-wait`. A question
  that hits Gemini's quota is retried twice after 30 s. Exit 0 finished / 1 some questions had no response / 2 could not start.
  52 offline tests in `tests/test_eval_runner.py` (0.15 s): scoring rules with exact numbers, the in-process client running the
  real route against the fakes, the HTTP client on a mock transport (login, 429 wait and cap, no password in errors), the judge,
  the runner and the command line. 15 mutation checks (lenient pass, inverted refusal, a hedged answer scored as a refusal, section ignored, errors in the
  means, settings or log levels not restored, request counter left on, wait not capped, answer unfenced, no pacing, unsound set still scored, judge on errors, quota
  retry removed or too broad) each fail them. **A bug found by the full suite, not the new tests:** the in-process client silenced
  the app's loggers and never restored them, which hid the JSON log lines from 12 later tests (they passed alone); now restored,
  with a regression test. 451 passed, 109 live deselected.
- **First live baseline (2026-11-07, dev database + real Gemini; three full runs):** **18/19** in runs 2 and 3 (17/19 in run 1,
  where one question hit Gemini's free-tier quota — which is why the runner now retries those). Retrieval cited the expected
  section for **16/16** in-scope questions every complete run (mean reciprocal rank 0.90); 3/3 out-of-scope questions refused,
  including the Terraform trap; no false refusals; mean fact coverage 97.9%; judge: all 19 correct, agreeing with the keyword
  check on 18. The recurring miss in those runs, `g16`, was a **flaw in the golden set** (a remedy fact attached to a question about
  causes); its third fact is now the cause `Empty Embedding` and it passed **5 of 5** live runs (1 of 4 before). A fourth full run
  after the fix (judge on) was **18/19** again, but the miss had moved to `g09` — a brittle exact-phrase fact, see Known issues — so
  results still vary run to run (temperature 0.2). **Then `g09` was fixed too (D-049, below), and the next full run (judge on) was
  19/19 with the judge agreeing on 19/19** — one run after two golden-set fixes, so a sample, not proof.
- Follow-up to 13.2 (D-049): **accepted fact variants.** `g09`'s fact `Git repository` missed in 4 of 6 live tries because the model
  wrote "Git repositories" — right answer, exact-phrase miss. An item can now carry `fact_variants` (`{fact: [other wordings]}`, 1–3 per
  fact); a fact counts as present if the answer has it or a variant (`golden.fact_present`), reported under the canonical fact. The
  canonical fact must still appear in the runbook section and the reference answer; variants must belong to an expected fact, be ≥2
  characters and not repeat anything; refusal items carry none; the rule is wording differences only, added only after a run shows
  a correct answer missed for that reason. Used once (`g09`). `tests/test_golden_set.py` now has 34 tests and
  `tests/test_eval_runner.py` 56. 7 mutation checks (variants ignored, loader dropping them, "all" instead of "any", three validator
  rules removed, scoring bypassing them) each fail the tests. `g09` passed 6/6 live tries (2/6 before); full suite 461 passed.
- 13.3 Done. Latency per question (D-050): every line of `python -m evals` shows its time, and a question **strictly over** the
  threshold is marked `SLOW (over 5.0 s)` (`--slow-seconds`, default 5; ≤0 refused with exit 2). The summary adds mean, median, p95
  (nearest-rank — with 19 questions that is the slowest one, a test and D-050 say so), max, how many were over, the three slowest by id, and
  a note saying whether the time was measured in-process or over HTTP. Latency is the final `/ask` attempt's wall-clock time (quota,
  429 and `--delay` waits excluded); a question with no response is shown but left out of the statistics and never flagged; slowness
  changes neither pass/fail nor the exit code. New in `evals/scoring.py` (`is_slow`, `percentile`, `latency_stats`, `LatencyStats`) and
  `evals/run.py`. `tests/test_eval_runner.py` is now 71 tests: exact percentile/mean/median/slowest numbers, the strict threshold,
  errors excluded, the report text, the command line and URL mode, and the HTTP client's 429 wait not counting as latency. 11 mutation
  checks (`>=`, errors flaggable or counted, percentile rounded down, median as mean, slowest order, threshold ignored or read as
  milliseconds, non-positive accepted, threshold rounded, marker without threshold) each fail them. A display flaw found while writing
  the tests: thresholds were shown to one decimal (0.25 s as "0.2 s"); now exact. 476 passed, 109 live deselected.
- **First latency measurements (2026-11-07):** full in-process run — **19/19 questions over 5 s** (mean 5.9 s, median 5.6 s, p95 = max
  7.2 s); over HTTP against `knowops-ai.vercel.app` (`--only g05,g17`, which created 2 conversation rows in the production database) —
  **14.4 s and 14.2 s**, matching the 14.4 s `/ask` measured earlier. The same run also verified URL mode end to end for the first time
  (login, `/ask`, scoring). The slowness is systemic — 3 database connections plus 2 Gemini calls per `/ask` — so it is the database
  investigation's finding seen from the user's side, still unaddressed (see Known issues). Accuracy that run: 18/19; the miss was `g12`,
  answered from the on-call guide's §5.2 instead of the playbook's §5 (both cover pool exhaustion; passed 5/5 when retried).
- 13.4 Done. Likely-hallucination flags (D-051; new `evals/hallucination.py`; the client now keeps each source's title and text).
  Each answer that made claims is checked against what `/ask` retrieved: `answered_out_of_scope`, `no_context`, `uncited` (names none of
  the retrieved documents), `phantom_citation` (a real runbook that was not retrieved), `unsupported_quantity` (a number with a unit
  in neither the retrieved text nor the question — "4-hour", "5 mins" and `replicas=5` match their spoken forms) and
  `unsupported_code` (an inline span or code-block command not in the retrieved text). With `--judge`, the same Gemini call also
  returns `faithful` + the unsupported claim, which becomes a `judge_unfaithful` flag. Shown per question (`FLAGGED: …`) and in the
  summary (flagged/answered, counts per kind, which questions, "heuristics, not verdicts"); never changes an outcome, a pass count or
  the exit code; refusals and errors are never flagged. 43 tests in `tests/test_eval_hallucination.py` (real runbook text as the sources)
  and `tests/test_eval_runner.py` is now 91. 20 mutation checks each fail them (one exposed a vacuous assertion of mine, now a
  sentinel test). **Live:** a full run flagged **0 of 16** answers (19/19 correct); an earlier run's one flag was a false positive
  (`replicas=5` vs "5 replicas"), fixed in the parser. Detection was shown by corrupting real answers with their real sources:
  `6 hours` → `unsupported_quantity`, an invented `kubectl delete namespace production` → `unsupported_code`, an unretrieved runbook →
  `phantom_citation`, no citation → `uncited`, and the live judge marked those `faithful: false`. Blind spots (D-051): a contradiction
  that changes no number or code and a citation of a document that does not exist are caught only by the judge.
- **A flaky test found and fixed:** `tests/test_ask_integration.py` failed about 1 run in 25 because the rate limiter deletes old
  rows on a random 1% of writes and the extra `DELETE` changed the statement list the test checks (latent since 11.3). Reproduced by
  forcing the branch; the test now pins the dice; the whole suite also passes with `random.random` forced to 0.0 and to 0.999.
  539 passed, 109 live deselected.
- 13.5 Done. Every run is saved as JSON (D-052; new `evals/report.py`): `evals/reports/run-<UTC time>.json` by default (git-ignored),
  `--report PATH` to choose the file (e.g. a committed `baseline-*.json`), `--no-report` to skip. A report holds `schema_version`, `complete`,
  times, target, options, models, the golden set's SHA-256, git commit + dirty flag, a summary per run, every question's result (outcome,
  facts, retrieval rank, latency, answer, source references — not their text —, flags, judge) and a per-question stability table.
  `--repeat N` (1–10) repeats the whole set and prints/records which questions did not come out the same every time. Written atomically;
  Ctrl-C saves what finished (`complete: false`, exit 130); a failed save exits 1 but the summary is still printed. Offline tests:
  `tests/test_eval_report.py` (20) and the new CLI tests in `tests/test_eval_runner.py` (126 together); 18 mutation checks (tuples left in the
  data, retrieved text stored, wrong pass counts, nothing ever unstable, flags counted per flag, failed calls in timing, temp file left,
  unicode escaped, interrupted run called complete, scratch reports no longer ignored, git flag inverted, repeat unchecked, `--no-report`
  ignored, Ctrl-C losing the run under way, interrupted exit 0, failed save not exit 1, repeat ignored) each fail them. A bug found on the
  way: my first tests wrote a stray report into the repo's `evals/reports/`; an autouse fixture now redirects reports to a temp folder and
  checks at teardown. 574 passed, 109 live deselected.
- **Live baseline (2026-11-07, `73c4023` + uncommitted 13.5 code, so `git_dirty: true`; `--repeat 3 --judge`, in-process, 13 min):**
  accuracy **18/19, 19/19, 19/19** (mean 98.2%); the one miss was not a wrong answer but `g09` in run 1: **no response** — Gemini's read
  timed out (`HTTP 503 … The read operation timed out`, 28.5 s), the first time the 25 s timeout from D-045 fired live, and it did what it
  should (a clear 503 instead of a ~90 s hang); `g09` passed in runs 2 and 3. The command exits 1 when any question has no response, so this run
  exited 1. Flags: 0/15, 0/16 and 1/16 answers; the one flag (`g06`, run 3, `unsupported_quantity: 3 replicas`) is a **false positive** — the
  runbook says "between 3 and 10 replicas" and the answer repeated it; the quantity parser only reads "N replicas", not ranges
  ("3 and 10 replicas"). Left as is so the baseline matches the code that produced it. Judge: every answer `correct` and `faithful` in
  the lines checked. Latency: 18 questions over 5 s in every run, medians 6.0 / 6.1 / 5.8 s. The scan for `.env` secret values in the report found none
  (only the two non-secret model names).
- **Phase 13 done-when check (2026-11-07):** one command (`python -m evals`) runs the golden set and prints an accuracy / latency /
  hallucination-flag summary, and saves it as JSON — shown live above. Accuracy is a sample (temperature 0.2), not a guarantee.

**Phase 14 — Deployment & final integration** 🟡 in progress (14.1–14.4 done)
- 14.1 Done. Confirmed by effect, not by reading the dashboard: pushes to `main` and `sprint-2` on 2026-11-07 produced
  fresh Vercel deployments on their own for both (production `dpl_F3AcygsD5dRyqaoJjQSwyTJeNEAb`, preview
  `dpl_HLvkPujcxQyYQ5B45pb749xLfF4j`), both `READY`, via the Vercel MCP — so the GitHub↔Vercel connection from Phase 4
  is live and current.
- 14.2 Done. `filter_project_envs` on the project shows `DATABASE_URL` (and the rest of the Neon-injected set —
  `PGHOST`, `POSTGRES_URL`, etc.) targeting both `production` and `preview`; `/health` on Production independently
  confirms `"database":"connected"`.
- 14.3 Done, with one gap found. Listed (not read) every secret: `JWT_SECRET`, `APP_PASSWORD`, `CRON_SECRET` are set for
  both Production and Preview; `APP_USERNAME`, `GEMINI_CHAT_MODEL`, `GEMINI_EMBED_MODEL`, `EMBED_DIM` likewise. **Gap:**
  `GEMINI_API_KEY` is set for Production but, on Preview, only for the `sprint-2` git branch — a Preview deployment of
  any other branch would get a 503 from `/ask` ("No API key was provided"). Not fixed yet; low impact (Preview is used
  for the `sprint-2` branch in practice) but worth widening to all Preview branches.
- 14.4 Done. Full smoke test against `https://knowops-ai.vercel.app`, run live end-to-end (2026-11-08) using the local
  `.env` credentials, in order: login (200) → `/ask` "How do I perform a database failover?" (200, 15.1 s, 5 sources,
  cited Disaster Recovery Runbook › 4.2 Manual Failover Steps, new `conversation_id` 46) → `POST /tickets` (200, id 42)
  → `GET /tickets/42` (200, same subject, status `open`) → `GET /cron/reindex` with `CRON_SECRET` (200, correct no-op:
  "0 of 5 reindexed … 5 unchanged"). Test ticket 42 was then closed as cleanup. The 15.1 s `/ask` call is the known
  database-latency finding (Known issues), not a new defect. No code changed; this chunk is pure verification.
- 14.5 Done. Vaishnavi first checked the dashboard (2026-11-08, before the migration): `knowops-ai-` → Settings →
  **Cron Jobs** showed `/cron/reindex` as `Active` but **Invocations**/**P75 Duration** both `—` — that page
  (labeled `Legacy`) carries a banner saying it keeps no execution history at all. Vercel's Runtime Logs couldn't
  substitute either: Hobby retains only 1 hour, and the last scheduled firing (03:00 UTC) was ~7 hours before the
  query. So **no channel available at the time could prove a scheduled run had happened.** Migrated to Vercel
  Schedules instead (D-054, code change, approved and deployed as `af73634`, CI green on both branches, production
  deployment `READY`). Dashboard check after deploy showed `reindex` `Active`, source `Static` (reading from the
  deployed `vercel.json`), but 0 invocations — too soon for a natural firing. The assistant then set up the Vercel
  CLI (`npm install -g vercel`, `vercel login` done by Vaishnavi, `vercel link`) and used `vercel schedules ls` /
  `executions list` / `invoke` directly against the real project: `ls` independently confirmed the same config the
  dashboard showed (`state: "active"`, `requestMethod: "GET"`, cron `0 3 * * *`, no leftover `crons`);
  `executions list reindex` showed 0 recorded invocations; `vercel schedules invoke reindex` triggered one
  immediately rather than waiting for the next 03:00 UTC firing; `executions list reindex` 45s later showed
  `status: "succeeded"`, 1 recorded invocation, 0 failed, 0% error rate, ~9000 ms duration. This is a genuine
  completed run through Vercel's own scheduler, not another manual HTTP call like 14.4's.
- **Phase 14 done-when check:** "a stranger with only the production URL and a login can use the whole thing end to
  end" — holds end-to-end: login/ask/ticket-create/ticket-check/reindex all verified live (14.4), and the scheduled
  reindex is now provably working through a product that keeps execution history (14.5). Phase 14 is ✅.

**Phase 15 — Documentation & wrap-up** 🟡 in progress (15.1 done)
- 15.1 Done. `README.md` gained an **Architecture** section with a Mermaid flowchart (renders natively on GitHub,
  no image file to keep in sync): the single FastAPI Function, its three inbound triggers (browser, Vercel
  Schedules, scripted calls), the two outbound dependencies (Gemini, Neon), the best-effort n8n webhook, and the
  agent's 7 tools as a subgraph — plus a one-paragraph description of the `/ask` and agent request flows, linking
  to `FLOW.md` for the full call chains. Also added an **API reference** section: a link to the live `/docs`
  Swagger UI (satisfying the guide's "either an API reference or a link to `/docs`" directly) plus a condensed
  route table, with the full table (exact rate limits, decision references) linked to `AGENTS.md#api` rather than
  duplicated. The rest of 15.1's ask — setup steps, and a link to this status/decision trail — was already in
  place from earlier phases (Quick start, Project layout, Deployment, Monitoring, Understanding the code). No
  DECISION.md entry: Markdown-only change, and choosing Mermaid over a static image isn't a tradeoff worth logging.
- 15.3 Done. New `PORTFOLIO.md`: no separate "original skills list" exists for this project (confirmed with the
  user), so skills are derived directly from the stack and the recorded work in this file and `DECISION.md` —
  every bullet points at a specific file, test count, or live result already on record, not an invented claim.
  Split by owner per the Phase status table: Niranjan (Phases 2, 4–7 — DB/vector-search design, FastAPI, JWT auth,
  RAG retrieval, the ReAct agent loop and two real bugs found and fixed under live load) and Vaishnavi with Claude
  Code (Phases 3, 8–9, 11–13, 15 — content authoring, CRM, automation including the Phase 14.5 Schedules migration,
  the offline test infrastructure that took the suite from 2m19s with live calls to ~2s with none, observability
  that caught a real production outage, and the evaluation harness); Phase 10 (security) and 14 (deployment) kept
  general since they were split/shared. Linked from `README.md` under a new "Who built what" heading. No
  DECISION.md entry: Markdown-only change.
- 15.4 Done. New **Future work** section in `README.md`, split in two: items named directly in the build guide
  (real HubSpot CRM integration, multi-user auth, streaming responses, OAuth — each with one sentence on what it
  would actually take, not just the name) and items this build already found and recorded but didn't fix (database
  latency, the two still-simulated agent tools, the never-really-run n8n workflow, hallucination-flag/golden-set
  limits, login hardening, `/metrics` having no percentiles), each linking back to its full `AGENTS.md` Known
  issues entry rather than duplicating the detail. No new issue invented — every item already existed in Known
  issues or the build guide's own stretch list. No DECISION.md entry: Markdown-only change.

## Phase log

Append one line per finished phase (newest last).

| Date | Phase | By | Summary |
|---|---|---|---|
| 2026-10-15 | 1 | Both | Accounts, venv, local `.env` complete |
| 2026-10-15 | 2 | Niranjan | Schema live on Neon, round-trip verified, extra `tickets` columns |
| 2026-10-15 | 3 | Both | 5 runbooks, 500-char chunker, 78 chunks ingested idempotently |
| 2026-10-15 | 4 | Both | Skeleton done; deployed via Vercel project `knowops-ai-` |
| 2026-10-18 | 5 | Vaishnavi (with Claude) | 5.4 closed — every route but health/login now requires a JWT, verified locally (40/40 tests) and live on `sprint-2` |
| 2026-10-20 | 6 | Vaishnavi (with Claude) | `/ask` verified live: cited in-scope answer, out-of-scope refusal; fixed chunker dropping code-fenced commands (80 chunks) |
| 2026-10-25 | 7 | Vaishnavi (with Claude) | Added `create_ticket`/`escalate_to_human` tools; found and fixed 2 real agent-loop bugs (blank resolution on malformed Gemini reply, tool call silently skipped when bundled with is_final) and 1 prompt-priority gap (escalation vs. ticketing); all 7 tools verified live |
| 2026-10-25 | 8 | Vaishnavi (with Claude) | CRM verified end-to-end: create_ticket/get_ticket against raw Postgres, /tickets endpoints over HTTP, natural-language ticket creation through /agent/chat — no code changes needed, 8.4 skipped (optional) |
| 2026-10-27 | 9 | Vaishnavi (with Claude) | Fixed CRON_SECRET bypass (9.2) found live; added n8n escalation webhook + workflow.json (9.4/9.5); fast-forwarded main to Production for the first real deploy, filled 7 missing Vercel env vars across both environments; dashboard-confirmed cron run still pending |
| 2026-11-03 | 10 | Vaishnavi (with Claude) | Retry/backoff for Gemini+DB (10.1); fuzzed all routes — 6 HTTP 500s + a non-ASCII login crash found and fixed (10.2); prompt-injection guardrails after measuring a 1-in-3 hijack (10.3); secrets/history scan clean + hygiene tests (10.4); DB-backed per-user rate limits (10.5) |
| 2026-11-03 | 9 | Vaishnavi (with Claude) | Closed the last open item: scheduled `/cron/reindex` run confirmed in the Vercel Cron Jobs dashboard (per Vaishnavi); Phase 9 now ✅ |
| 2026-11-06 | 11 | Vaishnavi (with Claude) | Offline Gemini/Postgres fakes + network guard (11.1); `live` marker and auth/RAG-ranking/dispatch unit tests (11.2); mocked `/ask` round trip (11.3); edge cases + in-memory `MemoryDB` with a real-Postgres twin of every DB test (11.4); GitHub Actions on 3.11 + 3.12, green on first run (11.5) — suite went from 2m19s with live calls to ~2s with none |
| 2026-11-06 | 12 | Vaishnavi (with Claude) | Structured JSON logs with a request id on every line (12.1); an `agent_run` event with the bounded trace on any non-clean run (12.2); verified on Vercel's runtime logs (12.3) — which exposed a production outage (`google-genai` 3.0.0 → Gemini `v1` 404) fixed by pinning dependencies, plus a raw-JSON summary and a 97 s `/ask` hang fixed with a plain-text summary and a Gemini timeout + retry budget; Postgres-backed `GET /metrics` (12.4, stretch — deployed as `80d779d`; a known request mix was counted exactly on Production, and its first numbers showed database-backed routes taking 2–4 s) |
| 2026-11-07 | 13 | Vaishnavi (with Claude) | 19-question golden set checked against the runbooks (13.1); `python -m evals` runner with keyword scoring and an opt-in Gemini judge, accepted fact variants (13.2); per-question latency with a >5 s flag (13.3); likely-hallucination flags (13.4); JSON reports and `--repeat N` (13.5). Baseline of 3 live runs: 18/19, 19/19, 19/19 (the miss was a Gemini read timeout); every question is over 5 s — the database-latency finding, still unaddressed |
| 2026-11-08 | 14 | Vaishnavi (with Claude) | Verified 14.1–14.3 by reading the Vercel project config (found Preview's GEMINI_API_KEY is scoped to sprint-2 only); full live smoke test 14.4 (login → ask → create ticket → check ticket → reindex, all 200) against production; 14.5 found Legacy Cron Jobs keeps no execution history, migrated /cron/reindex to Vercel Schedules (D-054, deployed `af73634`), set up the Vercel CLI and used `vercel schedules invoke` to prove a real completed run (succeeded, 0% error rate, ~9s) — Phase 14 done |
| 2026-11-08 | 15 | Vaishnavi (with Claude) | 15.1: README gained an Architecture section (Mermaid diagram of the single-Function design, request flow for /ask and the agent) and an API reference section (link to /docs + a condensed route table) |
| 2026-11-08 | 15 | Vaishnavi (with Claude) | 15.3: new PORTFOLIO.md maps each person's work to concrete, resume-ready skills, derived from the recorded phase work rather than an external skills list (none exists) |
| 2026-11-08 | 15 | Vaishnavi (with Claude) | 15.4: new Future work section in README — build-guide stretch items (HubSpot, multi-user auth, streaming, OAuth) plus every unfixed gap already recorded in Known issues, nothing new invented |
| 2026-11-10 | — | Vaishnavi (with Claude) | Post-launch fix from an external bug report (D-055): `/cron/reindex` now refuses with 503 when deployed with no `CRON_SECRET` configured, instead of silently allowing anyone to trigger it; local dev with no secret unchanged |

## Deployment

- Vercel project **`knowops-ai-`** (Vaishnavi's account), Git-connected to `vaibhavii2810/KnowOps-AI-`;
  pushes deploy automatically. It is the only deployment — don't create another Vercel project.
- Vercel entrypoint: `api/index.py` (imports `app.main:app`) + `vercel.json` rewrites everything to it and
  bundles `static/` and `data/`. These exist on the `sprint-2` branch.
- Env vars live in that project's dashboard (Preview + Production), never in git. `.env` is gitignored.
- Hobby plan: Git deploys only build commits by the project owner's account.
- **Two Neon databases exist:** the Vercel app's `DATABASE_URL` points at a different Neon database from the one
  first used in a local `.env` (D-024). Re-ingest after any `data/docs/` or chunker change into **each** one you
  care about: `DATABASE_URL='<url>' python scripts/ingest.py --reset --quiet` (the env var overrides `.env`).
  A local `.env` pointing at the live database means `pytest -m live` writes test tickets into it (plain `pytest` no
  longer touches any database, D-040).
- `GEMINI_API_KEY` must exist in Vercel for **Preview** as well as Production (a missing key shows as a 503
  "No API key was provided" from `/ask`); variables only apply to new deployments.

## Branches

- `main` — **Production branch (2026-10-27).** Fast-forwarded to match `sprint-2`'s tip so the real app could
  go live; was the bare scaffold before that. Keep it fast-forwarded from `sprint-2` as work lands, or Vercel
  Production silently falls behind.
- `sprint-1-(base)` — Phases 1–4 code.
- `sprint-2` — Active branch; everything through Phase 12 lives here first, then gets fast-forwarded to `main`.
  Production was promoted to Phase 10 on 2026-11-03 (`2d0fe88`) and checked live: validation 422s, non-ASCII login
  401 (was a 500), rate-limit 429 + `Retry-After` on `/ask` and the agent endpoints, cron still protected.

## API

| Method | Path | Auth today | Purpose |
|---|---|---|---|
| GET | `/` | none | Web operations console (`static/`) |
| GET | `/health` | none (correct) | DB + KB health |
| GET | `/metrics` | required | Request count, average latency, error rate — last `hours` (1–168, default 24), per route (Phase 12.4, D-046) |
| POST | `/auth/login` | none (correct); 5/min + 30/hour per IP (429) | Returns JWT |
| GET | `/auth/me` | required | Current operator |
| POST | `/ask` | required, 10/min per user (429) | RAG answer with citations |
| POST/GET | `/conversations`, `/conversations/{id}` | required | Chat history |
| POST/GET/PATCH | `/tickets`, `/tickets/stats`, `/tickets/{id}` | required | Mock CRM |
| POST | `/agent/chat`, `/agent/triage/{ticket_id}` | required, 5/min per user, shared (429) | ReAct agent |
| GET | `/cron/reindex` | `CRON_SECRET` bearer | Re-index new/changed `data/docs/` files (Phase 9.1, D-029) |

Interactive docs: `/docs` (Swagger UI).

## Environment variables

`DATABASE_URL` (Neon pooled) · `GEMINI_API_KEY` · `GEMINI_CHAT_MODEL` · `GEMINI_EMBED_MODEL` · `EMBED_DIM` (768) ·
`JWT_SECRET` · `APP_USERNAME` / `APP_PASSWORD` · `CRON_SECRET` · `N8N_ESCALATION_WEBHOOK_URL` (optional — Phase
9.4, D-031; `escalate_to_human` skips the webhook call entirely when unset) · `RATE_LIMIT_ASK_PER_MINUTE` (10) /
`RATE_LIMIT_AGENT_PER_MINUTE` (5) (optional — Phase 10.5, D-036; 0 disables) · `RATE_LIMIT_LOGIN_PER_MINUTE` (5) /
`RATE_LIMIT_LOGIN_PER_HOUR` (30) (optional — D-037; per client IP) · `LOG_LEVEL` (INFO) (optional — Phase 12.1, D-042) · `GEMINI_TIMEOUT_SECONDS` (25) (optional — D-045; per Gemini request,
also each call's retry budget) · `METRICS_ENABLED` (true) (optional — Phase 12.4, D-046; false stops request counting).
`VERCEL` is platform-set by Vercel itself (never add it to `.env` or `.env.example`) — `GET /cron/reindex` uses it to tell a real
deployment apart from local dev when `CRON_SECRET` is missing (D-055).
Template: `.env.example`.
All are now set on both Preview and Production in the Vercel project (2026-10-27) — `main` was fast-forwarded
to `sprint-2`'s tip the same day, so Production is a real, working deployment for the first time.

## Repo layout

```
AGENTS.md   this file — status + rules      DECISION.md  why things are the way they are
FLOW.md     how execution moves through the code
CODE_TOUR.md  plain-English, phase-by-phase walkthrough of the code (for teammates new to it)
PORTFOLIO.md  what each person built, mapped to resume-ready skills (Phase 15.3)
app/        main.py (routes) · config.py · db.py · auth.py · rag.py · llm.py · agent.py · crm.py · schemas.py · retry.py · guardrails.py ·
            ratelimit.py · logs.py (JSON logs + request id, Phase 12.1) · metrics.py (GET /metrics counters, Phase 12.4)
api/        index.py — Vercel entrypoint (sprint-2)
scripts/    init_db.sql · ingest.py · generate_phase_*_pdf.py (report generators)
data/docs/  runbook knowledge base (markdown)
static/     web console (index.html, css, js)
n8n/        incident_triage_workflow.json (alert → ticket → triage → Slack) ·
            workflow.json (escalate_to_human → Slack, Phase 9.4/9.5, D-031)
tests/      pytest suite + eval_rag.py (conftest.py: offline fakes, MemoryDB; pytest.ini at repo root)
evals/      AI evaluation harness (Phase 13): golden_set.json + golden.py (D-047) · run.py, client.py, scoring.py, judge.py, hallucination.py, report.py — `python -m evals` (D-048–D-052) · reports/ (baseline-*.json committed, run-*.json ignored)
.github/    workflows/tests.yml — CI: plain pytest on every push/PR, Python 3.11 + 3.12 (Phase 11.5, D-041)
```

## Decisions

All decisions and their reasons are in [`DECISION.md`](DECISION.md). Key ones: DevOps/SRE runbooks instead of
EdTech (D-009), ~500-char chunks (D-010), deploy through the existing `knowops-ai-` project (D-018).

## Known issues

- **An external bug report (`KnowOps_AI_Bug_Report.pdf`, 2026-11-08, 27 findings) is not yet in this repo:** it
  references `tests/test_suspected_bugs.py` and `TEST_RESULTS.md`, neither of which exist here — that testing
  pass happened somewhere outside this repo's history. Bug #1 (High — `/cron/reindex` open when `CRON_SECRET` is
  unset) is fixed, D-055, 2026-11-10. The other 26 (including #21, High — stored-XSS in the console via
  `formatMarkdown`, and #2, High — the 0.55 retrieval threshold lets unrelated text through as cited context)
  are **not yet fixed or verified against this codebase** — only cross-checked that bug #1's claim matched the
  real code before fixing it. Worth pulling the PDF's test file and results doc into the repo so the rest aren't
  only tracked in a PDF.

- **Preview `GEMINI_API_KEY` is scoped to one branch (found in Phase 14.3, 2026-11-08):** the Vercel project has
  `GEMINI_API_KEY` for Production, and for Preview only on the `sprint-2` git branch. A Preview deployment of any
  other branch would get a 503 from `/ask` ("No API key was provided"). Low impact today (Preview is only used for
  `sprint-2`), but worth widening to all Preview branches before relying on Preview deploys of other branches.

- **Admin login hardening (password fixed 2026-11-03; residual risks):** Vercel's `APP_PASSWORD` was changed by hand to
  the strong one from the local `.env` and checked live: `admin`/`admin` → 401, the new password → 200 and its token works
  on `/auth/me`. (First attempt had a trailing newline from `pbcopy` — the site only accepted the password with `\n`
  appended; fix by copying with `... | cut -d= -f2- | tr -d '\n' | pbcopy`.) Still open: `APP_USERNAME` is `admin`
  (a free guess; optional to change). If an env var is ever missing, `app/config.py` silently falls back to
  `admin`/`admin` and `jwt_secret="dev-secret"` (D-007). The per-IP login limit (5/min, 30/hour, D-037) does not stop a
  distributed attack from many addresses, and trusts the client-IP headers only because Vercel sets them.
- **`get_conn()` latency — worse on Production than measured locally:** each call costs ~1.2s against the remote Neon DB
  locally, ~0.8s of it `register_vector`, which only `scripts/ingest.py` needs (found while measuring 10.5). `/ask` pays
  it 3×. `/metrics` on Production (2026-11-06) shows `/health` averaging 4.5 s (max 4.6 s), `/tickets/{id}` 4.3 s and
  `/tickets/stats` 2.5 s, against 1.9 ms for `/auth/me`, which makes no database call. A `vectors=False` default would
  cut the `register_vector` part (~0.8 s per call); the rest looks like function-to-database distance (the logs show the
  function running in `bom1`/`sfo1`/`iad1`, the database being in Singapore) — pinning the function's region next to
  Neon is worth testing. Not done. **The Phase 13.3 evaluation shows the cost from the user's side:** every golden question is
  over 5 s even in-process (median 5.6 s), and 14.2–14.4 s against the deployed site.
- **n8n triage workflow has no auth:** `n8n/incident_triage_workflow.json` calls `POST /tickets` and
  `/agent/triage/{id}` without an `Authorization` header, so since Phase 5.4 it would get 401s.
- **Phase 7.1 (partial, remainder of D-015):** `create_ticket`/`escalate_to_human` were added (D-025), but
  `run_system_diagnostics`/`execute_recovery_action` are still simulated for everything except the database
  diagnostic — no real infrastructure is inspected or changed.
- **`/ask` history:** loads the *first* 8 messages of a conversation, not the latest 8.
- **Request counting costs a Postgres write (~65 ms locally) per API request (Phase 12.4, D-046):** it runs after the
  response is produced; live client-side timings showed no measurable difference (see 12.4), but a caller may still wait
  for it on a serverless runtime. `/metrics` has no percentiles (only sums and a max are stored). `METRICS_ENABLED=false`
  turns counting off; if the cost ever shows, batch or sample the writes.
- **Tests can't see a changed SQL statement that keeps its matching text** (D-040): `MemoryDB` answers by fragment, so
  e.g. flipping the history query's `ORDER BY` goes unnoticed offline. The `live` variants (`pytest -m live`) catch it;
  run them before a deploy that touches SQL.
- **The hallucination flags are heuristics (Phase 13.4, D-051):** a number written as a range ("between 3 and 10 replicas") is flagged as `3 replicas` although right (seen live, 13.5 baseline); they miss a contradiction that changes no number or code and a citation of a
  document that does not exist (only `--judge` notices), and can flag a correct answer that reformats a command or derives a number.
  Read them as a list of answers worth a look.
- **Evaluation results vary run to run** (temperature 0.2): treat a single run as a sample. A run with `--judge` takes ~3 minutes
  on the free tier and can hit Gemini's quota (the runner waits and retries). Two runbook sections that cover the same incident
  (e.g. pool exhaustion in the playbooks and the on-call guide) can make the answer's facts differ between runs (`g12`, once).
- **Runbook text disagrees with the app in places (found reading them for 13.1):** `api_troubleshooting.md` §7 says `POST /ask` is
  limited to 20 requests/minute and `GET /health` to 100/minute, but the app enforces 10/minute on `/ask` (D-036) and does not
  limit `/health`; it and `on_call_guide.md` also say the Gemini retry is "up to 3 attempts" where the code makes 4 (D-032). `/ask`
  answers from these documents, so it repeats them. Not fixed; no golden question depends on these facts.
- **Phase 9.4:** `n8n/workflow.json`'s Slack URL is a placeholder (`.../mock/webhook/...`); the backend→webhook
  mechanism is verified (D-031) but nobody has actually run `npx n8n` and imported the workflow for real yet.

## Working here

- `python -m venv .venv` → `pip install -r requirements.txt` → `uvicorn app.main:app --reload`
- Tests: `pytest` (offline, ~2s; tests marked `live` are skipped). `pytest -m live` runs the ones that need the real
  Neon DB and Gemini, including the real-Postgres variant of every `db_backend` test (D-039, D-040). New tests should use
  `fake_gemini`, `fake_db` or `memory_db` (D-038, D-040); a test needing a new SQL statement must add it to `MemoryDB`.
- Evaluation: `python -m evals` (in-process, real Gemini, ~1–3 min; `--judge`, `--only g01,g05`, `--slow-seconds 3`, `--repeat 3`, `--report PATH` / `--no-report`, `--url https://… ` for a
  deployed site). It calls real services and writes conversations into the database in `.env`, so it is not part of `pytest` (D-048).
- Never commit `.env` or real keys.
- Vercel CLI (Phase 14.5, D-054): `npm install -g vercel` installs it to `~/.local/node/bin` in this environment,
  which isn't on `PATH` by default — prefix commands with
  `export PATH="/Users/vaishnavigaikwad/.local/node/bin:$PATH"`. `vercel login` is interactive (email/browser); a
  human has to do it. Once logged in, `vercel link` attaches the repo (project `knowops-ai-`, team `vaii2`) and
  creates a git-ignored `.env.local` with a short-lived `VERCEL_OIDC_TOKEN`. Useful once linked:
  `vercel schedules ls`, `vercel schedules executions list <name>`, `vercel schedules invoke <name>` (triggers a
  real run immediately instead of waiting for the cron time — used to confirm 14.5 live).

## Rules for every code change

A **code change** is any edit under `app/`, `api/`, `scripts/`, `static/`, `tests/`, or to `vercel.json`,
`requirements.txt`, `.env.example` or `scripts/init_db.sql`. Changes to Markdown docs only are exempt.

### 1. Log decisions in `DECISION.md`

Add an entry (template at the top of the file) whenever the change:
- adds, removes or swaps a library or service — say **why this one** and what else was considered;
- picks one design over another, or accepts a known limitation — say **why the tradeoff is acceptable**;
- changes the DB schema, an API route or contract, auth, config or deployment;
- deviates from the build guide.

Not needed for renames, formatting, or obvious bug fixes. If a later change reverses a decision, add a new
entry and mark the old one `Superseded by D-NNN` — never delete history.

### 2. Keep `FLOW.md` true

In the same change, update `FLOW.md` when you add, remove or rename an entry point, route, module or function
in a documented chain, or change which function calls which, the order of steps, or which tables a code path touches.

### 3. Quiz before acceptance

Before a code change counts as accepted, the agent quizzes the human who asked for it:

1. Finish the change, then say: *"Change ready — quiz before acceptance."* Don't give the answers away in the summary.
2. Ask **3 questions, one at a time**, about *this* change, mixing multiple-choice and short-answer:
   - **What** — what changed, and in which file / function?
   - **Why** — why this approach over the alternative (link to the `DECISION.md` entry when there is one)?
   - **Flow / impact** — how execution moves through the changed code, or what would break if X happened?
3. **Pass = all 3 correct.** A wrong or half-right answer gets a short explanation, then a new question on the
   same idea, until it's answered correctly.
4. **Until the quiz is passed, the change is pending:** don't mark a chunk or phase done, don't run
   `/phase-done`, don't commit or push, and don't start the next task. If the human wants to drop the change,
   offer to revert it.
5. On a pass, say *"Quiz passed — change accepted."* and continue.

An agent can't disable its editor's own "accept" button; this gate controls what happens after the edit.

## Phase completion protocol

Run this whenever a build-guide chunk or phase is finished (or when someone types `/phase-done <phase>`):

1. **Verify first.** Check the phase's "Done when" criterion from the build guide. Only mark ✅ if it holds;
   otherwise mark 🟡 and say what's missing.
2. **Quiz check** — every code change in the phase must have passed its quiz. If any didn't, run it now.
3. **Phase status table** — update the row's status (and owner if it changed).
4. **Completed phase details** — add a short block for the phase listing each chunk and the files involved.
5. **Phase log** — append `| YYYY-MM-DD | <phase> | <who> | <one-line summary> |`.
6. **`DECISION.md` and `FLOW.md`** — make sure every decision and flow change from the phase is recorded.
7. **Keep the rest true** — update API, Environment variables, Repo layout, Deployment and Known issues if the
   work changed them; delete issues that are fixed.
8. **README.md** — update the `Progress:` line.
9. **Report** — tell the user what changed. Don't commit or push unless they ask.
