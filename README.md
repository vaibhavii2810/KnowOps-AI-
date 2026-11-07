# AI Support & Knowledge Ops Platform (KnowOps AI)

[![tests](https://github.com/vaibhavii2810/KnowOps-AI-/actions/workflows/tests.yml/badge.svg)](https://github.com/vaibhavii2810/KnowOps-AI-/actions/workflows/tests.yml)

An AI-powered technical support backend for DevOps/SRE teams. It answers support questions from a
runbook knowledge base with citations (RAG), and runs an agent that can search the knowledge base,
create, check and triage incident tickets, and escalate to a human.

**Progress:** Phases 1–12 of 15 complete. Live status of every phase: [AGENTS.md](AGENTS.md#phase-status). New to the code? Start with [CODE_TOUR.md](CODE_TOUR.md).

## Stack (free tier)

| Layer | Choice |
|---|---|
| Hosting | Vercel (Hobby) |
| Backend | Python + FastAPI |
| Database | Neon Postgres + pgvector |
| LLM + embeddings | Google Gemini (`gemini-embedding-001`, 768 dims) |
| Auth | Self-rolled JWT |
| CRM | Mocked in Postgres |
| Automation | Vercel Cron + local n8n |
| Testing | pytest (offline fakes, no real API calls) + GitHub Actions on every push |
| Monitoring | Structured JSON logs (Vercel Runtime Logs) + `GET /metrics` |

## Quick start

1. `python -m venv .venv` and activate it
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in real values (never commit `.env`)
4. Run `scripts/init_db.sql` against your Neon database (SQL editor or psql)
5. `python scripts/ingest.py` to load `data/docs/` into the knowledge base
6. `uvicorn app.main:app --reload`, then open `/health`, `/docs` (Swagger) or `/` (web console)

Tests: `pytest` (skips tests marked `live`) · `pytest -m live` (tests that need the real database and Gemini)

Evaluation: `python -m evals` runs 19 golden questions through the real `/ask` and prints accuracy (add `--judge` for a Gemini
second opinion, `--url https://…` to test a deployed site). Each question's time is shown and anything over 5 s is flagged `SLOW`; answers that look unsupported by the retrieved runbook text are flagged too. It uses real services, so it is separate from `pytest`.

## Project layout

```
app/        FastAPI app: routes, config, DB, auth, RAG, LLM, agent, CRM, retry, guardrails, rate limits, logs, metrics
api/        Vercel entrypoint (sprint-2 branch)
scripts/    DB schema, ingestion
data/docs/  runbook knowledge base
static/     web console
n8n/        n8n workflow export
tests/      pytest suite (offline fakes in conftest.py) + RAG eval
evals/      AI evaluation harness: golden question set and the `python -m evals` runner (Phase 13)
.github/    CI workflow: runs pytest on every push
```

## Deployment

Deployed on Vercel through the project `knowops-ai-`, which is Git-connected to this repo, so pushes
deploy automatically. Environment variables are set in the Vercel dashboard. Details in
[AGENTS.md](AGENTS.md#deployment).

## Monitoring

Every request writes one JSON log line (request id, user, latency, status, tools the agent used) that shows up in
Vercel's Runtime Logs; the id also comes back in an `X-Request-ID` header. `GET /metrics` (login required) reports
request count, average latency and error rate for the last 1–168 hours, per route. Details in [AGENTS.md](AGENTS.md)
(Phase 12) and [DECISION.md](DECISION.md) (D-042, D-043, D-046).

## Understanding the code

- [FLOW.md](FLOW.md) — entry points, startup order, and which function calls which for every route
- [DECISION.md](DECISION.md) — every meaningful decision and the reason behind it (why this library, why this tradeoff)

## Team workflow

The build follows a shared 15-phase build guide (ask a teammate for the link). The rules for AI agents live in
[AGENTS.md](AGENTS.md):

- Agents log decisions in `DECISION.md` and keep `FLOW.md` up to date with every code change.
- Before a code change is accepted, the agent **quizzes you with 3 questions about it**. You have to get all 3
  right for the change to count as accepted.
- After finishing a phase, run **`/phase-done <phase>`** in Antigravity or Claude Code. It updates the status
  table, phase log and known issues in `AGENTS.md` and the progress line above, so everyone sees the same
  status after a pull.
