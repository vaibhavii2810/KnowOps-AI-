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
| 6 | RAG retrieval + `/ask` | Niranjan | 🟡 Code exists, 6.4/6.5 not verified |
| 7 | Agent + tool-calling | Niranjan | 🟡 Code exists, not verified |
| 8 | Mock CRM / tickets | Vaishnavi | 🟡 Code exists, not verified |
| 9 | Automation (cron + n8n) | Vaishnavi | 🟡 Partial — see Known issues |
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

## Phase log

Append one line per finished phase (newest last).

| Date | Phase | By | Summary |
|---|---|---|---|
| 2026-10-15 | 1 | Both | Accounts, venv, local `.env` complete |
| 2026-10-15 | 2 | Niranjan | Schema live on Neon, round-trip verified, extra `tickets` columns |
| 2026-10-15 | 3 | Both | 5 runbooks, 500-char chunker, 78 chunks ingested idempotently |
| 2026-10-15 | 4 | Both | Skeleton done; deployed via Vercel project `knowops-ai-` |
| 2026-10-18 | 5 | Vaishnavi (with Claude) | 5.4 closed — every route but health/login now requires a JWT, verified locally (40/40 tests) and live on `sprint-2` |

## Deployment

- Vercel project **`knowops-ai-`** (Vaishnavi's account), Git-connected to `vaibhavii2810/KnowOps-AI-`;
  pushes deploy automatically. It is the only deployment — don't create another Vercel project.
- Vercel entrypoint: `api/index.py` (imports `app.main:app`) + `vercel.json` rewrites everything to it and
  bundles `static/` and `data/`. These exist on the `sprint-2` branch.
- Env vars live in that project's dashboard (Preview + Production), never in git. `.env` is gitignored.
- Hobby plan: Git deploys only build commits by the project owner's account.

## Branches

- `main` — scaffold removed; no app code yet.
- `sprint-1-(base)` — Phases 1–4 code.
- `sprint-2` — same plus the Vercel entrypoint (`api/index.py`, `vercel.json` rewrites). Active branch.

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
| POST | `/cron/reindex` | `CRON_SECRET` bearer | Re-index trigger |

Interactive docs: `/docs` (Swagger UI).

## Environment variables

`DATABASE_URL` (Neon pooled) · `GEMINI_API_KEY` · `GEMINI_CHAT_MODEL` · `GEMINI_EMBED_MODEL` · `EMBED_DIM` (768) ·
`JWT_SECRET` · `APP_USERNAME` / `APP_PASSWORD` · `CRON_SECRET`. Template: `.env.example`.

## Repo layout

```
AGENTS.md   this file — status + rules      DECISION.md  why things are the way they are
FLOW.md     how execution moves through the code
app/        main.py (routes) · config.py · db.py · auth.py · rag.py · llm.py · agent.py · crm.py · schemas.py
api/        index.py — Vercel entrypoint (sprint-2)
scripts/    init_db.sql · ingest.py · generate_phase_*_pdf.py (report generators)
data/docs/  runbook knowledge base (markdown)
static/     web console (index.html, css, js)
n8n/        incident_triage_workflow.json
tests/      pytest suite + eval_rag.py
```

## Decisions

All decisions and their reasons are in [`DECISION.md`](DECISION.md). Key ones: DevOps/SRE runbooks instead of
EdTech (D-009), ~500-char chunks (D-010), deploy through the existing `knowops-ai-` project (D-018).

## Known issues

- **Phase 10 (config):** if an env var is missing, `app/config.py` silently falls back to `admin`/`admin` and
  `jwt_secret="dev-secret"` (D-007).
- **Phase 7.1:** agent tools differ from the guide — no `create_ticket` or `escalate_to_human` tool; diagnostics
  and recovery actions are simulated (D-015).
- **`/ask` history:** loads the *first* 8 messages of a conversation, not the latest 8.
- **Phase 9.1:** `/cron/reindex` only counts rows — it doesn't re-run ingestion.
- **Phase 9.3:** `vercel.json` cron calls `/cron/reindex`, but the route is `POST`; Vercel Cron sends `GET`,
  so scheduled runs will get 405. The guide specifies `GET /cron/reindex`.

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
