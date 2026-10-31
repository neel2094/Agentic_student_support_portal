"""The agent loop: LLM -> tool calls -> tool results -> LLM ... -> final answer."""
import hashlib
import time
import config
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from context_manager import build_context
from schemas import AgentResult
from tools import make_tools
from tracing import current_trace_id, log_run, tag_run, traceable


_cached_llm = None


def get_llm():
    global _cached_llm
    if _cached_llm is None:
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is missing. Copy .env.example to .env and set it.")
        from langchain_groq import ChatGroq
        _cached_llm = ChatGroq(
            model=config.GROQ_MODEL, 
            api_key=config.GROQ_API_KEY, 
            temperature=0,
            max_tokens=1024,
            timeout=60,
            max_retries=2
        )
    return _cached_llm


def run_agent(question, student_id, history=None, session_id="default", llm=None, db_path=None, max_steps=None):
    """Public entry point."""
    return _run(question, student_id, history or [], session_id, llm, db_path, max_steps)


def _trace_inputs(inputs):
    """What LangSmith records as this run's input: the question and a hashed student id only."""
    sid = str(inputs.get("student_id", ""))
    return {"question": inputs.get("question"), "student": hashlib.sha256(sid.encode()).hexdigest()[:8],
            "session_id": inputs.get("session_id")}


def generate_followup_questions(question, answer, tools_called, chunks):
    """Return 2 to 3 high-precision follow-up questions that are 100% answerable properly."""
    tool_names = {t["name"] for t in (tools_called or [])}
    chunk_titles = {c.get("title", "") for c in (chunks or [])}
    q_lower = (question or "").lower()

    candidates = []
    if "get_fee_status" in tool_names or "fee" in q_lower or "Fee Payment Deadlines" in chunk_titles or "Late Payment Procedure" in chunk_titles:
        candidates.extend([
            "What is the late fee if I pay after the due date?",
            "Can I pay my tuition fee in installments?",
            "What should I do if the payment portal crashes?",
        ])
    if "check_scholarship_status" in tool_names or "scholarship" in q_lower or "Scholarship Eligibility" in chunk_titles or "Scholarship Application Procedure" in chunk_titles:
        candidates.extend([
            "What are the Merit scholarship criteria?",
            "How do I apply for a scholarship?",
            "What is the scholarship application deadline?",
        ])
    if "Payment Portal Failure" in chunk_titles or "portal" in q_lower:
        candidates.extend([
            "The payment portal failed. Can I pay on the next working day?",
            "How long does the support team take to reply to a ticket?",
            "My ticket was not answered, who do I escalate to?",
        ])
    if "Course Change Requests" in chunk_titles or "course" in q_lower:
        candidates.extend([
            "Who has to approve a course change request?",
            "What is the deadline for course change requests?",
        ])
    if "Attendance Policy and Minimum Requirements" in chunk_titles or "attendance" in q_lower or "leave" in q_lower:
        candidates.extend([
            "What is the minimum attendance requirement?",
            "What is the medical leave policy for attendance?",
            "What counts as a working day?",
        ])
    if "Grading System and CGPA Calculation" in chunk_titles or "grade" in q_lower or "cgpa" in q_lower or "exam" in q_lower:
        candidates.extend([
            "How is CGPA calculated on the 10-point scale?",
            "What is the procedure for exam re-evaluation?",
            "What are the examination hall rules?",
        ])
    if "Hostel Regulations and Curfew Guidelines" in chunk_titles or "hostel" in q_lower or "curfew" in q_lower:
        candidates.extend([
            "What are the hostel curfew hours and night pass rules?",
            "What are the Central Library operating hours and book borrowing limits?",
        ])
    if "save_memory" in tool_names or "get_saved_memory" in tool_names or "remember" in q_lower or "memory" in q_lower or "profile" in q_lower:
        candidates.extend([
            "What facts do you have saved in my personalized memory?",
            "Can you customize your advice based on my saved programme?",
            "How do I clear or update my saved memory?",
        ])

    defaults = [
        "What is my fee balance?",
        "What is my scholarship status?",
        "What is the minimum attendance requirement?",
        "What is the definition of a working day?",
        "What are the Merit scholarship criteria?",
        "Who has to approve a course change request?",
    ]
    for d in defaults:
        if d not in candidates:
            candidates.append(d)

    result = []
    for c in candidates:
        if c.lower().strip("?. ") != q_lower.strip("?. ") and c not in result:
            result.append(c)
        if len(result) >= 3:
            break
    return result


