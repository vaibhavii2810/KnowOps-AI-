CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    content_hash TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Idempotent migration for databases created before content_hash existed (Phase 9.1, D-029).
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    heading TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    embedding vector(768) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks
    USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS tickets (
    id SERIAL PRIMARY KEY,
    subject TEXT NOT NULL,
    description TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'P2',
    status TEXT NOT NULL DEFAULT 'open',
    resolution_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Hourly request counters for GET /metrics (Phase 12.4, D-046). app/metrics.py also creates this on first use.
CREATE TABLE IF NOT EXISTS request_metrics (
    hour_start     BIGINT           NOT NULL,
    method         TEXT             NOT NULL,
    route          TEXT             NOT NULL,
    requests       INTEGER          NOT NULL DEFAULT 0,
    server_errors  INTEGER          NOT NULL DEFAULT 0,
    client_errors  INTEGER          NOT NULL DEFAULT 0,
    latency_ms_sum DOUBLE PRECISION NOT NULL DEFAULT 0,
    latency_ms_max DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (hour_start, method, route)
);

-- Per-user rate-limit counters (Phase 10.5, D-036). app/ratelimit.py also creates this on first use.
CREATE TABLE IF NOT EXISTS rate_limits (
    user_key     TEXT    NOT NULL,
    bucket       TEXT    NOT NULL,
    window_start BIGINT  NOT NULL,
    hits         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_key, bucket, window_start)
);
