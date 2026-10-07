from contextlib import contextmanager
import psycopg
from pgvector.psycopg import register_vector
from app.config import settings

@contextmanager
def get_conn():
    conn = psycopg.connect(settings.database_url, autocommit=True)
    try:
        register_vector(conn)
        yield conn
    finally:
        conn.close()
