"""
app/crm.py  –  Phase 3.1
Incident & Support Ticket CRM Layer for KnowOps AI.

This module provides data access operations for managing incident tickets in PostgreSQL:
  - Ticket creation, querying, status transitions, and resolution logging
  - Filtering by status (open, in_progress, resolved) and priority (P1, P2, P3, P4)
  - Ticket metrics and analytics aggregation
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.db import get_conn


VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}
VALID_PRIORITIES = {"P1", "P2", "P3", "P4"}


def create_ticket(
    subject: str,
    description: str,
    priority: str = "P2",
    status: str = "open",
) -> dict:
    """
    Create a new operational incident ticket.

    Args:
        subject: Brief incident summary (e.g., 'Primary Database Connection Timeout')
        description: Detailed incident symptoms or error trace
        priority: 'P1' (Critical), 'P2' (High), 'P3' (Medium), 'P4' (Low)
        status: Initial ticket status (defaults to 'open')

    Returns:
        The newly created ticket record as a dictionary.
    """
    priority = priority.upper() if priority.upper() in VALID_PRIORITIES else "P2"
    status = status.lower() if status.lower() in VALID_STATUSES else "open"
    now = datetime.now(timezone.utc)

    sql = """
        INSERT INTO tickets (subject, description, priority, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, subject, description, priority, status, created_at, updated_at, resolution_notes
    """

    with get_conn() as conn:
        row = conn.execute(
            sql,
            (subject.strip(), description.strip(), priority, status, now, now),
        ).fetchone()

    return {
        "id": row[0],
        "subject": row[1],
        "description": row[2],
        "priority": row[3],
        "status": row[4],
        "created_at": str(row[5]),
        "updated_at": str(row[6]),
        "resolution_notes": row[7],
    }


def get_ticket(ticket_id: int) -> Optional[dict]:
    """
    Retrieve an incident ticket by its primary key ID.
    Returns None if the ticket does not exist.
    """
    sql = """
        SELECT id, subject, description, priority, status, created_at, updated_at, resolution_notes
        FROM tickets
        WHERE id = %s
    """
    with get_conn() as conn:
        row = conn.execute(sql, (ticket_id,)).fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "subject": row[1],
        "description": row[2],
        "priority": row[3],
        "status": row[4],
        "created_at": str(row[5]),
        "updated_at": str(row[6]),
        "resolution_notes": row[7],
    }


def list_tickets(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """
    List incident tickets with optional status and priority filtering.
    Ordered by priority (P1 first) and created_at descending.
    """
    conditions: list[str] = []
    params: list[object] = []

    if status:
        conditions.append("status = %s")
        params.append(status.lower())

    if priority:
        conditions.append("priority = %s")
        params.append(priority.upper())

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT id, subject, description, priority, status, created_at, updated_at, resolution_notes
        FROM tickets
        {where_clause}
        ORDER BY
            CASE priority
                WHEN 'P1' THEN 1
                WHEN 'P2' THEN 2
                WHEN 'P3' THEN 3
                WHEN 'P4' THEN 4
                ELSE 5
            END,
            id DESC
        LIMIT %s
    """
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()

    return [
        {
            "id": r[0],
            "subject": r[1],
            "description": r[2],
            "priority": r[3],
            "status": r[4],
            "created_at": str(r[5]),
            "updated_at": str(r[6]),
            "resolution_notes": r[7],
        }
        for r in rows
    ]


def update_ticket_status(
    ticket_id: int,
    status: str,
    resolution_notes: Optional[str] = None,
) -> Optional[dict]:
    """
    Transition ticket status and optionally append resolution notes.
    """
    status = status.lower()
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of {VALID_STATUSES}")

    now = datetime.now(timezone.utc)

    if resolution_notes is not None:
        sql = """
            UPDATE tickets
            SET status = %s, resolution_notes = %s, updated_at = %s
            WHERE id = %s
            RETURNING id, subject, description, priority, status, created_at, updated_at, resolution_notes
        """
        params = (status, resolution_notes.strip(), now, ticket_id)
    else:
        sql = """
            UPDATE tickets
            SET status = %s, updated_at = %s
            WHERE id = %s
            RETURNING id, subject, description, priority, status, created_at, updated_at, resolution_notes
        """
        params = (status, now, ticket_id)

    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "subject": row[1],
        "description": row[2],
        "priority": row[3],
        "status": row[4],
        "created_at": str(row[5]),
        "updated_at": str(row[6]),
        "resolution_notes": row[7],
    }


def get_crm_stats() -> dict:
    """
    Aggregate statistics across tickets for operational dashboards.
    """
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        open_count = conn.execute("SELECT COUNT(*) FROM tickets WHERE status = 'open'").fetchone()[0]
        in_progress = conn.execute("SELECT COUNT(*) FROM tickets WHERE status = 'in_progress'").fetchone()[0]
        resolved = conn.execute("SELECT COUNT(*) FROM tickets WHERE status = 'resolved'").fetchone()[0]
        p1_count = conn.execute("SELECT COUNT(*) FROM tickets WHERE priority = 'P1' AND status != 'resolved'").fetchone()[0]

    return {
        "total_tickets": total,
        "open": open_count,
        "in_progress": in_progress,
        "resolved": resolved,
        "active_p1_incidents": p1_count,
    }
