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
| 9 | Automation (cron + n8n) | Vaishnavi | 🟡 Partial — all 5 chunks code-complete & live; only the dashboard-confirmed cron run (part of the guide's "Done when") is outstanding |
| 10 | Error handling & security | Split 50/50 | ⬜ Not started |
| 11 | Testing & QA | Vaishnavi | 🟡 Partial — tests exist, no CI (11.5) |
| 12 | Logging & monitoring | Vaishnavi | ⬜ Not started |
| 13 | AI eval harness | Vaishnavi | 🟡 Partial — `tests/eval_rag.py` exists |
| 14 | Deployment & final integration | Both | ⬜ Not started |
| 15 | Docs & wrap-up | Vaishnavi | ⬜ Not started |

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

**Phase 9 — Automation (cron + n8n)** 🟡 code-complete, one item outstanding
- 9.1 `GET /cron/reindex` (was `POST`, counted rows only) now actually re-ingests new/changed `data/docs/`
  files via `scripts.ingest.reindex_knowledge_base()`, skipping unchanged ones by content hash (D-029).
  Verified live on both Preview and Production: editing one runbook re-embedded only that file; a no-op run
  took 2.3s with zero Gemini calls.
- 9.2 `CRON_SECRET` is now enforced in every environment, not just production (D-030) — found and fixed a
  real gap: an unauthenticated call against the live Preview deployment succeeded and triggered a real
  re-embed before the fix.
- 9.3 `vercel.json`'s daily cron (`0 3 * * *` → `/cron/reindex`) is syntactically correct and, as of
  2026-10-27, actually deployed to Production for the first time (`main` was fast-forwarded to `sprint-2`).
  Manually confirmed the endpoint behaves exactly as Vercel Cron's own invocation would (`GET`, `Authorization:
  Bearer $CRON_SECRET` — Vercel auto-attaches this header for a project env var literally named
  `CRON_SECRET`, confirmed via Vercel's own docs). **Not yet confirmed:** an actual automatic run in Vercel's
  Cron dashboard — Production only went live today, so the next scheduled 03:00 UTC fire hasn't happened yet.
  Check `vercel.com/vaii2/knowops-ai-` → Cron Jobs tab tomorrow, or run `vercel crons run /cron/reindex` from
  the CLI to trigger it immediately.
- 9.4 Added `n8n/workflow.json` (new, separate from the existing `incident_triage_workflow.json`): a webhook
  node at `escalate-to-human` → an HTTP Request node posting to Slack. `tool_escalate_to_human` in
  `app/agent.py` now POSTs to `N8N_ESCALATION_WEBHOOK_URL` when configured (best-effort — n8n being down
  never breaks the escalation tool itself) (D-031). Verified end-to-end against a real local HTTP listener
  (not n8n itself, which wasn't actually run) — the payload shape matches what the workflow's Slack template
  expects.
- 9.5 `n8n/workflow.json` is exported and in the repo, satisfying that half of the guide's done-when directly.
- 7 new tests (3 for the webhook behavior, matching the pattern already used for 9.1/9.2's live-bug fixes).

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
  A local `.env` pointing at the live database means `pytest` writes test tickets into it.
- `GEMINI_API_KEY` must exist in Vercel for **Preview** as well as Production (a missing key shows as a 503
  "No API key was provided" from `/ask`); variables only apply to new deployments.

## Branches

- `main` — **Production branch (2026-10-27).** Fast-forwarded to match `sprint-2`'s tip so the real app could
  go live; was the bare scaffold before that. Keep it fast-forwarded from `sprint-2` as work lands, or Vercel
  Production silently falls behind.
- `sprint-1-(base)` — Phases 1–4 code.
- `sprint-2` — Active branch; everything through Phase 9 lives here first, then gets pushed to `main`.

## API

| Method | Path | Auth today | Purpose |
|---|---|---|---|
| GET | `/` | none | Web operations console (`static/`) |
| GET | `/health` | none (correct) | DB + KB health |
| POST | `/auth/login` | none (correct) | Returns JWT |
| GET | `/auth/me` | required | Current operator |
| POST | `/ask` | required | RAG answer with citations |
| POST/GET | `/conversations`, `/conversations/{id}` | required | Chat history |
| POST/GET/PATCH | `/tickets`, `/tickets/stats`, `/tickets/{id}` | required | Mock CRM |
| POST | `/agent/chat`, `/agent/triage/{ticket_id}` | required | ReAct agent |
| GET | `/cron/reindex` | `CRON_SECRET` bearer | Re-index new/changed `data/docs/` files (Phase 9.1, D-029) |

Interactive docs: `/docs` (Swagger UI).

## Environment variables

`DATABASE_URL` (Neon pooled) · `GEMINI_API_KEY` · `GEMINI_CHAT_MODEL` · `GEMINI_EMBED_MODEL` · `EMBED_DIM` (768) ·
`JWT_SECRET` · `APP_USERNAME` / `APP_PASSWORD` · `CRON_SECRET` · `N8N_ESCALATION_WEBHOOK_URL` (optional — Phase
9.4, D-031; `escalate_to_human` skips the webhook call entirely when unset). Template: `.env.example`.
All are now set on both Preview and Production in the Vercel project (2026-10-27) — `main` was fast-forwarded
to `sprint-2`'s tip the same day, so Production is a real, working deployment for the first time.

## Repo layout

```
AGENTS.md   this file — status + rules      DECISION.md  why things are the way they are
FLOW.md     how execution moves through the code
CODE_TOUR.md  plain-English, phase-by-phase walkthrough of the code (for teammates new to it)
app/        main.py (routes) · config.py · db.py · auth.py · rag.py · llm.py · agent.py · crm.py · schemas.py
api/        index.py — Vercel entrypoint (sprint-2)
scripts/    init_db.sql · ingest.py · generate_phase_*_pdf.py (report generators)
data/docs/  runbook knowledge base (markdown)
static/     web console (index.html, css, js)
n8n/        incident_triage_workflow.json (alert → ticket → triage → Slack) ·
            workflow.json (escalate_to_human → Slack, Phase 9.4/9.5, D-031)
tests/      pytest suite + eval_rag.py
```

## Decisions

All decisions and their reasons are in [`DECISION.md`](DECISION.md). Key ones: DevOps/SRE runbooks instead of
EdTech (D-009), ~500-char chunks (D-010), deploy through the existing `knowops-ai-` project (D-018).

## Known issues

- **Phase 10 (config):** if an env var is missing, `app/config.py` silently falls back to `admin`/`admin` and
  `jwt_secret="dev-secret"` (D-007).
- **Phase 7.1 (partial, remainder of D-015):** `create_ticket`/`escalate_to_human` were added (D-025), but
  `run_system_diagnostics`/`execute_recovery_action` are still simulated for everything except the database
  diagnostic — no real infrastructure is inspected or changed.
- **`/ask` history:** loads the *first* 8 messages of a conversation, not the latest 8.
- **Phase 9.3:** the Vercel Cron Jobs dashboard hasn't yet shown an automatic scheduled run of
  `GET /cron/reindex` — Production only went live 2026-10-27, so the next 03:00 UTC fire hasn't happened yet.
  Check the dashboard tomorrow, or run `vercel crons run /cron/reindex` to trigger it immediately.
- **Phase 9.4:** `n8n/workflow.json`'s Slack URL is a placeholder (`.../mock/webhook/...`); the backend→webhook
  mechanism is verified (D-031) but nobody has actually run `npx n8n` and imported the workflow for real yet.

## Working here

- `python -m venv .venv` → `pip install -r requirements.txt` → `uvicorn app.main:app --reload`
- Tests: `pytest`
- Never commit `.env` or real keys.

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
