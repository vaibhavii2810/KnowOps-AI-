# On-Call Guide & Incident Response Playbook

**Document ID:** OC-001  
**Title:** On-Call Guide & Incident Response Playbook  
**Category:** Operations / SRE  
**Owner:** SRE Lead  
**Last Updated:** 2026-02-15  

---

## 1. Purpose

This guide is the single source of truth for engineers who are on the on-call rotation. It covers how to triage incoming alerts, escalate correctly, handle common failure scenarios, and maintain a high-quality on-call experience.

---

## 2. On-Call Responsibilities

As the on-call engineer, you are responsible for:

- **Acknowledging alerts** within 5 minutes of PagerDuty notification
- **Triaging** the issue to determine scope and severity
- **Resolving or escalating** within the defined SLA windows
- **Documenting** all actions in the incident timeline
- **Handing off** clearly if your shift ends before resolution

---

## 3. Tools & Access

| Tool | Purpose | URL |
|---|---|---|
| PagerDuty | Alert management and on-call schedules | app.pagerduty.com |
| Grafana | Metrics dashboards, alert history | grafana.internal |
| Datadog | APM traces, log aggregation | app.datadoghq.com |
| Slack | Communication (#incidents, #on-call) | knowops.slack.com |
| Runbook Wiki | This and all other runbooks | wiki.internal/runbooks |
| Kubernetes Dashboard | Pod and service health | k8s-dashboard.internal |
| AWS Console | Cloud infrastructure management | console.aws.amazon.com |

---

## 4. Alert Triage Decision Tree

When an alert fires:

1. **Is this a false positive?**
   - Check if a recent deployment was made
   - Verify if the alert self-resolved within 2 minutes
   - If yes → silence the alert and add a note

2. **What is the blast radius?**
   - Check Datadog: how many users are affected?
   - Check Grafana: is error rate >5%? >20%? >50%?
   - Classify as P1/P2/P3/P4 (see severity table in DR-001)

3. **Is there a known runbook for this alert?**
   - Check the runbook wiki using the alert name
   - If yes → follow the runbook
   - If no → escalate to senior SRE and create a new runbook after resolution

---

## 5. Common Alerts & Immediate Actions

### 5.1 `HIGH_CPU_USAGE` — Pod CPU > 85%

**Cause:** Traffic spike, runaway process, or memory leak triggering CPU throttle.

**Immediate action:**
```bash
# Identify the high-CPU pod
kubectl top pods -n production --sort-by=cpu

# Check pod logs for unusual activity
kubectl logs <pod-name> -n production --tail=200

# If a single request is hanging, cordon the node:
kubectl cordon <node-name>

# Scale up replicas to spread load
kubectl scale deployment/knowops-api --replicas=6 -n production
```

### 5.2 `DB_CONNECTION_POOL_EXHAUSTED` — No available DB connections

**Cause:** Connection pool fully occupied; requests queuing up.

**Immediate action:**
```bash
# Check active connections in Postgres
psql $DATABASE_URL -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"

# Check who is holding connections
psql $DATABASE_URL -c "SELECT pid, usename, application_name, state, wait_event, query_start FROM pg_stat_activity ORDER BY query_start;"

# Terminate long-running idle connections (>10 min)
psql $DATABASE_URL -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle' AND query_start < now() - interval '10 minutes';"
```

**Resolution:** Restart the API pods to flush the connection pool.

### 5.3 `SSL_CERTIFICATE_EXPIRY` — Certificate expires in <30 days

**Cause:** TLS certificate approaching expiry (auto-renewal may have failed).

**Steps:**
1. Check cert-manager logs: `kubectl logs -n cert-manager deployment/cert-manager`
2. Force cert renewal: `kubectl delete certificate knowops-tls -n production`
3. Watch cert-manager reissue: `kubectl get certificate -n production -w`

### 5.4 `API_LATENCY_HIGH` — P99 latency > 2s

**Cause:** Slow database queries, large payload sizes, or upstream Gemini API delays.

**Steps:**
1. Check Datadog APM for slowest traces
2. Run `EXPLAIN ANALYZE` on the slow queries identified
3. Check if vector similarity queries are missing the HNSW index:
```sql
EXPLAIN ANALYZE SELECT content FROM chunks 
ORDER BY embedding <=> '[...]'::vector 
LIMIT 5;
-- Should say "Index Scan using chunks_embedding_idx"
```

### 5.5 `GEMINI_API_503` — Upstream AI service unavailable

**Cause:** Google Gemini API experiencing high demand or outage.

**Immediate action:**
- Check Google Cloud Status: status.cloud.google.com
- The `chat_completion()` function has automatic retry logic with exponential backoff (up to 3 attempts)
- If persisting >15 minutes: switch to degraded mode (return cached answers only)
- Notify users: "AI responses may be delayed"

---

## 6. Escalation Paths

### When to Escalate Immediately (don't wait):
- Full platform outage (all API endpoints returning 5xx)
- Data loss detected or suspected
- Security breach or unauthorized access
- SLA breach imminent (<1 hour to SLA violation)

### How to Escalate:
1. Post in `#incidents` with current status, severity, and what you've tried
2. Page the on-call Engineering Manager via PagerDuty
3. For P1: call the VP Engineering directly (phone in PagerDuty contacts)

---

## 7. Shift Handoff Checklist

Before ending your on-call shift:

- [ ] All open incidents have a new assignee
- [ ] Incident timeline is up to date
- [ ] Any muted alerts are documented with an expiry time
- [ ] Handoff message posted in `#on-call` with:
  - Current open incidents
  - Known fragile systems to watch
  - Any scheduled maintenance windows
  - Your contact info in case of questions

---

## 8. On-Call Health & Wellness

On-call should not be a heroic effort. If you are:
- **Paged >3 times per night** → escalate to EM to reduce alert noise
- **Handling P1s back-to-back** → request a shadow on your next shift
- **Uncertain about any runbook step** → ask in `#on-call` before acting

After every P1, a **blameless post-incident review** is mandatory. The goal is to fix the system, not assign blame.
