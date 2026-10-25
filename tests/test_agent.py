"""
tests/test_agent.py  –  Phase 3.2 & 3.3
Tests for Autonomous ReAct Agent tools, triage pipeline, and cron re-indexing.
"""

import json
import pytest
from fastapi.testclient import TestClient

from app.agent import (
    run_agent,
    tool_create_ticket,
    tool_escalate_to_human,
    tool_execute_recovery_action,
    tool_get_ticket,
    tool_lookup_runbook,
    tool_run_system_diagnostics,
    tool_update_ticket,
)
from app.crm import create_ticket, get_ticket
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_agent_tool_lookup_runbook():
    """tool_lookup_runbook() should return matched excerpts from operational runbooks."""
    result = tool_lookup_runbook("How do I perform a database failover?")
    assert "Disaster Recovery" in result
    assert "Verification" in result or "Failover" in result or "Primary" in result


def test_agent_tool_run_system_diagnostics():
    """tool_run_system_diagnostics() should return JSON diagnostic data for known components."""
    # Database
    db_res = json.loads(tool_run_system_diagnostics("database"))
    assert db_res["component"] == "database"
    assert db_res["status"] in ("healthy", "degraded")

    # Kubernetes Pods
    k8s_res = json.loads(tool_run_system_diagnostics("kubernetes_pods"))
    assert k8s_res["component"] == "kubernetes_pods"
    assert "pods" in k8s_res

    # API Gateway
    api_res = json.loads(tool_run_system_diagnostics("api_gateway"))
    assert api_res["component"] == "api_gateway"


def test_agent_tool_execute_recovery_action():
    """tool_execute_recovery_action() should execute approved actions and reject unknown ones."""
    # Scale deployment
    scale_res = json.loads(tool_execute_recovery_action("scale_deployment", "deployment/knowops-api"))
    assert scale_res["result"] == "success"
    assert "scaled" in scale_res["output"]

    # Rollback deployment
    rb_res = json.loads(tool_execute_recovery_action("rollback_deployment", "deployment/knowops-api"))
    assert rb_res["result"] == "success"

    # Unknown action rejected
    unkn_res = json.loads(tool_execute_recovery_action("delete_database", "all"))
    assert unkn_res["status"] == "rejected"


def test_agent_tool_ticket_management():
    """tool_get_ticket and tool_update_ticket should inspect and modify CRM tickets."""
    ticket = create_ticket(
        subject="Agent Tool Test Ticket",
        description="Testing agent ticket management tools.",
        priority="P2",
    )
    t_id = ticket["id"]

    # Get ticket tool
    t_str = tool_get_ticket(t_id)
    t_data = json.loads(t_str)
    assert t_data["id"] == t_id

    # Update ticket tool
    upd_msg = tool_update_ticket(t_id, status="resolved", resolution_notes="Auto-remediated by agent.")
    assert "updated successfully" in upd_msg


def test_agent_tool_create_ticket():
    """tool_create_ticket() should file a new ticket via the CRM (Phase 7.1)."""
    msg = tool_create_ticket(
        subject="Agent-filed: API latency spike",
        description="p99 latency on /ask exceeded 3s for 10 minutes.",
        priority="P2",
    )
    assert "created" in msg
    assert "Agent-filed: API latency spike" in msg
    ticket_id = int(msg.split("#")[1].split(" ")[0])
    assert get_ticket(ticket_id)["priority"] == "P2"


def test_agent_tool_escalate_to_human():
    """tool_escalate_to_human() should return the on-call escalation path and, given a
    ticket_id, set that ticket's status and append an escalation note (Phase 7.1)."""
    ticket = create_ticket(
        subject="Full platform outage",
        description="All API endpoints returning 5xx.",
        priority="P1",
    )

    result = json.loads(tool_escalate_to_human(ticket["id"], "Full platform outage, all endpoints 5xx"))
    assert result["result"] == "escalated"
    assert "PagerDuty" in " ".join(result["steps_taken"])
    assert result["ticket_id"] == ticket["id"]

    updated = get_ticket(ticket["id"])
    assert updated["status"] == "open"
    assert "Escalated to human" in updated["resolution_notes"]

    # Escalation with no ticket attached still returns the steps, with no ticket fields.
    no_ticket_result = json.loads(tool_escalate_to_human(None, "Security breach suspected"))
    assert no_ticket_result["result"] == "escalated"
    assert "ticket_id" not in no_ticket_result

    # Unknown ticket id is reported, not raised.
    missing_result = json.loads(tool_escalate_to_human(999999, "test"))
    assert "not found" in missing_result["ticket_update"]


