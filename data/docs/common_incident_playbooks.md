# Common Incident Playbooks

**Document ID:** OPS-005  
**Title:** Common Incident Playbooks  
**Category:** Incident Response  
**Owner:** Platform SRE Team  
**Last Updated:** 2026-10-15  

---

## 1. Overview

This document collects short, step-by-step playbooks for the incidents the platform sees most often. Each playbook lists the symptoms, how to confirm the cause, the fix, and how to verify recovery. If a playbook does not resolve the issue within 30 minutes, escalate per the On-Call Guide.

---

## 2. Pod OOMKilled / CrashLoopBackOff

**Symptoms:** a pod shows `CrashLoopBackOff`, restart count keeps rising, exit code `137`.

**Confirm the cause:**

```bash
kubectl describe pod <pod-name> -n production | grep -A3 "Last State"
kubectl top pod <pod-name> -n production
```

If `Reason: OOMKilled` appears, the container exceeded its memory limit.

**Fix:**

1. Check whether memory grew steadily (a leak) or spiked (a large request) in the last 24 hours of the memory dashboard.
2. As a short-term fix, raise the memory limit, e.g. from `512Mi` to `1Gi`, in the deployment manifest and apply it.
3. For a leak, open a P3 ticket for the owning team with the memory graph attached; the limit increase only buys time.

**Verify:** the pod stays `Running` with zero new restarts for 15 minutes.

---

## 3. HTTP 502 Bad Gateway

**Symptoms:** clients receive 502 responses; the ingress error rate rises above 1%.

A 502 means the gateway could not get a valid response from the upstream pod. The usual causes are pods restarting, pods failing readiness checks, or upstream requests timing out.

**Confirm the cause:**

```bash
kubectl get pods -n production -l app=knowops-api
kubectl logs -n ingress-nginx deploy/ingress-nginx-controller --since=15m | grep " 502 "
```

**Fix:**

1. If pods are restarting, follow the OOMKilled playbook above.
2. If pods are healthy but slow, check upstream latency; long LLM calls on `/ask` can exceed the proxy timeout. Raise `proxy-read-timeout` to 60s or reduce the work done per request.
3. If only one node is affected, cordon it and let pods reschedule.

**Verify:** the 502 rate returns below 0.1% for 15 minutes.

---

## 4. JWT Authentication Failures

**Symptoms:** a sudden spike of HTTP 401 responses across all users.

**Common causes:**

- `JWT_SECRET` was rotated but some pods still run with the old value, so tokens signed by one pod fail on another.
- Server clock skew makes freshly issued tokens look expired.
- Clients are sending the token without the `Bearer ` prefix.

**Fix:**

1. Confirm every pod uses the same secret version: restart the deployment after any secret change so all pods reload it.
2. Check node clocks with `timedatectl`; NTP drift of more than 30 seconds must be corrected.
3. After a deliberate rotation, all users must log in again. Announce this in the status channel before rotating.

**Verify:** a fresh login token works on several consecutive requests that land on different pods.

---

## 5. Database Connection Pool Exhausted

**Symptoms:** requests fail with `too many connections` or time out waiting for a connection.

**Confirm the cause:**

```sql
SELECT state, count(*) FROM pg_stat_activity GROUP BY state;
```

Many `idle in transaction` sessions point to application code that opens a transaction and never commits.

**Fix:**

1. Make sure the application uses the pooled (`-pooler`) connection string, not the direct one.
2. Terminate sessions idle in a transaction for more than 10 minutes (see the On-Call Guide for the exact query).
3. If traffic is legitimately higher, scale the pooler size before scaling API replicas; more replicas means more connections.

**Verify:** active connections stay below 80% of the limit for 30 minutes.

---

## 6. Knowledge Base Returns No Results

**Symptoms:** `/ask` answers "I don't know" for questions that are covered by the runbooks.

**Fix:**

1. Check that the knowledge base is populated: `SELECT count(*) FROM chunks;` should be greater than zero.
2. If it is empty or stale, re-run ingestion: `python scripts/ingest.py`.
3. Confirm the embedding model and dimension (`gemini-embedding-001`, 768) match what was used at ingestion time; mixing models makes similarity scores meaningless.

**Verify:** a question copied from a runbook heading returns that runbook as the top source.
