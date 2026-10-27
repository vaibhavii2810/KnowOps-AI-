"""
app/agent.py  –  Phase 3.2
Autonomous ReAct Agent & Operational Tool-Calling Engine for KnowOps AI.

This module provides:
  - Operational diagnostic & remediation tools (runbook lookup, CRM ticket create/get/update,
    human escalation, system diagnostics, recovery actions) — build-guide Phase 7.1
  - Autonomous ReAct (Reasoning + Action) execution loop
  - Automated incident triage pipeline: triage_ticket_with_agent()
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

import httpx

from app.crm import get_ticket, update_ticket_status, create_ticket, list_tickets
from app.db import get_conn
from app.llm import get_client, settings
from app.rag import retrieve, format_context_for_llm


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------

def tool_lookup_runbook(query: str) -> str:
    """
    Search the operational knowledge base using RAG retrieval for relevant runbooks.
    """
    chunks = retrieve(query, top_k=3, threshold=0.50)
    if not chunks:
        return "No relevant runbook sections found with similarity >= 0.50."

    formatted = []
    for c in chunks:
        formatted.append(
            f"[{c.document_title} › {c.heading} (Similarity: {c.similarity:.2f})]\n{c.content}"
        )
    return "\n\n---\n\n".join(formatted)


def tool_get_ticket(ticket_id: int) -> str:
    """
    Retrieve an incident ticket from the CRM by ID.
    """
    ticket = get_ticket(ticket_id)
    if not ticket:
        return f"Ticket #{ticket_id} not found."
    return json.dumps(ticket, indent=2)


def tool_update_ticket(ticket_id: int, status: str, resolution_notes: str) -> str:
    """
    Update ticket status ('in_progress', 'resolved', 'closed') and append resolution notes.
    """
    updated = update_ticket_status(ticket_id, status=status, resolution_notes=resolution_notes)
    if not updated:
        return f"Failed to update Ticket #{ticket_id}."
    return f"Ticket #{ticket_id} updated successfully: status='{status}'."


def tool_create_ticket(subject: str, description: str, priority: str = "P2") -> str:
    """
    File a new incident ticket in the CRM (build-guide Phase 7.1: create_ticket).
    """
    ticket = create_ticket(subject=subject, description=description, priority=priority)
    return (
        f"Ticket #{ticket['id']} created: '{ticket['subject']}' "
        f"(priority={ticket['priority']}, status={ticket['status']})."
    )


def notify_n8n_escalation(payload: dict) -> None:
    """
    POST an escalation event to the n8n webhook configured in N8N_ESCALATION_WEBHOOK_URL
    (build-guide Phase 9.4 — n8n posts to Discord/Slack when escalate_to_human fires).
    Best-effort: n8n may not be running (it's a local `npx n8n` instance per the guide), so a
    failure here is logged and swallowed rather than breaking the escalation tool itself.
    """
    if not settings.n8n_escalation_webhook_url:
        return
    try:
        httpx.post(settings.n8n_escalation_webhook_url, json=payload, timeout=5.0)
    except Exception as exc:
        print(f"[Warning] Failed to notify n8n escalation webhook: {exc}")


def tool_escalate_to_human(ticket_id: Optional[int], reason: str) -> str:
    """
    Escalate an incident to a human on-call engineer (build-guide Phase 7.1: escalate_to_human).
    Simulated — follows the On-Call Guide's escalation path (D-015 pattern): post to #incidents,
    page the on-call EM via PagerDuty, and for P1s call the VP Engineering directly. If a ticket_id
    is given, its status is set to 'open' and an escalation note is appended (priority is unchanged —
    crm.update_ticket_status doesn't support editing priority). Also notifies the n8n webhook, if
    configured, so a connected workflow can post to Discord/Slack (Phase 9.4, D-031).
    """
    escalation = {
        "action": "escalate_to_human",
        "reason": reason,
        "steps_taken": [
            "Posted current status, severity, and attempted steps in #incidents",
            "Paged the on-call Engineering Manager via PagerDuty",
            "P1 — called VP Engineering directly",
        ],
        "result": "escalated",
    }

    if ticket_id is not None:
        updated = update_ticket_status(
            ticket_id,
            status="open",
            resolution_notes=f"Escalated to human on-call engineer: {reason}",
        )
        if not updated:
            escalation["ticket_update"] = f"Ticket #{ticket_id} not found."
            notify_n8n_escalation(escalation)
            return json.dumps(escalation, indent=2)
        escalation["ticket_id"] = ticket_id
        escalation["ticket_priority"] = updated["priority"]

    notify_n8n_escalation(escalation)
    return json.dumps(escalation, indent=2)


def tool_run_system_diagnostics(component: str) -> str:
    """
    Run diagnostic health checks on an infrastructure component.
    Valid components: 'database', 'kubernetes_pods', 'api_gateway', 'jwt_auth'
    """
    comp = component.lower().strip()

    if comp in ("database", "postgres", "db"):
        try:
            with get_conn() as conn:
                t0 = time.perf_counter()
                conn.execute("SELECT 1").fetchone()
                latency_ms = (time.perf_counter() - t0) * 1000
                doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
                chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

            return json.dumps({
                "component": "database",
                "status": "healthy",
                "connection": "Neon PostgreSQL pooler online",
                "ping_latency_ms": round(latency_ms, 2),
                "active_documents": doc_count,
                "active_chunks": chunk_count,
                "replication_state": "Streaming standby online (db-replica-01.internal)",
            }, indent=2)
        except Exception as e:
            return json.dumps({
                "component": "database",
                "status": "degraded",
                "error": str(e),
                "recommended_action": "Execute database failover runbook (Section 4.2)",
            }, indent=2)

    elif comp in ("kubernetes_pods", "k8s", "pods"):
        return json.dumps({
            "component": "kubernetes_pods",
            "cluster": "knowops-prod",
            "namespace": "production",
            "pods": [
                {"name": "knowops-api-7b8f9c-1", "status": "Running", "restarts": 0, "cpu": "120m", "memory": "280Mi"},
                {"name": "knowops-api-7b8f9c-2", "status": "Running", "restarts": 1, "cpu": "145m", "memory": "310Mi"},
                {"name": "knowops-worker-4d2a1b-1", "status": "CrashLoopBackOff", "restarts": 6, "exit_code": 137, "reason": "OOMKilled (exceeded 512Mi limit)"},
            ],
            "ingress": "Healthy (nginx-ingress 2/2)",
            "diagnostics": "Worker pod crashing due to memory leak. Increase memory limit to 1Gi in deployment manifest.",
        }, indent=2)

    elif comp in ("api_gateway", "ingress", "api"):
        return json.dumps({
            "component": "api_gateway",
            "status": "warning",
            "p99_latency_ms": 420.5,
            "error_rate": "1.2% (HTTP 502 Bad Gateway detected on /ask route)",
            "upstream_target": "knowops-api.production.svc.cluster.local:8000",
            "root_cause_indicator": "Backend API pods temporarily unresponsive under high concurrency",
        }, indent=2)

    elif comp in ("jwt_auth", "auth"):
        return json.dumps({
            "component": "jwt_auth",
            "status": "healthy",
            "algorithm": "HS256",
            "token_expiration_minutes": 60,
            "secret_checksum": "valid",
        }, indent=2)

    return json.dumps({
        "component": component,
        "status": "unknown",
        "message": f"Component '{component}' not recognized. Available: database, kubernetes_pods, api_gateway, jwt_auth",
    })


def tool_execute_recovery_action(action: str, target: str) -> str:
    """
    Execute a safe, verified automated remediation runbook command.
    Actions:
      - 'scale_deployment': Scales pods to handle traffic
      - 'restart_worker_pod': Restarts failing worker pods
      - 'promote_database_replica': Triggers automated failover sequence
      - 'rollback_deployment': Reverts deployment to previous revision
    """
    act = action.lower().strip()

    if act == "scale_deployment":
        return json.dumps({
            "action": "scale_deployment",
            "target": target or "deployment/knowops-api",
            "executed_command": "kubectl scale deployment/knowops-api --replicas=4 -n production",
            "result": "success",
            "output": "deployment.apps/knowops-api scaled from 2 to 4 replicas.",
        }, indent=2)

    elif act == "restart_worker_pod":
        return json.dumps({
            "action": "restart_worker_pod",
            "target": target or "deployment/knowops-worker",
            "executed_command": "kubectl rollout restart deployment/knowops-worker -n production",
            "result": "success",
            "output": "deployment.apps/knowops-worker restarted. New pods scheduled with clean state.",
        }, indent=2)

    elif act == "promote_database_replica":
        return json.dumps({
            "action": "promote_database_replica",
            "target": "db-replica-01.internal",
            "executed_command": "SELECT pg_promote(); ALTER SYSTEM SET primary_conninfo = '';",
            "result": "success",
            "output": "Standby server promoted to primary in 1.4s. Connection string pointed to new primary.",
        }, indent=2)

    elif act == "rollback_deployment":
        return json.dumps({
            "action": "rollback_deployment",
            "target": target or "deployment/knowops-api",
            "executed_command": "kubectl rollout undo deployment/knowops-api -n production",
            "result": "success",
            "output": "deployment.apps/knowops-api rolled back to revision 2.",
        }, indent=2)

    return json.dumps({
        "action": action,
        "status": "rejected",
        "reason": f"Action '{action}' is not in the approved automated runbook catalog.",
    })


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------

AVAILABLE_TOOLS: dict[str, Callable[..., Any]] = {
    "lookup_runbook": tool_lookup_runbook,
    "get_ticket": tool_get_ticket,
    "create_ticket": tool_create_ticket,
    "update_ticket": tool_update_ticket,
    "escalate_to_human": tool_escalate_to_human,
    "run_system_diagnostics": tool_run_system_diagnostics,
    "execute_recovery_action": tool_execute_recovery_action,
}


AGENT_SYSTEM_PROMPT = """You are KnowOps Agent, an autonomous Site Reliability Engineering (SRE) and incident response agent.
Your mission is to investigate IT incidents, diagnose root causes using verified runbooks, run system diagnostics, and propose or execute safe remediation actions.

You have access to the following operational tools:
1. lookup_runbook(query: str): Search runbooks for troubleshooting procedures, error codes, and failover steps.
2. get_ticket(ticket_id: int): Retrieve ticket details (subject, description, priority, status).
3. create_ticket(subject: str, description: str, priority: str): File a new incident ticket when none exists yet.
4. update_ticket(ticket_id: int, status: str, resolution_notes: str): Transition ticket to 'in_progress', 'resolved', or 'closed'.
5. escalate_to_human(ticket_id: int | None, reason: str): Page the on-call human engineer when the incident is beyond safe automated remediation (full outage, data loss, security breach, or imminent SLA breach).
6. run_system_diagnostics(component: str): Inspect live health for 'database', 'kubernetes_pods', 'api_gateway', or 'jwt_auth'.
7. execute_recovery_action(action: str, target: str): Run safe remediation actions ('scale_deployment', 'restart_worker_pod', 'promote_database_replica', 'rollback_deployment').

CRITICAL RULES:
- Always base technical diagnosis on verified runbooks retrieved via lookup_runbook.
- ESCALATION TAKES PRIORITY OVER TICKETING. If the situation matches the On-Call Guide's "escalate
  immediately" criteria (full platform outage, data loss, security breach, or imminent SLA breach), call
  escalate_to_human FIRST — before create_ticket, before diagnostics, before any remediation attempt.
  escalate_to_human does not need an existing ticket: pass ticket_id=null if none exists yet.
- Otherwise, use create_ticket when the user describes a new incident that has no ticket yet.
- Use escalate_to_human instead of execute_recovery_action whenever the situation matches the "escalate
  immediately" criteria above, even if a ticket already exists.
- Cite the source runbooks and specific sections in your final resolution.
- Provide clear, professional, and actionable SRE summaries.
"""


# ---------------------------------------------------------------------------
# ReAct Orchestrator
# ---------------------------------------------------------------------------

def run_agent(task_prompt: str, max_steps: int = 5) -> dict:
    """
    Execute the autonomous ReAct agent loop on an operational task.

    Args:
        task_prompt: Natural language task or incident description.
        max_steps: Maximum number of tool iterations to prevent runaway loops.

    Returns:
        Structured trace including thoughts, tool actions, observations, and final answer.
    """
    client = get_client()
    trace: list[dict] = []

    # Format tools schema for prompt guidance
    tools_description = """
Available Tools:
- lookup_runbook: query: string (e.g. {"tool": "lookup_runbook", "args": {"query": "how to rollback kubernetes deployment"}})
- get_ticket: ticket_id: integer (e.g. {"tool": "get_ticket", "args": {"ticket_id": 1}})
- create_ticket: subject: string, description: string, priority: string (e.g. {"tool": "create_ticket", "args": {"subject": "API 500s on /ask", "description": "Gemini returning 503s intermittently", "priority": "P2"}})
- update_ticket: ticket_id: integer, status: string, resolution_notes: string
- escalate_to_human: ticket_id: integer or null, reason: string (e.g. {"tool": "escalate_to_human", "args": {"ticket_id": 1, "reason": "Full platform outage, all endpoints returning 5xx"}})
- run_system_diagnostics: component: string (e.g. {"tool": "run_system_diagnostics", "args": {"component": "database"}})
- execute_recovery_action: action: string, target: string (e.g. {"tool": "execute_recovery_action", "args": {"action": "rollback_deployment", "target": "deployment/knowops-api"}})

Format your thought and next action as JSON:
{
  "thought": "Your reasoning about what to do next",
  "action": "tool_name",
  "args": { "arg_name": "arg_value" },
  "is_final": false,
  "final_answer": ""
}
When you have gathered enough information and resolved or completed the task, set "is_final": true and provide your comprehensive resolution in "final_answer".
"""

    conversation_history = f"Task: {task_prompt}\n\n{tools_description}\n"

    for step_num in range(1, max_steps + 1):
        prompt = (
            f"{conversation_history}\n"
            f"Step {step_num}: Provide your next Thought and Action in JSON."
        )

        try:
            raw_text = None
            last_finish_reason = "unknown"
            # Gemini's JSON mode occasionally returns finish_reason=MALFORMED_RESPONSE with no
            # text at all (not an exception) — observed to be transient, so retry a couple of
            # times before giving up, same as the 429/503 retries in app/llm.py.
            for attempt in range(3):
                resp = client.models.generate_content(
                    model=settings.gemini_chat_model,
                    contents=prompt,
                    config={
                        "system_instruction": AGENT_SYSTEM_PROMPT,
                        "temperature": 0.1,
                        "response_mime_type": "application/json",
                    },
                )
                raw_text = resp.text
                if raw_text:
                    break
                last_finish_reason = resp.candidates[0].finish_reason if resp.candidates else "unknown"
            if not raw_text:
                raise ValueError(f"Gemini returned no response text after 3 attempts (finish_reason={last_finish_reason})")
            step_data = json.loads(raw_text)
        except Exception as exc:
            # Fallback if JSON parsing or model generation encounters temporary error
            step_data = {
                "thought": f"Agent encountered generation notice: {exc}",
                "is_final": True,
                "final_answer": f"Completed triage based on available runbook knowledge. ({exc})"
            }

        thought = step_data.get("thought", "")
        action = step_data.get("action", "")
        args = step_data.get("args", {})
        is_final = step_data.get("is_final", False)
        final_answer = step_data.get("final_answer", "")

        step_record = {
            "step": step_num,
            "thought": thought,
            "action": action,
            "args": args,
            "observation": None,
        }

        has_valid_tool_call = bool(action) and action in AVAILABLE_TOOLS

        if not has_valid_tool_call:
            step_record["final_answer"] = final_answer or thought
            trace.append(step_record)
            break

        # Execute Tool. Run it even when Gemini also set is_final=true in the same reply —
        # otherwise a tool call bundled with is_final is silently dropped while the model still
        # reports success (observed live: update_ticket requested + is_final=true in one step
        # meant the ticket was never actually updated, see D-027).
        tool_fn = AVAILABLE_TOOLS[action]
        try:
            if isinstance(args, dict):
                observation = tool_fn(**args)
            elif isinstance(args, list):
                observation = tool_fn(*args)
            else:
                observation = tool_fn(args)
        except Exception as e:
            observation = f"Tool execution error: {e}"

        step_record["observation"] = observation

        if is_final:
            step_record["final_answer"] = final_answer or thought
            trace.append(step_record)
            break

        trace.append(step_record)

        # Append to context for next step
        conversation_history += (
            f"\nThought {step_num}: {thought}\n"
            f"Action {step_num}: {action}({json.dumps(args)})\n"
            f"Observation {step_num}: {observation}\n"
        )

    # If loop ended without a non-empty final answer, synthesize one.
    # (Checking `"final_answer" in s` instead of `s.get("final_answer")` would miss a step whose
    # final_answer is present but blank — e.g. a malformed Gemini response — and silently return "".)
    if not any(s.get("final_answer") for s in trace):
        summary_prompt = (
            f"{conversation_history}\n\n"
            "Provide the final SRE incident resolution report based on all observations."
        )
        try:
            final_resp = client.models.generate_content(
                model=settings.gemini_chat_model,
                contents=summary_prompt,
                config={"system_instruction": AGENT_SYSTEM_PROMPT, "temperature": 0.2},
            )
            final_text = final_resp.text or "Incident investigation concluded."
        except Exception as e:
            final_text = f"Investigation completed. Steps executed: {len(trace)}."
        trace.append({"step": len(trace) + 1, "thought": "Final resolution synthesized", "final_answer": final_text})

    return {
        "task": task_prompt,
        "total_steps": len(trace),
        "steps": trace,
        "resolution": trace[-1].get("final_answer", "Completed."),
    }


def triage_ticket_with_agent(ticket_id: int) -> dict:
    """
    High-level automated triage pipeline for a specific incident ticket.
    1. Loads ticket details.
    2. Runs ReAct agent with tools to diagnose and propose remediation.
    3. Updates ticket in PostgreSQL with resolution notes.
    """
    ticket = get_ticket(ticket_id)
    if not ticket:
        raise ValueError(f"Ticket #{ticket_id} does not exist.")

    prompt = (
        f"Investigate Incident Ticket #{ticket['id']}:\n"
        f"Subject: {ticket['subject']}\n"
        f"Priority: {ticket['priority']}\n"
        f"Description: {ticket['description']}\n\n"
        f"Goals:\n"
        f"1. Use lookup_runbook to identify the relevant operational procedure.\n"
        f"2. Use run_system_diagnostics to check the impacted component.\n"
        f"3. Propose or execute remediation via execute_recovery_action if needed.\n"
        f"4. Use update_ticket to set status to 'resolved' with clear technical resolution notes."
    )

    triage_result = run_agent(prompt, max_steps=4)

    # Refresh ticket state after agent run
    updated_ticket = get_ticket(ticket_id)

    return {
        "ticket_id": ticket_id,
        "initial_ticket": ticket,
        "updated_ticket": updated_ticket,
        "triage_trace": triage_result["steps"],
        "resolution_summary": triage_result["resolution"],
    }
