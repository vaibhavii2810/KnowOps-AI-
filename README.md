# AI Support & Knowledge Ops Platform (KnowOps AI)

An AI-powered technical support backend for DevOps/SRE teams. It answers support questions from a
runbook knowledge base with citations (RAG), and runs an agent that can search the knowledge base,
create, check and triage incident tickets, and escalate to a human.

**Progress:** Phases 1–8 of 15 complete. Live status of every phase: [AGENTS.md](AGENTS.md#phase-status). New to the code? Start with [CODE_TOUR.md](CODE_TOUR.md).

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

## Quick start

1. `python -m venv .venv` and activate it
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in real values (never commit `.env`)
4. Run `scripts/init_db.sql` against your Neon database (SQL editor or psql)
5. `python scripts/ingest.py` to load `data/docs/` into the knowledge base
6. `uvicorn app.main:app --reload`, then open `/health`, `/docs` (Swagger) or `/` (web console)

Tests: `pytest`

## Project layout

```
app/        FastAPI app: routes, config, DB, auth, RAG, LLM, agent, CRM
api/        Vercel entrypoint (sprint-2 branch)
scripts/    DB schema, ingestion
data/docs/  runbook knowledge base
static/     web console
n8n/        n8n workflow export
tests/      pytest suite + RAG eval
```

## Deployment

Deployed on Vercel through the project `knowops-ai-`, which is Git-connected to this repo, so pushes
deploy automatically. Environment variables are set in the Vercel dashboard. Details in
[AGENTS.md](AGENTS.md#deployment).

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
