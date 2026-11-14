"""Real-Postgres checks. Every write happens inside ONE transaction that is rolled back at the end."""
import contextlib, json, sys, psycopg
sys.path.insert(0, ".")
from pgvector.psycopg import register_vector
from app import crm
from app.config import settings

conn = psycopg.connect(settings.database_url, autocommit=False)
register_vector(conn)
@contextlib.contextmanager
def txn_conn(retry=True):
    yield conn
crm.get_conn = txn_conn
R = []
def rec(id, name, expected, actual, ok): R.append(dict(id=id, name=name, expected=expected, actual=actual, result="PASS" if ok else "FAIL")); print(R[-1]["result"], id, name, "| expected:", expected, "| actual:", actual)

try:
    base = crm.get_crm_stats()
    t = crm.create_ticket("ZZ test p1", "closed p1 probe", "P1")
    s = crm.get_crm_stats(); rec("T8a", "open P1 counts as active", "+1", s["active_p1_incidents"]-base["active_p1_incidents"], s["active_p1_incidents"]-base["active_p1_incidents"]==1)
    crm.update_ticket_status(t["id"], "closed", "done")
    s = crm.get_crm_stats(); d = s["active_p1_incidents"]-base["active_p1_incidents"]
    rec("T8b", "CLOSED P1 is not an active incident", "+0", f"+{d}", d==0)
    crm.update_ticket_status(t["id"], "resolved")
    s = crm.get_crm_stats(); d = s["active_p1_incidents"]-base["active_p1_incidents"]
    rec("T8c", "resolved P1 is not active", "+0", f"+{d}", d==0)

    b2 = crm.get_crm_stats()
    for st in ("open","in_progress","resolved","closed"): crm.create_ticket(f"ZZ st {st}", "status breakdown probe", "P3", st)
    s = crm.get_crm_stats()
    dt = s["total_tickets"]-b2["total_tickets"]; parts = sum(s[k]-b2[k] for k in ("open","in_progress","resolved"))
    rec("T9", "stats parts add up to total", f"total +4 == parts +4", f"total +{dt}, parts +{parts}", dt==parts)

    crm.create_ticket("ZZ order p3","order probe aaa","P3"); crm.create_ticket("ZZ order p1","order probe bbb","P1"); crm.create_ticket("ZZ order p2","order probe ccc","P2")
    rows = [r for r in crm.list_tickets(limit=500) if r["subject"].startswith("ZZ order")]
    rec("T2", "list order P1,P2,P3", ["ZZ order p1","ZZ order p2","ZZ order p3"], [r["subject"] for r in rows], [r["subject"] for r in rows]==["ZZ order p1","ZZ order p2","ZZ order p3"])
    rec("T4", "limit=1 returns exactly 1", 1, len(crm.list_tickets(limit=1)), len(crm.list_tickets(limit=1))==1)
    crm.create_ticket("ZZ cf","filter probe row","P1","closed"); crm.create_ticket("ZZ cf2","filter probe row","P2","closed")
    f = crm.list_tickets(status="closed", priority="P1", limit=500)
    rec("T3", "combined filter returns only closed P1", "all closed+P1", len(f), len(f)>0 and all(r["status"]=="closed" and r["priority"]=="P1" for r in f))

    nasty = "x'; DROP TABLE tickets;-- %s {} \ \u00e9\U0001F600 <script>alert(1)</script>"
    t2 = crm.create_ticket(nasty, "d"*5000, "P2"); g = crm.get_ticket(t2["id"])
    rec("T10", "SQL metachars/unicode round-trip byte-for-byte; 5000-char description", "identical", "identical" if g["subject"]==nasty.strip() and len(g["description"])==5000 else g["subject"][:40], g["subject"]==nasty.strip() and len(g["description"])==5000)
    rec("T1", "created_at == updated_at on create", "equal", f"{t2['created_at']} / {t2['updated_at']}", t2["created_at"]==t2["updated_at"])
    u = crm.update_ticket_status(t2["id"], "in_progress")
    rec("T6", "PATCH bumps updated_at, keeps created_at", "updated>created", f"{u['created_at']} -> {u['updated_at']}", u["created_at"]==t2["created_at"] and u["updated_at"]>u["created_at"])
    rec("T7", "PATCH nonexistent id returns None", None, crm.update_ticket_status(2147483000, "open"), crm.update_ticket_status(2147483000, "open") is None)
    p = crm.create_ticket("ZZ prio","bad priority probe","P9")
    rec("T14", "invalid priority is rejected (API gives 422)", "error", f"stored as {p['priority']}", False)
    u2 = crm.update_ticket_status(t2["id"], "closed", "first notes"); u3 = crm.update_ticket_status(t2["id"], "open")
    rec("T5", "reopen closed ticket (allowed?)", "documented", f"status={u3['status']}, notes kept={u3['resolution_notes']!r}", u3["status"]=="open")
    rec("PATCH-notes", "PATCH without notes keeps old notes (cannot clear)", "can clear", f"notes={u3['resolution_notes']!r}", u3["resolution_notes"] is None)

    # R10: the exact history query from app/main.py against a 12-message conversation
    cid = conn.execute("INSERT INTO conversations DEFAULT VALUES RETURNING id").fetchone()[0]
    for i in range(1, 13): conn.execute("INSERT INTO messages (conversation_id, role, content) VALUES (%s,%s,%s)", (cid, "user" if i%2 else "model", f"message {i}"))
    h = conn.execute("SELECT role, content FROM messages WHERE conversation_id = %s ORDER BY id ASC LIMIT 8", (cid,)).fetchall()
    rec("R10", "history sent to model includes the latest message (12)", "message 12 in history", f"last in history = {h[-1][1]!r}", any(c=="message 12" for _,c in h))
    # FK cascade
    conn.execute("DELETE FROM conversations WHERE id=%s", (cid,))
    left = conn.execute("SELECT count(*) FROM messages WHERE conversation_id=%s", (cid,)).fetchone()[0]
    rec("FK", "deleting a conversation cascades to messages", 0, left, left==0)
    # concurrency-ish: two PATCH on separate connections cannot be tested inside one txn -> noted
    # NUL byte at DB level
    try:
        conn.execute("SELECT 1"); crm.create_ticket("ZZ nul","a\x00b nul probe","P2"); rec("NUL", "NUL byte at DB layer", "rejected", "accepted", False)
    except Exception as e:
        conn.rollback(); rec("NUL", "NUL byte at DB layer is rejected (API blocks it first)", "rejected", type(e).__name__, True)
finally:
    conn.rollback(); conn.close()
    after = psycopg.connect(settings.database_url); n = after.execute("SELECT count(*) FROM tickets WHERE subject LIKE 'ZZ %'").fetchone()[0]; after.close()
    print("leftover ZZ tickets after rollback:", n)
    json.dump(dict(results=R, leftover=n), open("reports/realdb_results.json","w"), indent=1, default=str)
