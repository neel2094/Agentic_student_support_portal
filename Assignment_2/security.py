"""Access control and input hygiene, enforced in plain Python (never by an LLM instruction).

1. authorize()      - the single permission check used by every tool and endpoint.
2. redact()         - strips OTPs, passwords, PINs, card numbers from text BEFORE it reaches the
                      model, the memory table or the trace logs.
3. other_student_referenced() - deterministic pre-screen for "show me S102's fee" style requests.
"""
import json
import re

import config
from database import connect

# action -> rules. scope "own" = the actor may only act on their own record.
# sensitive=True = must be confirmed in a separate approval step before it executes.
POLICY = {
    "fee.read":           {"scope": "own", "sensitive": False},
    "scholarship.read":   {"scope": "own", "sensitive": False},
    "ticket.create":      {"scope": "own", "sensitive": False},
    "memory.write":       {"scope": "own", "sensitive": False},
    "memory.read":        {"scope": "own", "sensitive": False},
    "profile.change":     {"scope": "own", "sensitive": True},
    "approval.decide":    {"scope": "own", "sensitive": False},
}


def authorize(actor, action, target):
    """Return (allowed, reason). Default deny: unknown actions and other students' records are refused."""
    rule = POLICY.get(action)
    if rule is None:
        return False, f"Unknown action '{action}'."
    if not actor:
        return False, "Not signed in."
    if rule["scope"] == "own" and str(target).strip().upper() != str(actor).strip().upper():
        return False, "You can only access your own record."
    return True, "ok"


def requires_approval(action):
    return bool(POLICY.get(action, {}).get("sensitive"))


# ---------------- redaction of secrets ----------------
_KW = r"(?:otp|one[\s-]?time\s+(?:password|code)|verification\s+code|password|passcode|pin|cvv|cvc|secret|token)"
_P_KEYWORD_VALUE = re.compile(rf"\b({_KW})\b\s*(?:is|was|are|=|:)\s*\S+", re.I)
_P_KEYWORD_DIGITS = re.compile(r"\b(otp|pin|cvv|cvc|code)\b[\s:=-]*\d{3,8}\b", re.I)
_P_DIGITS_KEYWORD = re.compile(r"\b\d{3,8}\b\s*(?:is|was)\s*(?:my|the)\s*(?:otp|pin|cvv|cvc|password|code)\b", re.I)
_P_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def redact(text):
    """Return (clean_text, flags). Secrets are replaced by [REDACTED]; flags name what was found."""
    flags, out = [], str(text or "")

    def kw(m):
        flags.append(m.group(1).lower())
        return f"{m.group(1)} [REDACTED]"

    def plain(label):
        def _r(m):
            flags.append(label)
            return "[REDACTED]"
        return _r

    out = _P_KEYWORD_VALUE.sub(kw, out)
    out = _P_KEYWORD_DIGITS.sub(lambda m: (flags.append(m.group(1).lower()), f"{m.group(1)} [REDACTED]")[1], out)
    out = _P_DIGITS_KEYWORD.sub(plain("otp/pin"), out)
    out = _P_CARD.sub(plain("card_number"), out)
    return out, sorted(set(flags))


def redact_history(history):
    return [{**h, "content": redact(h.get("content", ""))[0]} for h in (history or [])]


# ---------------- cross-student guardrails ----------------
REFUSAL = ("I can only help with your own student record. I cannot show, compare or change another student's "
           "information. I can help with your own fees, scholarship, policies or a support ticket.")

_DATA_WORDS = r"(?:fees?|scholarships?|balance|records?|marks|grades?|cgpa|attendance|e-?mail|phone|number|password|tickets?|details|info|information|status|address|result|paid|due|memory|profile|data)"
_THIRD_PARTY = (r"(?:another|other|someone\s+else|somebody\s+else|classmates?|class\s*mates?|friends?|roommates?|room\s*mates?|"
                r"batch\s*mates?|seniors?|juniors?|everyone|everybody|all\s+(?:the\s+)?students|every\s+student|each\s+student|"
                r"top\s+students?|toppers?|students?\s+list|list\s+of\s+students|(?:his|her|their)\s+(?:fees?|scholarship|record|balance|details))")
_P_THIRD_PARTY = re.compile(rf"\b{_THIRD_PARTY}\b", re.I)
_P_DATA = re.compile(rf"\b{_DATA_WORDS}\b", re.I)
_P_ID_TOKEN = re.compile(r"\bS\s?-?\s?(\d{3})\b", re.I)                       # S102, s 102, S-102
_P_ID_WORDS = re.compile(r"\b(?:student|roll|id|enrol\w*|reg\w*)\s*(?:no\.?|number|#)?\s*:?\s*#?(\d{3})\b", re.I)  # "student 102", "roll no 102"


def _people(db_path=None):
    conn = connect(db_path)
    rows = conn.execute("SELECT s.student_id, s.name, p.email, p.phone FROM students s "
                        "LEFT JOIN student_profile p USING(student_id)").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _first(name):
    return (name or "").split()[0] if name else ""


def other_student_referenced(text, actor, db_path=None):
    """Input guard. Return a short reason string if the message asks about someone other than the signed-in student, else None.
    Catches: any other student id (S102, s 102, 'student 102'), full or FIRST names, and third-party wording
    ('my roommate's fee', 'everyone's scholarship', 'list all students') when combined with a data word."""
    text = re.sub(r"\S+@\S+", " ", str(text or ""))  # an email being typed (e.g. priya.new@x.com) is not a reference to a person
    try:
        people = _people(db_path)
    except Exception:
        return None
    me = next((p for p in people if p["student_id"].upper() == str(actor).upper()), None)
    my_first = _first(me["name"]).lower() if me else ""
    for m in list(_P_ID_TOKEN.finditer(text)) + list(_P_ID_WORDS.finditer(text)):
        sid = "S" + m.group(m.lastindex)
        if sid.upper() != str(actor).upper():
            return sid
    for p in people:
        if p["student_id"].upper() == str(actor).upper():
            continue
        first = _first(p["name"])
        if re.search(rf"\b{re.escape(p['name'])}\b", text, re.I) or (first and first.lower() != my_first and re.search(rf"\b{re.escape(first)}\b", text, re.I)):
            return p["student_id"]
    if _P_THIRD_PARTY.search(text) and _P_DATA.search(text):
        return "third_party"
    return None


def leaks_other_student(answer, actor, db_path=None):
    """Output guard. True if the model's answer contains another student's id, name, first name, email or phone."""
    answer = str(answer or "")
    try:
        people = _people(db_path)
    except Exception:
        return False
    me = next((p for p in people if p["student_id"].upper() == str(actor).upper()), None)
    my_first = _first(me["name"]).lower() if me else ""
    for p in people:
        if p["student_id"].upper() == str(actor).upper():
            continue
        first = _first(p["name"])
        if re.search(rf"\b{re.escape(p['student_id'])}\b", answer, re.I) or re.search(rf"\b{re.escape(p['name'])}\b", answer, re.I):
            return True
        if first and first.lower() != my_first and re.search(rf"\b{re.escape(first)}\b", answer, re.I):
            return True
        for v in (p.get("email"), p.get("phone")):
            if v and v in answer:
                return True
    return False


def mask(field, value):
    """Short masked form of a value for audit records."""
    v = str(value)
    if field == "phone":
        return "*" * max(len(v) - 4, 0) + v[-4:]
    if field == "email" and "@" in v:
        return v[0] + "***@" + v.split("@", 1)[1]
    return v


def to_json(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)