@traceable(name="student_support_agent", run_type="chain", process_inputs=_trace_inputs)
def _run(question, student_id, history=None, session_id="default", llm=None, db_path=None, max_steps=None):
    """student_id comes from the app's login - never from the message text."""
    tag_run(session_id=session_id, student=hashlib.sha256(student_id.encode()).hexdigest()[:8])
    t0 = time.perf_counter()
    max_steps = max_steps or config.MAX_STEPS
    evidence, called, mem_ids = [], [], []

    llm_time, in_tok, out_tok = 0.0, None, None
    try:
        llm = llm or get_llm()
        tools = make_tools(student_id, db_path, evidence)
        registry = {t.name: t for t in tools}  # strict allow-list
        model = llm.bind_tools(tools)
        system, recent, cats, mem_ids = build_context(student_id, history or [], db_path)
        msgs = [SystemMessage(system)] + [
            (HumanMessage if r["role"] == "user" else AIMessage)(r["content"]) for r in recent
        ] + [HumanMessage(question)]

        answer = None
        for _ in range(max_steps):
            t1 = time.perf_counter()
            try:
                ai = model.invoke(msgs)
            except Exception:  # Groq sometimes returns a malformed tool call or a brief outage: retry once
                ai = model.invoke(msgs)
            llm_time += time.perf_counter() - t1
            u = getattr(ai, "usage_metadata", None)
            if u:
                in_tok = (in_tok or 0) + u.get("input_tokens", 0)
                out_tok = (out_tok or 0) + u.get("output_tokens", 0)
            msgs.append(ai)
            if not ai.tool_calls:
                answer = ai.content if isinstance(ai.content, str) else str(ai.content)
                answer = answer.strip() or None
                if answer is None:
                    answer = "I could not form an answer. Please rephrase your question or create a support ticket."
                break
            for call in ai.tool_calls:
                tool = registry.get(call["name"])
                if tool is None:  # unknown tool -> controlled error
                    result = {"ok": False, "error": f"Unknown tool '{call['name']}'."}
                else:
                    try:
                        result = tool.invoke(call["args"])
                    except Exception as e:  # malformed arguments etc.
                        result = {"ok": False, "error": f"Bad tool call: {type(e).__name__}"}
                called.append({"name": call["name"], "args": call["args"], "ok": bool(result.get("ok"))})
                msgs.append(ToolMessage(str(result), tool_call_id=call["id"]))
                if call["name"] == "save_memory" and result.get("ok") and result.get("memory_id"):
                    if result["memory_id"] not in mem_ids:
                        mem_ids.append(result["memory_id"])
                elif call["name"] == "get_saved_memory" and result.get("ok"):
                    for m in result.get("memories", []):
                        if m.get("memory_id") and m["memory_id"] not in mem_ids:
                            mem_ids.append(m["memory_id"])
        if answer is None:
            answer = "Sorry, I could not finish this request. Please rephrase it or create a support ticket."
            error = "max_steps_reached"
        else:
            error = None
    except RuntimeError as e:  # configuration problem (missing GROQ_API_KEY)
        answer, error = "The assistant is not set up yet: the administrator must add the Groq API key.", str(e)
    except Exception as e:
        answer, error = "Sorry, something went wrong. Please try again in a moment.", f"{type(e).__name__}: {e}"

    followups = generate_followup_questions(question, answer, called, evidence) if not error else []
    result = AgentResult(answer=answer, tools_called=called, chunks=evidence, memory_used=mem_ids,
                         llm_seconds=round(llm_time, 3), total_seconds=round(time.perf_counter() - t0, 3),
                         input_tokens=in_tok, output_tokens=out_tok, trace_id=current_trace_id(), error=error,
                         suggested_questions=followups)
    return _finish(result, question, student_id, session_id)


def _finish(result, question, student_id, session_id):
    """Write the local structured trace line (no question text) and return the result."""
    log_run({"session": session_id, "student": hashlib.sha256(student_id.encode()).hexdigest()[:8],
             "question_chars": len(question), "tools": [(t["name"], t["ok"]) for t in result.tools_called],
             "chunk_ids": [c["id"] for c in result.chunks], "chunk_scores": [c["score"] for c in result.chunks],
             "memory_ids": result.memory_used, "llm_s": result.llm_seconds, "total_s": result.total_seconds,
             "in_tokens": result.input_tokens, "out_tokens": result.output_tokens, "error": result.error,
             "langsmith_trace": result.trace_id})
    return result
