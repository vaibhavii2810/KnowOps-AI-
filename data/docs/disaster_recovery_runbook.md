# Disaster Recovery Runbook

**Document ID:** DR-001  
**Title:** Disaster Recovery Runbook  
**Category:** Infrastructure / Business Continuity  
**Owner:** Platform SRE Team  
**Last Updated:** 2026-01-10  

---

## 1. Overview

This runbook defines the procedures for recovering critical services following a major infrastructure failure, data-centre outage, or regional cloud provider disruption. It covers RTO (Recovery Time Objective) and RPO (Recovery Point Objective) targets, escalation paths, and step-by-step recovery procedures.

**RTO Target:** 4 hours for Tier-1 services  
**RPO Target:** 1 hour (maximum data loss tolerance)  

---

## 2. Incident Classification

| Severity | Description | RTO |
|---|---|---|
| P1 – Critical | Full platform outage, all users impacted | 1 hour |
| P2 – High | Partial outage, >50% users impacted | 2 hours |
| P3 – Medium | Degraded performance, <50% impacted | 4 hours |
| P4 – Low | Single service degraded, workaround available | 8 hours |

---

## 3. First Response (0–15 Minutes)

1. **Acknowledge the alert** in PagerDuty within 5 minutes.
2. **Create a War Room** in Slack: `#incident-<date>-<service>`.
3. **Assign an Incident Commander (IC)** — the on-call SRE lead.
4. **Notify stakeholders** using the `/incident broadcast` Slack bot.
5. **Begin the timeline log** in the incident management portal.

---

## 4. Database Failover Procedure

### 4.1 Detecting Primary Database Failure

Signs of primary DB failure:
- Alert: `pg_primary_unreachable` firing in Grafana
- Connection errors: `FATAL: could not connect to the primary database server`
- Application error rate exceeds 20% (5xx responses)

### 4.2 Manual Failover Steps

```bash
# 1. SSH into the standby replica host
ssh ops@db-replica-01.internal

# 2. Promote the replica to primary
pg_ctl promote -D /var/lib/postgresql/16/main

# 3. Confirm promotion
psql -c "SELECT pg_is_in_recovery();"
# Expected output: f (false = now primary)

# 4. Update the DNS CNAME record
# Change: db.internal → db-replica-01.internal
aws route53 change-resource-record-sets \
  --hosted-zone-id Z12345 \
  --change-batch file://failover-dns.json

# 5. Restart application pods to re-establish connections
kubectl rollout restart deployment/api-server -n production
```

### 4.3 Verification

After failover, confirm:
- `SELECT COUNT(*) FROM critical_table;` returns expected row counts
- Application health checks return `200 OK`
- Monitoring dashboards show reduced error rate

---

## 5. Application Recovery Procedure

### 5.1 Kubernetes Pod Recovery

```bash
# Check pod status
kubectl get pods -n production

# Describe failing pod for root cause
kubectl describe pod <pod-name> -n production

# Force restart all pods in deployment
kubectl rollout restart deployment/knowops-api -n production

# Watch rollout progress
kubectl rollout status deployment/knowops-api -n production
```

### 5.2 Rollback to Previous Version

If the current deployment caused the incident:

```bash
# List revision history
kubectl rollout history deployment/knowops-api -n production

# Rollback to previous revision
kubectl rollout undo deployment/knowops-api -n production

# Or rollback to a specific revision
kubectl rollout undo deployment/knowops-api --to-revision=5 -n production
```

---

## 6. Communication Templates

### 6.1 Initial Customer Notification
> **Subject:** [Incident] Service Disruption – KnowOps AI Platform  
> We are currently experiencing a service disruption affecting [service]. Our team is actively investigating. Next update in 30 minutes.

### 6.2 Resolution Notification
> **Subject:** [Resolved] Service Restored – KnowOps AI Platform  
> The incident affecting [service] has been resolved as of [time]. Root cause analysis will be published within 48 hours.

---

## 7. Post-Incident Actions

1. Schedule a **Post-Incident Review (PIR)** within 48 hours.
2. Document the **Root Cause Analysis (RCA)** using the 5 Whys method.
3. Create **action items** in Jira with owners and deadlines.
4. Update this runbook if new steps were discovered during recovery.
5. Share the **PIR report** with all stakeholders.

---

## 8. Contact Escalation Matrix

| Role | Name | Primary Contact | Escalate After |
|---|---|---|---|
| On-Call SRE | Rotation | PagerDuty | 15 min no response |
| Engineering Manager | Platform Lead | Slack DM | 30 min |
| VP Engineering | — | Phone | P1 only |
| Cloud Provider Support | AWS/GCP | Support portal | 1 hour |
