"""Human-in-the-loop approval for sensitive actions.

The tool only CREATES a pending request. The change is executed here, and only when the student presses
Approve in the UI (POST /api/approvals/<id>/decide). The LLM has no tool that can approve, so it can never
execute a sensitive change on its own. Each request can be decided exactly once."""
import re
import uuid
from datetime import date

import audit
import security
from database import connect

FIELDS = {"email": "email", "phone": "phone", "fee_due_date": "fee due date"}


def validate(field, value, current=None):
    """Return (clean_value, error)."""
    value = str(value).strip()
    if field == "email":
        return (value.lower(), None) if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) else (None, "Enter a valid email address.")
    if field == "phone":
        digits = re.sub(r"[\s+-]", "", value)
        return (digits, None) if re.fullmatch(r"\d{10,13}", digits) else (None, "Enter a valid phone number (10-13 digits).")
    if field == "fee_due_date":
        try:
            new = date.fromisoformat(value)
        except ValueError:
            return None, "Use the date format YYYY-MM-DD."
        if current and new <= date.fromisoformat(current):
            return None, "The new due date must be later than the current due date."
        return value, None
    return None, f"'{field}' cannot be changed through the assistant."


def _current(student_id, field, conn):
    if field == "fee_due_date":
        r = conn.execute("SELECT due_date v FROM fees WHERE student_id=?", (student_id,)).fetchone()
    else:
        r = conn.execute(f"SELECT {field} v FROM student_profile WHERE student_id=?", (student_id,)).fetchone()  # field is allow-listed
    return r["v"] if r else None


def request_change(student_id, field, new_value, db_path=None):
    """Create a pending approval. Nothing is changed yet."""
    allowed, why = security.authorize(student_id, "profile.change", student_id)
    if not allowed:
        audit.record(student_id, "profile.change", student_id, "denied", "blocked", why, db_path=db_path)
        return {"ok": False, "decision": "denied", "error": why}
    field = str(field).strip().lower()
    if field not in FIELDS:
        audit.record(student_id, "profile.change", student_id, "denied", "blocked", f"field '{field}' not allowed", db_path=db_path)
        return {"ok": False, "decision": "denied", "error": f"Only these can be changed: {', '.join(FIELDS)}."}
    conn = connect(db_path)
    old = _current(student_id, field, conn)
    clean, err = validate(field, new_value, old if field == "fee_due_date" else None)
    if err:
        conn.close()
        audit.record(student_id, "profile.change", student_id, "denied", "failed", f"{field}: {err}", db_path=db_path)
        return {"ok": False, "decision": "denied", "error": err}
    approval_id = "APR-" + uuid.uuid4().hex[:8].upper()
    with conn:
        conn.execute("INSERT INTO approvals(approval_id,student_id,field,old_value,new_value,status) VALUES(?,?,?,?,?,'pending')",
                     (approval_id, student_id, field, old, clean))
    conn.close()
    audit.record(student_id, "profile.change", student_id, "approval_required", "pending",
                 f"{field}: {security.mask(field, old)} -> {security.mask(field, clean)}", approval_id, db_path)
    return {"ok": True, "decision": "approval_required", "status": "pending_approval", "approval_id": approval_id,
            "field": FIELDS[field],
            "message": "NOT executed. The student must press Approve in the chat to confirm. Tell the student the change is waiting for their confirmation."}


def get(approval_id, db_path=None):
    conn = connect(db_path)
    r = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
    conn.close()
    return dict(r) if r else None


def list_pending(student_id, db_path=None):
    conn = connect(db_path)
    rows = conn.execute("SELECT approval_id,field,old_value,new_value,status,created_at FROM approvals "
                        "WHERE student_id=? AND status='pending' ORDER BY created_at", (student_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def decide(actor, approval_id, approve, db_path=None):
    """Approve or reject a pending request. Only the owner may decide; each request can be decided once."""
    ap = get(approval_id, db_path)
    if not ap:
        return {"ok": False, "error": "Approval request not found."}
    allowed, why = security.authorize(actor, "approval.decide", ap["student_id"])
    if not allowed:
        audit.record(actor, "approval.decide", ap["student_id"], "denied", "blocked", why, approval_id, db_path)
        return {"ok": False, "error": "You cannot decide another student's request."}
    new_status = "approved" if approve else "rejected"
    conn = connect(db_path)
    with conn:  # atomic: only a still-pending row can be decided (blocks double-click / replay)
        n = conn.execute("UPDATE approvals SET status=?, decided_at=CURRENT_TIMESTAMP, decided_by=? "
                         "WHERE approval_id=? AND status='pending'", (new_status, actor, approval_id)).rowcount
    if n == 0:
        conn.close()
        return {"ok": False, "error": f"This request was already {ap['status']}."}
    field, label = ap["field"], FIELDS.get(ap["field"], ap["field"])
    if not approve:
        conn.close()
        audit.record(actor, "profile.change", actor, "rejected", "not_executed", f"{field} change rejected", approval_id, db_path)
        return {"ok": True, "status": "rejected", "message": f"Request {approval_id} was rejected. Your {label} was not changed."}
    try:
        with conn:
            if field == "fee_due_date":
                conn.execute("UPDATE fees SET due_date=? WHERE student_id=?", (ap["new_value"], actor))
            else:
                conn.execute(f"UPDATE student_profile SET {field}=? WHERE student_id=?", (ap["new_value"], actor))  # allow-listed
            conn.execute("UPDATE approvals SET status='executed' WHERE approval_id=?", (approval_id,))
        conn.close()
    except Exception as e:
        conn.execute("UPDATE approvals SET status='failed' WHERE approval_id=?", (approval_id,)); conn.commit(); conn.close()
        audit.record(actor, "profile.change", actor, "approved", "failed", f"{field}: {type(e).__name__}", approval_id, db_path)
        return {"ok": False, "error": "The change could not be applied."}
    audit.record(actor, "profile.change", actor, "approved", "success",
                 f"{field}: {security.mask(field, ap['old_value'])} -> {security.mask(field, ap['new_value'])}", approval_id, db_path)
    return {"ok": True, "status": "executed", "message": f"Approved. Your {label} has been updated (request {approval_id})."}
