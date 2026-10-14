"""
tests/test_agent.py  –  Phase 3.2 & 3.3
Tests for Autonomous ReAct Agent tools, triage pipeline, and cron re-indexing.
"""

import json
import pytest
from fastapi.testclient import TestClient

from app.agent import (
    tool_execute_recovery_action,
    tool_get_ticket,
    tool_lookup_runbook,
    tool_run_system_diagnostics,
    tool_update_ticket,
)
from app.crm import create_ticket
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


def test_api_cron_reindex_endpoint(client):
    """POST /cron/reindex should verify knowledge base files and return 200."""
    response = client.post("/cron/reindex")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["documents_indexed"] >= 4
    assert data["chunks_created"] >= 60
