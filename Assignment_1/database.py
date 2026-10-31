"""SQLite setup. All queries elsewhere use ? parameters (no string-built SQL)."""
import json
import sqlite3
import config
from werkzeug.security import generate_password_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS students(student_id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fees(student_id TEXT PRIMARY KEY REFERENCES students(student_id),
    fee_total INTEGER NOT NULL, fee_paid INTEGER NOT NULL, due_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS scholarships(student_id TEXT PRIMARY KEY REFERENCES students(student_id),
    status TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS tickets(ticket_id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(student_id),
    category TEXT NOT NULL, description TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS memory(memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL REFERENCES students(student_id), key TEXT NOT NULL, value TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(student_id, key));
CREATE TABLE IF NOT EXISTS credentials(student_id TEXT PRIMARY KEY REFERENCES students(student_id), password_hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_mem ON memory(student_id);
"""


def connect(db_path=None):
    conn = sqlite3.connect(db_path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None, reset=False):
    """Create tables and seed fictional students. Existing data is kept unless reset=True."""
    conn = connect(db_path)
    with conn:
        if reset:
            for t in ("credentials", "memory", "tickets", "scholarships", "fees", "students"):
                conn.execute(f"DROP TABLE IF EXISTS {t}")  # fixed names, not user input
        conn.executescript(SCHEMA)
        for s in json.loads(config.STUDENTS_JSON.read_text()):
            conn.execute("INSERT INTO students VALUES(?,?) ON CONFLICT(student_id) DO UPDATE SET name=excluded.name",
                         (s["student_id"], s["name"]))
            conn.execute("INSERT OR IGNORE INTO fees VALUES(?,?,?,?)",
                         (s["student_id"], s["fee_total"], s["fee_paid"], s["due_date"]))
            conn.execute("INSERT OR IGNORE INTO scholarships VALUES(?,?,?)",
                         (s["student_id"], s["scholarship_status"], s["scholarship_detail"]))
            # only the salted hash is stored, never the password itself
            conn.execute("INSERT INTO credentials VALUES(?,?) ON CONFLICT(student_id) DO UPDATE SET password_hash=excluded.password_hash",
                         (s["student_id"], generate_password_hash(s["password"])))  # demo seed only
    conn.close()


def list_students(db_path=None):
    conn = connect(db_path)
    rows = conn.execute("SELECT student_id, name FROM students ORDER BY student_id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def verify_login(student_id, password, db_path=None):
    """True only if the id exists and the password matches the stored hash."""
    from werkzeug.security import check_password_hash
    conn = connect(db_path)
    row = conn.execute("SELECT password_hash FROM credentials WHERE student_id=?", (student_id,)).fetchone()
    conn.close()
    return bool(row) and check_password_hash(row["password_hash"], password)


def student_name(student_id, db_path=None):
    conn = connect(db_path)
    row = conn.execute("SELECT name FROM students WHERE student_id=?", (student_id,)).fetchone()
    conn.close()
    return row["name"] if row else None
