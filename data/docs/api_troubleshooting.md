# API Troubleshooting Guide

**Document ID:** API-001  
**Title:** API Troubleshooting Guide — KnowOps AI REST API  
**Category:** Application / Backend  
**Owner:** Backend Engineering  
**Last Updated:** 2026-03-20  

---

## 1. Overview

This guide helps engineers and support staff diagnose and resolve common issues with the KnowOps AI REST API. The API is built using **FastAPI** and served behind an NGINX ingress on Kubernetes. It connects to Neon PostgreSQL (pgvector) and Google Gemini AI.

Base URL (Production): `https://api.knowops.ai/v1`

---

## 2. Common HTTP Error Codes

| Status Code | Meaning | Most Common Cause |
|---|---|---|
| 400 Bad Request | Invalid request body or parameters | Missing required field, wrong data type |
| 401 Unauthorized | Missing or invalid JWT token | Token expired, wrong credentials |
| 403 Forbidden | Valid token but insufficient permissions | User lacks required role |
| 404 Not Found | Endpoint or resource doesn't exist | Wrong URL path |
| 422 Unprocessable Entity | FastAPI validation error | Schema mismatch in request body |
| 429 Too Many Requests | Rate limit exceeded | Client making too many requests |
| 500 Internal Server Error | Unhandled exception in backend | Check application logs |
| 503 Service Unavailable | Upstream dependency down | Database or Gemini API unreachable |

---

## 3. Authentication Issues

### 3.1 `401 Unauthorized` — "Could not validate credentials"

**Cause:** JWT token is missing, expired, or malformed.

**Resolution:**
```bash
# Get a fresh token
curl -X POST https://api.knowops.ai/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your-password"}'

# Use the token in requests
curl -X GET https://api.knowops.ai/v1/health \
  -H "Authorization: Bearer <your-token>"
```

**Check token expiry:**
- Tokens expire after 60 minutes by default (configurable via `JWT_EXPIRE_MINUTES`)
- If seeing frequent expiry issues, check if the system clock is out of sync between client and server

### 3.2 Token Not Accepted After Password Reset

The JWT secret may have been rotated. All existing tokens are immediately invalid after a `JWT_SECRET` rotation. Users must log in again to obtain new tokens.

---

## 4. API Endpoint Errors

### 4.1 `POST /ask` — 500 Internal Server Error

**Most common causes:**

1. **Gemini API Unavailable (503):**
   ```bash
   # Check Gemini API status
   curl https://status.cloud.google.com/incidents.json | python3 -m json.tool | grep -i gemini
   ```
   The API has built-in retry logic (3 attempts with exponential backoff). If persisting, check application logs.

2. **Database Connection Failure:**
   ```bash
   # Test DB connectivity directly
   psql $DATABASE_URL -c "SELECT 1;"
   ```

3. **Empty Embedding Returned:**
   - Caused by passing an empty string to `embed_query()`
   - The `/ask` endpoint validates that the question is not empty (400 response)

4. **No Chunks Found (no RAG context):**
   - Happens when the knowledge base is empty (no documents ingested)
   - Run `python scripts/ingest.py` to populate the knowledge base
   - Returns: "I don't have enough information in the knowledge base to answer that."

### 4.2 `POST /ask` — 422 Unprocessable Entity

Ensure the request body matches the expected schema:
```json
{
  "question": "How do I perform a database failover?",
  "conversation_id": null
}
```

`question` is required and must be a non-empty string.

### 4.3 `GET /health` — 503

The health check endpoint tests DB connectivity. If it returns 503:
```bash
# Check if the database URL is set correctly
kubectl get secret knowops-secrets -n production -o jsonpath='{.data.DATABASE_URL}' | base64 -d

# Verify the pod can reach Neon
kubectl exec -it <api-pod> -n production -- python3 -c "
import psycopg, os
conn = psycopg.connect(os.environ['DATABASE_URL'])
print('DB OK:', conn.execute('SELECT version()').fetchone())
"
```

---

## 5. Performance Issues

### 5.1 Slow `/ask` Response Times

Expected response times:
- Embedding generation: 200–500ms
- Vector search: 10–50ms  
- Gemini chat completion: 500ms–3s
- **Total P95 target:** < 4 seconds

If responses are slower:

1. **Check vector search is using the HNSW index:**
```sql
EXPLAIN ANALYZE
SELECT content, 1 - (embedding <=> '[...]'::vector) AS similarity
FROM chunks
ORDER BY embedding <=> '[...]'::vector
LIMIT 5;
-- Must show: "Index Scan using chunks_embedding_idx"
-- If "Seq Scan" appears, the index may be missing
```

2. **Rebuild the HNSW index if missing:**
```sql
CREATE INDEX IF NOT EXISTS chunks_embedding_idx 
ON chunks USING hnsw (embedding vector_cosine_ops);
```

3. **Check Gemini API latency in Datadog** APM under the `llm.chat_completion` span.

### 5.2 High Memory Usage in API Pods

The embedding model responses are large. If memory is spiking:
- Ensure embedding results are not cached in memory (they are stored in DB)
- Check for memory leaks: `kubectl top pods -n production`
- If >900Mi, trigger a rolling restart: `kubectl rollout restart deployment/knowops-api -n production`

---

## 6. Logging & Tracing

### 6.1 Application Logs

```bash
# Tail live application logs
kubectl logs -f deployment/knowops-api -n production

# Search for specific errors
kubectl logs deployment/knowops-api -n production | grep "ERROR"

# View logs from crashed previous pod
kubectl logs <pod-name> -n production --previous
```

### 6.2 Structured Log Format

All application logs are JSON-structured:
```json
{
  "timestamp": "2026-03-20T10:23:45.123Z",
  "level": "ERROR",
  "service": "knowops-api",
  "trace_id": "abc123",
  "message": "Gemini API 503 - attempt 1 of 3",
  "duration_ms": 1234
}
```

Filter by trace ID in Datadog to follow a single request across all services.

---

## 7. Rate Limiting

The API enforces rate limits per authenticated user:

| Endpoint | Rate Limit | Window |
|---|---|---|
| `POST /ask` | 20 requests | per minute |
| `POST /auth/login` | 5 requests | per minute |
| `GET /health` | 100 requests | per minute |

If a client hits the rate limit, they receive a `429` response with:
```json
{
  "error": "rate_limit_exceeded",
  "retry_after_seconds": 45
}
```

Clients should implement exponential backoff when receiving 429 responses.

---

## 8. Database Query Debugging

```sql
-- Check slow queries (pg_stat_statements required)
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;

-- Check table sizes
SELECT schemaname, tablename, 
       pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as total_size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Check number of indexed chunks
SELECT COUNT(*) as total_chunks, 
       COUNT(DISTINCT document_id) as total_documents
FROM chunks;

-- Check last ingestion time
SELECT d.title, d.source, d.created_at, COUNT(c.id) as chunk_count
FROM documents d
LEFT JOIN chunks c ON c.document_id = d.id
GROUP BY d.id
ORDER BY d.created_at DESC;
```
