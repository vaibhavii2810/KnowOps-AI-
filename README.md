# AI Support & Knowledge Ops Platform

Free-tier stack: FastAPI on Vercel (Hobby), Neon Postgres + pgvector,
Google Gemini API (free tier), JWT auth, mocked CRM, Vercel Cron + local n8n.

Setup:
1. `python -m venv .venv` and activate it
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in real values
4. Run `scripts/init_db.sql` against your Neon database (SQL editor or psql)
5. `uvicorn app.main:app --reload` to run locally, then check `/health`

Full phase-by-phase build plan lives in our shared build guide doc
(ask [your teammate] for the link if you don't have it).
