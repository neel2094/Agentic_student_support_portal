"""Audit trail in SQLite (table audit_log). One row per important action:
who asked (actor), what was attempted (action/target/detail), whether it was allowed or approved (decision),
and the final result. Secrets are never written here; details are masked or omitted. Never raises."""
from database import connect

# decision: allowed | denied | approval_required | approved | rejected | redacted
# result:   success | failed | blocked | not_executed | pending | not_stored


def record(actor, action, target, decision, result, detail="", approval_id=None, db_path=None):
    try:
        conn = connect(db_path)
        with conn:
            conn.execute(
                "INSERT INTO audit_log(actor,action,target,decision,result,detail,approval_id) VALUES(?,?,?,?,?,?,?)",
                (actor, action, str(target), decision, result, str(detail)[:300], approval_id))
        conn.close()
    except Exception:
        pass


def list_audit(actor=None, limit=50, db_path=None):
    conn = connect(db_path)
    q, args = "SELECT audit_id,ts,actor,action,target,decision,result,detail,approval_id FROM audit_log", []
    if actor:
        q += " WHERE actor=?"
        args.append(actor)
    rows = conn.execute(q + " ORDER BY audit_id DESC LIMIT ?", (*args, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
