from contextlib import contextmanager
import psycopg
from pgvector.psycopg import register_vector
from app.config import settings
from app.retry import DEFAULT_ATTEMPTS, is_transient_db_error, retry_call

@contextmanager
def get_conn(retry: bool = True):
    # Retry only the connect step (Phase 10.1, D-032): a Neon cold start or brief network blip
    # shows up here, and nothing has been executed yet so a retry can't duplicate a write.
    # Individual statements are deliberately not retried — an INSERT whose response was lost
    # may already have committed (autocommit), and re-running it would create a duplicate.
    # Health probes pass retry=False: their job is to report an outage, so they must fail fast
    # (a /health that takes ~7s to say "degraded" looks like a timeout to a monitor).
    conn = retry_call(
        lambda: psycopg.connect(settings.database_url, autocommit=True),
        is_transient=is_transient_db_error,
        label="postgres connect",
        attempts=DEFAULT_ATTEMPTS if retry else 1,
    )
    try:
        register_vector(conn)
        yield conn
    finally:
        conn.close()
