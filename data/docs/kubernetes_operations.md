# Kubernetes Cluster Operations Guide

**Document ID:** K8S-001  
**Title:** Kubernetes Cluster Operations Guide  
**Category:** Infrastructure / Container Orchestration  
**Owner:** Platform Engineering  
**Last Updated:** 2026-03-01  

---

## 1. Overview

This guide covers day-to-day operational procedures for managing the KnowOps AI Kubernetes clusters. The platform runs on AWS EKS with the following cluster configuration:

| Cluster | Region | Purpose | Node Count |
|---|---|---|---|
| `knowops-prod` | ap-southeast-1 | Production workloads | 6 nodes (m5.xlarge) |
| `knowops-staging` | ap-southeast-1 | Staging / QA | 3 nodes (m5.large) |
| `knowops-dev` | us-east-1 | Development | 2 nodes (t3.medium) |

---

## 2. Connecting to the Cluster

```bash
# Update kubeconfig for production cluster
aws eks update-kubeconfig --name knowops-prod --region ap-southeast-1

# Verify connection
kubectl cluster-info
kubectl get nodes

# Switch between clusters
kubectl config use-context knowops-prod
kubectl config use-context knowops-staging
```

---

## 3. Key Namespaces

| Namespace | Contents |
|---|---|
| `production` | API server, worker pods, ingress |
| `monitoring` | Grafana, Prometheus, AlertManager |
| `cert-manager` | TLS certificate automation |
| `kube-system` | Core Kubernetes components |

---

## 4. Deployment Operations

### 4.1 Deploy a New Version

```bash
# Update image tag in deployment
kubectl set image deployment/knowops-api \
  api=ghcr.io/knowops/api:v2.3.1 \
  -n production

# Monitor the rolling update
kubectl rollout status deployment/knowops-api -n production

# Verify new pods are healthy
kubectl get pods -n production -l app=knowops-api
```

### 4.2 Canary Deployment

For risk-sensitive releases, deploy to 20% of traffic first:

```bash
# Scale down current deployment to 80%
kubectl scale deployment/knowops-api --replicas=4 -n production

# Deploy canary with new image (1 replica = ~20% traffic)
kubectl apply -f k8s/canary-deployment.yaml -n production

# Monitor error rates in Datadog for 30 minutes
# If healthy → proceed with full rollout
kubectl scale deployment/knowops-api --replicas=5 -n production
kubectl delete deployment/knowops-api-canary -n production
```

### 4.3 Rollback

```bash
# Immediate rollback to previous version
kubectl rollout undo deployment/knowops-api -n production

# Check rollout history
kubectl rollout history deployment/knowops-api -n production

# Rollback to specific revision
kubectl rollout undo deployment/knowops-api --to-revision=3 -n production
```

---

## 5. Scaling Operations

### 5.1 Manual Scaling

```bash
# Scale API pods
kubectl scale deployment/knowops-api --replicas=8 -n production

# Check Horizontal Pod Autoscaler (HPA) status
kubectl get hpa -n production

# Describe HPA for current scaling decisions
kubectl describe hpa knowops-api-hpa -n production
```

### 5.2 HPA Configuration

The HPA is configured to scale between 3 and 10 replicas based on:
- CPU utilization > 70%
- Memory utilization > 80%
- Custom metric: requests per second > 100

```yaml
# HPA resource definition (reference)
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: knowops-api-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: knowops-api
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

---

## 6. Node Management

### 6.1 Draining a Node for Maintenance

```bash
# Safely drain a node (evict all pods)
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data

# Verify the node is cordoned
kubectl get nodes

# After maintenance, uncordon the node
kubectl uncordon <node-name>
```

### 6.2 Adding Nodes (EKS Node Group)

```bash
# Update node group desired count via AWS CLI
aws eks update-nodegroup-config \
  --cluster-name knowops-prod \
  --nodegroup-name main-nodes \
  --scaling-config minSize=6,maxSize=12,desiredSize=8 \
  --region ap-southeast-1
```

---

## 7. Debugging Pods

### 7.1 Investigating CrashLoopBackOff

```bash
# Get pod details and events
kubectl describe pod <pod-name> -n production

# View current and previous container logs
kubectl logs <pod-name> -n production
kubectl logs <pod-name> -n production --previous

# Run an interactive shell in the pod
kubectl exec -it <pod-name> -n production -- /bin/bash

# For distroless images, use debug container
kubectl debug -it <pod-name> --image=busybox -n production
```

### 7.2 Pod Stuck in Pending State

Most common causes:
1. **Insufficient resources** — node pool is full
2. **Node selector mismatch** — pod requires a label the nodes don't have
3. **PVC not bound** — persistent volume claim not provisioned

```bash
# Check events for the pending pod
kubectl describe pod <pod-name> -n production

# Check node resource availability
kubectl describe nodes | grep -A 5 "Allocated resources"
```

---

## 8. Secrets Management

All secrets are stored in **AWS Secrets Manager** and injected at pod startup via the AWS Secrets CSI Driver.

```bash
# List secrets used by production pods
kubectl get secretproviderclass -n production

# Verify a secret is mounted correctly
kubectl exec -it <pod-name> -n production -- cat /mnt/secrets/gemini-api-key
```

**Never** store secrets in:
- Kubernetes ConfigMaps
- Environment variables defined in deployment YAML
- Git repository (even private)

---

## 9. Resource Quotas & Limits

| Resource | Request | Limit |
|---|---|---|
| CPU (per pod) | 250m | 1000m |
| Memory (per pod) | 256Mi | 1Gi |
| Namespace CPU quota | 4 cores | — |
| Namespace memory quota | 8Gi | — |

To check current usage against quotas:
```bash
kubectl describe resourcequota -n production
```

---

## 10. Useful One-Liners

```bash
# All pods not in Running state
kubectl get pods -A --field-selector=status.phase!=Running

# Pod restart counts
kubectl get pods -n production --sort-by='.status.containerStatuses[0].restartCount'

# Resource usage across all pods
kubectl top pods -n production

# Resource usage by node
kubectl top nodes

# View all events sorted by time
kubectl get events -n production --sort-by='.lastTimestamp'

# Port-forward for local debugging
kubectl port-forward svc/knowops-api 8080:80 -n production
```
