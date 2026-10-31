"""Persistent memory in SQLite. Only explicit, non-sensitive facts are stored."""
import re
from database import connect

# Conservative block-list: never store secrets or payment details.
SENSITIVE = re.compile(r"password|passcode|\botp\b|\bpin\b|cvv|card|account\s*number|secret|token|\b\d{9,}\b", re.I)


def save_memory(student_id, key, value, db_path=None):
    if SENSITIVE.search(f"{key} {value}"):
        return {"ok": False, "error": "Sensitive information cannot be saved to memory."}
    conn = connect(db_path)
    with conn:  # one row per (student, key) -> updates instead of duplicates
        conn.execute(
            "INSERT INTO memory(student_id,key,value) VALUES(?,?,?) "
            "ON CONFLICT(student_id,key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            (student_id, key, value))
        row = conn.execute("SELECT memory_id FROM memory WHERE student_id=? AND key=?", (student_id, key)).fetchone()
        mid = row["memory_id"] if row else None
    conn.close()
    return {"ok": True, "memory_id": mid, "key": key, "value": value}


def list_memory(student_id, db_path=None):
    conn = connect(db_path)
    rows = conn.execute("SELECT memory_id,key,value FROM memory WHERE student_id=?", (student_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_memory(student_id, memory_id, db_path=None):
    conn = connect(db_path)
    with conn:  # student_id in WHERE: you can only delete your own rows
        n = conn.execute("DELETE FROM memory WHERE memory_id=? AND student_id=?", (memory_id, student_id)).rowcount
    conn.close()
    return n > 0


def clear_memory(student_id, db_path=None):
    conn = connect(db_path)
    with conn:
        conn.execute("DELETE FROM memory WHERE student_id=?", (student_id,))
    conn.close()
