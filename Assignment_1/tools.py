"""LangChain tools. They are built per student: the student_id is bound here in Python,
so the LLM can never choose (or be tricked into choosing) another student's id."""
import re
import uuid
from langchain_core.tools import tool
from pydantic import ValidationError

import memory
from database import connect
from retrieval import BM25, load_chunks
from schemas import MemoryInput, TicketInput

_bm25 = None
# the model may phrase the category loosely; map common wordings to the allowed values
ALIASES = {"payment_portal": "portal", "portal_failure": "portal", "payment": "fee", "fees": "fee", "fee_payment": "fee",
           "scholarships": "scholarship", "course": "course_change", "course_change_request": "course_change",
           "course_changes": "course_change", "general": "other", "others": "other"}

MEMORY_ALIASES = {
    "program": "programme", "academic_program": "programme", "major": "programme", "degree": "programme",
    "lang": "language", "preferred_language": "language", "mother_tongue": "language",
    "pref": "preference", "timing": "timing_preference", "mode": "study_mode",
    "room": "hostel_room", "room_no": "hostel_room", "room_number": "hostel_room",
    "hostel_name": "hostel", "dorm": "hostel",
    "goal": "career_goal", "ambition": "career_goal",
}


def get_bm25():
    global _bm25
    if _bm25 is None:
        _bm25 = BM25(load_chunks())
    return _bm25


def fee_status(student_id, db_path=None):
    try:
        conn = connect(db_path)
        r = conn.execute("SELECT fee_total,fee_paid,due_date FROM fees WHERE student_id=?", (student_id,)).fetchone()
        conn.close()
    except Exception as e:
        return {"ok": False, "error": f"Database error: {e}"}
    if not r:
        return {"ok": False, "error": "No fee record found."}
    paid, total = r["fee_paid"], r["fee_total"]
    return {"ok": True, "total": total, "paid": paid, "outstanding": total - paid, "due_date": r["due_date"],
            "status": "paid" if paid >= total else "partially paid" if paid else "unpaid"}


def scholarship_status(student_id, db_path=None):
    try:
        conn = connect(db_path)
        r = conn.execute("SELECT status,detail FROM scholarships WHERE student_id=?", (student_id,)).fetchone()
        conn.close()
    except Exception as e:
        return {"ok": False, "error": f"Database error: {e}"}
    if not r:
        return {"ok": False, "error": "No scholarship record found."}
    return {"ok": True, "status": r["status"], "detail": r["detail"]}


def new_ticket(student_id, category, description, db_path=None):
    norm = re.sub(r"[\s-]+", "_", str(category).strip().lower())
    category = ALIASES.get(norm, norm)  # "Payment Portal" -> portal, "course change" -> course_change
    try:
        data = TicketInput(category=category, description=str(description).strip())  # validate
    except ValidationError:
        return {"ok": False, "error": "Invalid ticket: use a valid category and a 5-300 character description."}
    ticket_id = "TCK-" + uuid.uuid4().hex[:8].upper()
    try:
        conn = connect(db_path)
        with conn:  # commit happens when this block ends
            conn.execute("INSERT INTO tickets(ticket_id,student_id,category,description) VALUES(?,?,?,?)",
                         (ticket_id, student_id, data.category, data.description))
        conn.close()
    except Exception as e:
        return {"ok": False, "error": f"Ticket was NOT created: {e}"}
    return {"ok": True, "ticket_id": ticket_id}


def make_tools(student_id, db_path=None, evidence=None):
    """Return the tools for ONE signed-in student.
    The student_id is bound here in Python (the model never supplies it), so a tool can only touch that student's record.
    `evidence` collects retrieved policy chunks for the trace/UI."""
    evidence = evidence if evidence is not None else []

    @tool
    def get_fee_status() -> dict:
        """Get the logged-in student's fee status: total, paid, outstanding balance, due date."""
        return fee_status(student_id, db_path)

    @tool
    def check_scholarship_status() -> dict:
        """Get the logged-in student's scholarship status and details."""
        return scholarship_status(student_id, db_path)

    @tool
    def create_support_ticket(category: str, description: str) -> dict:
        """Create a support ticket. category: fee, scholarship, course_change, portal or other."""
        return new_ticket(student_id, category, description, db_path)

    @tool
    def search_policy(query: str) -> dict:
        """Search the student handbook for policy rules. Use for any policy/procedure question."""
        hits = get_bm25().search(query)
        evidence.extend(hits)
        if not hits:
            return {"ok": True, "chunks": [], "note": "No relevant policy found. Do not guess."}
        return {"ok": True, "chunks": [{"id": h["id"], "title": h["title"], "text": h["text"]} for h in hits]}

    @tool
    def save_memory(key: str, value: str) -> dict:
        """Save a personalized fact, preference, personal detail, or context discussed by the student.
        Use this whenever the student discusses their personal details (programme, major, year, hostel, room,
        language, career interest, study habits, specific situation) or asks you to remember something.
        key: descriptive snake_case key (e.g. programme, hostel, hostel_room, language, career_goal, preference).
        value: the fact to remember (up to 150 characters)."""
        norm_key = re.sub(r"[^a-zA-Z0-9_]+", "_", str(key).strip().lower()).strip("_")
        norm_key = MEMORY_ALIASES.get(norm_key, norm_key or "preference")
        try:
            m = MemoryInput(key=norm_key, value=str(value).strip())
        except ValidationError:
            return {"ok": False, "error": "Invalid memory input."}
        return memory.save_memory(student_id, m.key, m.value, db_path)

    @tool
    def get_saved_memory() -> dict:
        """Retrieve all personalized facts, preferences, and profile details saved in memory for the logged-in student."""
        rows = memory.list_memory(student_id, db_path)
        return {"ok": True, "memories": [{k: x[k] for k in ("memory_id", "key", "value")} for x in rows]}

    return [get_fee_status, check_scholarship_status, create_support_ticket, search_policy,
            save_memory, get_saved_memory]