class _FakeCandidate:
    def __init__(self, finish_reason):
        self.finish_reason = finish_reason


class _FakeResponse:
    """Mimics a Gemini response with finish_reason=MALFORMED_RESPONSE: .text is None."""

    def __init__(self):
        self.text = None
        self.candidates = [_FakeCandidate("MALFORMED_RESPONSE")]


class _FakeModels:
    def __init__(self):
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        return _FakeResponse()


class _FakeClient:
    def __init__(self):
        self.models = _FakeModels()


def test_run_agent_never_returns_blank_resolution_on_malformed_gemini_response(monkeypatch):
    """
    Regression test for a real bug found during Phase 7.2 live testing: Gemini's JSON mode can
    return finish_reason=MALFORMED_RESPONSE with resp.text=None (not an exception). The old code
    silently parsed `resp.text or "{}"` into a blank thought/action/final_answer, and the post-loop
    synthesis fallback only checked `"final_answer" in s` (key presence, not truthiness), so a blank
    final_answer was mistaken for a real one and run_agent() returned resolution="".
    This asserts the fix: every attempt is retried (3x), the loop step records a non-blank
    final_answer via the exception fallback, and run_agent()'s top-level resolution is never blank.
    """
    fake_client = _FakeClient()
    monkeypatch.setattr("app.agent.get_client", lambda: fake_client)

    result = run_agent("Investigate a database issue.", max_steps=2)

    assert result["resolution"].strip() != ""
    assert "MALFORMED_RESPONSE" in result["resolution"] or "generation" in result["resolution"].lower()
    # 3 retry attempts for the one step that ran before max_steps/is_final stopped the loop
    assert fake_client.models.calls == 3


class _FakeTextResponse:
    """Mimics a Gemini response carrying real JSON text."""

    def __init__(self, text):
        self.text = text
        self.candidates = [_FakeCandidate("STOP")]


class _FakeModelsSingleReply:
    def __init__(self, reply_json):
        self.reply_json = reply_json
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        return _FakeTextResponse(self.reply_json)


def test_run_agent_executes_tool_call_bundled_with_is_final(monkeypatch):
    """
    Regression test for a real bug found live during Phase 7.4 triage testing: Gemini sometimes
    returns a valid tool call AND is_final=true in the SAME JSON reply. The old code's
    `if is_final or not action or ...: break` exited before the tool-execution block ever ran,
    so the requested tool call (e.g. update_ticket) was silently skipped while run_agent() still
    returned a confident final_answer claiming the action was taken — the ticket was never
    actually updated. See D-027.
    This asserts the fix: a valid tool call bundled with is_final is still executed (its real
    observation lands in the trace and the database), and the loop still ends on that step.
    """
    ticket = create_ticket(
        subject="Regression test ticket for bundled is_final+action",
        description="Created to verify update_ticket actually runs when Gemini also sets is_final.",
        priority="P3",
    )

    reply = json.dumps({
        "thought": "Resolving now.",
        "action": "update_ticket",
        "args": {"ticket_id": ticket["id"], "status": "resolved", "resolution_notes": "Fixed via regression test."},
        "is_final": True,
        "final_answer": "Ticket resolved.",
    })
    fake_client = type("FC", (), {})()
    fake_client.models = _FakeModelsSingleReply(reply)
    monkeypatch.setattr("app.agent.get_client", lambda: fake_client)

    result = run_agent(f"Resolve ticket #{ticket['id']}", max_steps=2)

    assert fake_client.models.calls == 1  # didn't need extra steps — one reply was enough
    assert result["steps"][-1]["action"] == "update_ticket"
    assert result["steps"][-1]["observation"] is not None  # the tool call actually ran
    assert result["resolution"] == "Ticket resolved."

    updated = get_ticket(ticket["id"])
    assert updated["status"] == "resolved"
    assert updated["resolution_notes"] == "Fixed via regression test."


def test_api_cron_reindex_endpoint(client):
    """POST /cron/reindex should verify knowledge base files and return 200."""
    response = client.post("/cron/reindex")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["documents_indexed"] >= 4
    assert data["chunks_created"] >= 60
