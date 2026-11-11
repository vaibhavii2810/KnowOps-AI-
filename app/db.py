from contextlib import contextmanager
import psycopg
from pgvector.psycopg import register_vector
from app.config import settings
from app.retry import DEFAULT_ATTEMPTS, is_transient_db_error, retry_call

@contextmanager
def get_conn(retry: bool = True, vectors: bool = False):
    # Retry only the connect step (Phase 10.1, D-032): a Neon cold start or brief network blip
    # shows up here, and nothing has been executed yet so a retry can't duplicate a write.
    # Individual statements are deliberately not retried — an INSERT whose response was lost
    # may already have committed (autocommit), and re-running it would create a duplicate.
    # Health probes pass retry=False: their job is to report an outage, so they must fail fast
    # (a /health that takes ~7s to say "degraded" looks like a timeout to a monitor).
    #
    # vectors=True registers pgvector's Python-list <-> `vector` column adapter (D-080, bug #25):
    # measured at ~0.8s of get_conn()'s ~1.2s total. No code path in this app ever SELECTs a raw
    # `embedding` column (always inside a `<=>` distance expression), so reads never need it. The one
    # write path — scripts/ingest.py's insert_chunk(), binding a raw Python list as `embedding` — keeps
    # vectors=True: without the registered adapter, psycopg still happens to send a plain list in a text
    # form pgvector's input parser accepts (confirmed directly), but that's an unspecified fallback to
    # depend on for a write, not a documented guarantee — the explicit adapter is used there on purpose.
    # rag.py's retrieve() never needed this at all: it formats the query vector as a text literal and
    # casts it server-side with `::vector`. Defaulting this to False cuts ~0.8s from every other call,
    # including the 3 `/ask` makes per request.
    conn = retry_call(
        lambda: psycopg.connect(settings.database_url, autocommit=True),
        is_transient=is_transient_db_error,
        label="postgres connect",
        attempts=DEFAULT_ATTEMPTS if retry else 1,
    )
    try:
        if vectors:
            register_vector(conn)
        yield conn
    finally:
        conn.close()
