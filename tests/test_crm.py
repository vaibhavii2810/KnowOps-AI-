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

# Phase 11.4: every test here runs on MemoryDB by default and against real Postgres under `pytest -m live`.
pytestmark = pytest.mark.usefixtures("db_backend")


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
    create_ticket(subject="Stats probe", description="Counted by get_crm_stats().", priority="P1")
    stats = get_crm_stats()
    assert "total_tickets" in stats
    assert "open" in stats
    assert "resolved" in stats
    assert stats["total_tickets"] >= 1


def test_closed_p1_ticket_is_not_counted_as_an_active_incident():
    """Bug #3 (external bug report, Medium, D-057): active_p1_incidents used `status != 'resolved'`, so a
    *closed* P1 ticket (a valid, distinct status per VALID_STATUSES) was still counted as an active incident,
    overstating the dashboard stat. Fixed to an explicit allow-list of the truly-active statuses."""
    ticket = create_ticket(subject="P1 outage", description="Full probe.", priority="P1")
    before = get_crm_stats()["active_p1_incidents"]

    update_ticket_status(ticket_id=ticket["id"], status="closed")

    after = get_crm_stats()["active_p1_incidents"]
    assert after == before - 1


def test_closed_tickets_are_counted_so_the_stats_add_up():
    """Bug #12 (external bug report, Medium, D-065): get_crm_stats() counted open/in_progress/resolved but
    never closed, so total_tickets != open + in_progress + resolved once any ticket was closed — the
    dashboard's own numbers didn't add up. Related to bug #3/D-057 (same function), fixed separately.
    Keeps a second, still-open ticket around on purpose: with only one ticket total, a "closed" count that
    wrongly fell back to the total-tickets count would coincidentally match anyway — this is what actually
    caught that in mutation testing."""
    before = get_crm_stats()
    stays_open = create_ticket(subject="Stays open", description="Full probe.", priority="P4")
    to_close = create_ticket(subject="To be closed", description="Full probe.", priority="P3")
    update_ticket_status(ticket_id=to_close["id"], status="closed")

    after = get_crm_stats()
    assert after["closed"] == before["closed"] + 1
    assert after["open"] == before["open"] + 1  # stays_open, not folded into "closed"
    assert after["total_tickets"] == after["open"] + after["in_progress"] + after["resolved"] + after["closed"]


def test_create_ticket_rejects_an_invalid_priority_instead_of_silently_defaulting():
    """Bug #17 (external bug report, Low, D-070): create_ticket("…","…","P9") used to silently become P2
    while POST /tickets already rejected the same value with a 422 — update_ticket_status() right next to
    it already raised ValueError the same way for an invalid status; create_ticket() now matches it."""
    with pytest.raises(ValueError, match="Invalid priority 'P9'"):
        create_ticket(subject="Test", description="Full probe for the regression test.", priority="P9")


def test_update_ticket_status_leaves_notes_untouched_when_omitted():
    """Bug #18 (external bug report, D-071): calling update_ticket_status() without resolution_notes at
    all (the UNSET default) must leave an existing note alone."""
    ticket = create_ticket(subject="Leave notes alone", description="Full probe.", priority="P3")
    update_ticket_status(ticket_id=ticket["id"], status="in_progress", resolution_notes="Initial note.")

    updated = update_ticket_status(ticket_id=ticket["id"], status="resolved")

    assert updated["resolution_notes"] == "Initial note."


def test_update_ticket_status_clears_notes_when_explicitly_none():
    """Bug #18 (external bug report, D-071): passing resolution_notes=None explicitly must clear a
    previously-set note to NULL — before this fix, None and "omitted" were indistinguishable."""
    ticket = create_ticket(subject="Clear notes", description="Full probe.", priority="P3")
    update_ticket_status(ticket_id=ticket["id"], status="in_progress", resolution_notes="Wrong note.")

    updated = update_ticket_status(ticket_id=ticket["id"], status="in_progress", resolution_notes=None)

    assert updated["resolution_notes"] is None


def test_update_ticket_status_still_sets_a_real_note():
    """The third state: a real string sets the note, same as before this fix."""
    ticket = create_ticket(subject="Set notes", description="Full probe.", priority="P3")

    updated = update_ticket_status(ticket_id=ticket["id"], status="resolved", resolution_notes="Fixed it.")

    assert updated["resolution_notes"] == "Fixed it."


def test_api_patch_ticket_can_clear_resolution_notes_via_explicit_null(client, auth_headers):
    """Bug #18 at the HTTP layer: PATCH with resolution_notes: null must clear it, not leave it alone."""
    create_res = client.post(
        "/tickets",
        json={"subject": "Clear via API", "description": "Full probe.", "priority": "P4"},
        headers=auth_headers,
    )
    ticket_id = create_res.json()["id"]
    client.patch(
        f"/tickets/{ticket_id}",
        json={"status": "in_progress", "resolution_notes": "Wrong note."},
        headers=auth_headers,
    )

    patch_res = client.patch(
        f"/tickets/{ticket_id}",
        json={"status": "in_progress", "resolution_notes": None},
        headers=auth_headers,
    )

    assert patch_res.status_code == 200
    assert patch_res.json()["resolution_notes"] is None


def test_api_patch_ticket_without_resolution_notes_field_leaves_it_untouched(client, auth_headers):
    """Bug #18 at the HTTP layer: PATCH that omits resolution_notes entirely must leave the existing
    note alone, not wipe it the way an explicit null does."""
    create_res = client.post(
        "/tickets",
        json={"subject": "Omit leaves alone", "description": "Full probe.", "priority": "P4"},
        headers=auth_headers,
    )
    ticket_id = create_res.json()["id"]
    client.patch(
        f"/tickets/{ticket_id}",
        json={"status": "in_progress", "resolution_notes": "Keep me."},
        headers=auth_headers,
    )

    patch_res = client.patch(f"/tickets/{ticket_id}", json={"status": "resolved"}, headers=auth_headers)

    assert patch_res.status_code == 200
    assert patch_res.json()["resolution_notes"] == "Keep me."


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
    create_ticket(subject="List probe P1", description="Should appear under priority=P1.", priority="P1")
    create_ticket(subject="List probe P3", description="Should not appear under priority=P1.", priority="P3")
    response = client.get("/tickets", headers=auth_headers)
    assert response.status_code == 200
    tickets = response.json()
    assert isinstance(tickets, list)
    assert len(tickets) > 0

    # Filter by priority
    p1_res = client.get("/tickets?priority=P1", headers=auth_headers)
    assert p1_res.status_code == 200
    p1_tickets = p1_res.json()
    assert p1_tickets and all(t["priority"] == "P1" for t in p1_tickets)


def test_api_list_tickets_requires_auth(client):
    """GET /tickets with no token should return 401 (Phase 5.4)."""
    assert client.get("/tickets").status_code == 401


def test_api_ticket_stats_endpoint(client, auth_headers):
    """GET /tickets/stats should return summary counts."""
    create_ticket(subject="Stats probe", description="Counted by /tickets/stats.", priority="P2")
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
