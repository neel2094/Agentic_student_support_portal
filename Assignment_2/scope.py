"""Scope guard: the assistant may answer ONLY from the data source (handbook via search_policy, the signed-in
student's own records via tools, and that student's saved memory). Anything else (general knowledge, people,
news, coding, maths ...) is refused. Enforced in Python after the model answers, so a model that "knows" the
answer from its training data still cannot show it."""
import re

import config
from retrieval import STOP, load_chunks, tokenize

OUT_OF_SCOPE = ("I'm sorry, I can only answer questions that are covered by the student handbook or your own student "
                "records (fees, scholarship, tickets, saved preferences). This is not covered there, so I cannot answer it. "
                "I can create a support ticket if you'd like someone from Student Services to help.")

# Small talk / preferences that legitimately need no data source.
_SMALL_TALK = re.compile(
    r"^\s*(hi|hii+|hello|hey|good\s+(morning|afternoon|evening)|thanks?|thank\s+you|ok(ay)?|yes|yep|yeah|no|nope|sure|bye|goodbye|cool|great|please)\b", re.I)
_ABOUT_ASSISTANT = re.compile(r"\b(who\s+are\s+you|what\s+can\s+you\s+(do|help)|how\s+can\s+you\s+help|what\s+do\s+you\s+do)\b", re.I)
_STYLE = re.compile(r"\b(keep\s+(it|answers?|replies|responses?)\s+(short|brief)|in\s+a\s+hurry|be\s+(brief|concise)|shorter|briefly)\b", re.I)
_MEMORY = re.compile(r"\b(remember|remind|saved|what\s+did\s+i\s+(say|tell|ask)|my\s+(programme|program|hostel|room|language|career)|what\s+do\s+you\s+know\s+about\s+me)\b", re.I)


def is_exempt(question, has_memory=False, redacted=False):
    """True if no data-source evidence is needed for this message."""
    q = str(question or "")
    if redacted:                                  # secret was removed; the reply is just a refusal to store it
        return True
    if len(q.split()) <= 6 and _SMALL_TALK.search(q):
        return True
    if _ABOUT_ASSISTANT.search(q) or _STYLE.search(q):
        return True
    if _MEMORY.search(q) and has_memory:
        return True
    return False


# Words that carry no topic ("who is", "tell me about", "explain" ...). They must not count as handbook matches,
# because BM25 happily returns weak chunks for them (e.g. "who is X" matched the exam re-evaluation section).
_GENERIC = set("who whom whose which where why tell about give explain describe please me us you your define meaning "
               "know say show find get need want like could would should will does did has have had any some more most "
               "there their they them this that these those than then also just only very much many other".split())
# Domain words that are always in scope even if a given handbook revision does not repeat them.
_DOMAIN = set("fee fees scholarship scholarships ticket tickets attendance hostel library exam exams grade grades cgpa course courses "
              "payment portal deadline deadlines policy rule rules college student students programme program refund leave "
              "memory email phone due balance support approval".split())
_vocab_cache = None


def vocabulary():
    """Every word that appears in the handbook (plus a few fixed domain words). Built once from data/student_policy.txt."""
    global _vocab_cache
    if _vocab_cache is None:
        v = set(_DOMAIN)
        for c in load_chunks():
            v.update(tokenize(c["title"] + " " + c["text"]))
        _vocab_cache = v - _GENERIC
    return _vocab_cache


def question_in_domain(question, history=None):
    """True if at least half of the question's topic words exist in the handbook vocabulary (or the recent chat).
    'who is narendra modi' -> narendra, modi are unknown -> False. 'late fee after due date' -> True."""
    vocab = set(vocabulary())
    for h in (history or [])[-4:]:                      # follow-ups like 'and the deadline?' may reuse earlier words
        vocab.update(tokenize(str(h.get("content", ""))))
    words = [w for w in tokenize(question) if w not in STOP and w not in _GENERIC and not w.isdigit()]
    if not words:
        return False
    known = sum(1 for w in words if w in vocab)
    return known / len(words) >= 0.5 and known >= 1


def is_grounded(called, evidence, question="", history=None):
    """True if this run produced usable evidence from the data source:
    - a record / memory / ticket / approval tool was used, or
    - handbook chunks were retrieved AND the question really is about the handbook's subject matter.
    Weak BM25 hits for an off-topic question (e.g. 'who is <public figure>') do not count."""
    if any(t["name"] != "search_policy" for t in (called or [])):
        return True
    return bool(evidence) and question_in_domain(question, history)