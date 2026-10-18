"""
tests/test_crm.py  –  Phase 3.1
Tests for Incident Ticket CRM layer and REST endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from app.crm import (
    create_ticket,
    get_crm_stats,
    get_ticket,
    list_tickets,
    update_ticket_status,
)
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_crm_create_ticket_direct():
    """create_ticket() should insert an incident record and return all fields."""
    ticket = create_ticket(
        subject="Database High CPU Spike",
        description="CPU utilization on primary database exceeded 92% for 5 minutes.",
        priority="P2",
    )
    assert ticket["id"] is not None
    assert ticket["subject"] == "Database High CPU Spike"
    assert ticket["priority"] == "P2"
    assert ticket["status"] == "open"
    assert "created_at" in ticket


def test_crm_get_ticket_direct():
    """get_ticket() should retrieve an existing ticket or return None if missing."""
    ticket = create_ticket(
        subject="Ingress 504 Gateway Timeout",
        description="Ingress controller reporting 504 timeouts to backend pods.",
        priority="P1",
    )
    fetched = get_ticket(ticket["id"])
    assert fetched is not None
    assert fetched["id"] == ticket["id"]
    assert fetched["subject"] == "Ingress 504 Gateway Timeout"

    # Non-existent
    assert get_ticket(999999) is None


def test_crm_update_ticket_status_direct():
    """update_ticket_status() should transition status and append resolution notes."""
    ticket = create_ticket(
        subject="Worker Pod Memory Alert",
        description="Pod knowops-worker-1 near memory limit.",
        priority="P3",
    )
    updated = update_ticket_status(
        ticket_id=ticket["id"],
        status="resolved",
        resolution_notes="Increased memory limit from 512Mi to 1Gi in deployment manifest.",
    )
    assert updated is not None
    assert updated["status"] == "resolved"
    assert "Increased memory limit" in updated["resolution_notes"]


def test_crm_stats_direct():
    """get_crm_stats() should return valid count aggregation."""
    stats = get_crm_stats()
    assert "total_tickets" in stats
    assert "open" in stats
    assert "resolved" in stats
    assert stats["total_tickets"] >= 1


def test_api_create_ticket_endpoint(client, auth_headers):
    """POST /tickets should create a new ticket and return 200 with a valid token."""
    payload = {
        "subject": "API Latency Degradation Test",
        "description": "Endpoint /ask responding in >3000ms under load testing.",
        "priority": "P2",
    }
    response = client.post("/tickets", json=payload, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["subject"] == payload["subject"]
    assert data["priority"] == "P2"
    assert data["status"] == "open"
    assert isinstance(data["id"], int)


def test_api_create_ticket_requires_auth(client):
    """POST /tickets with no token should return 401 (Phase 5.4)."""
    payload = {
        "subject": "Unauthenticated Ticket Attempt",
        "description": "Should be rejected before it reaches the CRM.",
        "priority": "P2",
    }
    response = client.post("/tickets", json=payload)
    assert response.status_code == 401


def test_api_list_tickets_endpoint(client, auth_headers):
    """GET /tickets should return a list of tickets, supporting status/priority filters."""
    response = client.get("/tickets", headers=auth_headers)
    assert response.status_code == 200
    tickets = response.json()
    assert isinstance(tickets, list)
    assert len(tickets) > 0

    # Filter by priority
    p1_res = client.get("/tickets?priority=P1", headers=auth_headers)
    assert p1_res.status_code == 200
    p1_tickets = p1_res.json()
    assert all(t["priority"] == "P1" for t in p1_tickets)


def test_api_list_tickets_requires_auth(client):
    """GET /tickets with no token should return 401 (Phase 5.4)."""
    assert client.get("/tickets").status_code == 401


def test_api_ticket_stats_endpoint(client, auth_headers):
    """GET /tickets/stats should return summary counts."""
    response = client.get("/tickets/stats", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total_tickets"] >= 1
    assert data["open"] >= 0


def test_api_update_ticket_endpoint(client, auth_headers):
    """PATCH /tickets/{id} should update status and notes."""
    # Create ticket first
    create_res = client.post(
        "/tickets",
        json={"subject": "Patch Test Ticket", "description": "Testing status update.", "priority": "P4"},
        headers=auth_headers,
    )
    ticket_id = create_res.json()["id"]

    patch_res = client.patch(
        f"/tickets/{ticket_id}",
        json={"status": "in_progress", "resolution_notes": "Investigation started by SRE."},
        headers=auth_headers,
    )
    assert patch_res.status_code == 200
    data = patch_res.json()
    assert data["status"] == "in_progress"
    assert data["resolution_notes"] == "Investigation started by SRE."


def test_api_ticket_not_found(client, auth_headers):
    """GET /tickets/999999 and PATCH /tickets/999999 should return 404 for an authenticated caller."""
    assert client.get("/tickets/999999", headers=auth_headers).status_code == 404
    assert client.patch("/tickets/999999", json={"status": "resolved"}, headers=auth_headers).status_code == 404
