"""Flask backend with student portal and trace-based evaluator dashboard."""
import json
import time
from collections import Counter
from functools import wraps
from pathlib import Path

import approvals
import audit
import config
import database
import memory
from agent import run_agent
from flask import Flask, jsonify, request, session

app = Flask(__name__, static_folder="static", static_url_path="")
app.config.update(SECRET_KEY=config.SECRET_KEY, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
database.init_db()
FAILS = {}
START_TIME = time.time()


def student_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("student"):
            return jsonify(error="Please log in first."), 401
        return f(session["student"], *a, **kw)
    return wrapper


def _safe_num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_traces():
    path = Path(config.LOG_PATH)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
            except json.JSONDecodeError:
                continue
    return rows


def _trace_payload(rows):
    tool_counter, failed_tool_counter = Counter(), Counter()
    tool_calls = successful_tools = failed_tools = 0
    retrieval_runs = chunks_retrieved = errors = 0
    in_tokens = out_tokens = 0
    total_times, llm_times = [], []

    normalized = []
    for index, row in enumerate(rows, start=1):
        tools = row.get("tools") or []
        clean_tools = []
        for tool in tools:
            if not isinstance(tool, (list, tuple)) or not tool:
                continue
            name = str(tool[0])
            ok = bool(tool[1]) if len(tool) > 1 else False
            tool_calls += 1
            tool_counter[name] += 1
            if ok:
                successful_tools += 1
            else:
                failed_tools += 1
                failed_tool_counter[name] += 1
            clean_tools.append({"name": name, "ok": ok})

        chunks = row.get("chunk_ids") or []
        scores = row.get("chunk_scores") or []
        if chunks:
            retrieval_runs += 1
            chunks_retrieved += len(chunks)

        i_tok = int(_safe_num(row.get("in_tokens")))
        o_tok = int(_safe_num(row.get("out_tokens")))
        total = _safe_num(row.get("total_s"))
        llm = _safe_num(row.get("llm_s"))
        in_tokens += i_tok
        out_tokens += o_tok
        if total >= 0: total_times.append(total)
        if llm >= 0: llm_times.append(llm)
        if row.get("error"): errors += 1

        normalized.append({
            "id": index,
            "ts": row.get("ts"),
            "session": row.get("session"),
            "student": row.get("student"),
            "question_chars": row.get("question_chars", 0),
            "tools": clean_tools,
            "chunk_ids": chunks,
            "chunk_scores": scores,
            "memory_ids": row.get("memory_ids") or [],
            "llm_s": llm,
            "total_s": total,
            "in_tokens": i_tok,
            "out_tokens": o_tok,
            "total_tokens": i_tok + o_tok,
            "error": row.get("error"),
            "langsmith_trace": row.get("langsmith_trace")
        })

    runs = len(normalized)
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "agent_runs": runs,
            "sessions": len({r.get("session") for r in normalized if r.get("session")}),
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "total_tokens": in_tokens + out_tokens,
            "tool_calls": tool_calls,
            "successful_tool_calls": successful_tools,
            "failed_tool_calls": failed_tools,
            "tool_success_rate": round((successful_tools / tool_calls * 100), 1) if tool_calls else 0,
            "retrieval_runs": retrieval_runs,
            "chunks_retrieved": chunks_retrieved,
            "avg_chunks_per_retrieval": round(chunks_retrieved / retrieval_runs, 2) if retrieval_runs else 0,
            "errors": errors,
            "error_rate": round((errors / runs * 100), 1) if runs else 0,
            "avg_total_s": round(sum(total_times) / len(total_times), 3) if total_times else 0,
            "avg_llm_s": round(sum(llm_times) / len(llm_times), 3) if llm_times else 0,
            "avg_overhead_s": round((sum(total_times)/len(total_times) if total_times else 0) - (sum(llm_times)/len(llm_times) if llm_times else 0), 3)
        },
        "tools": [{"name": n, "calls": c, "failed": failed_tool_counter[n], "success": c-failed_tool_counter[n]} for n,c in tool_counter.most_common()],
        "runs": list(reversed(normalized))
    }


@app.get("/health")
@app.get("/api/health")
def health_check():
    return jsonify(status="ok", uptime_seconds=int(time.time()-START_TIME), service="student-support-portal"), 200

@app.get("/")
def index(): return app.send_static_file("index.html")

@app.get("/evaluator")
def evaluator(): return app.send_static_file("dashboard/index.html")

@app.get("/api/evaluator")
def evaluator_data():
    return jsonify(_trace_payload(_read_traces()))

@app.post("/api/login")
def login():
    d=request.get_json(silent=True) or {}
    uid,pw=str(d.get("student_id","")).strip().upper(),str(d.get("password",""))
    key=(request.remote_addr,uid); count,locked=FAILS.get(key,[0,0])
    if time.time()<locked: return jsonify(error="Too many attempts. Try again in a minute."),429
    if not database.verify_login(uid,pw):
        count+=1; FAILS[key]=[count,time.time()+60 if count>=5 else 0]
        return jsonify(error="Wrong ID or password."),401
    FAILS.pop(key,None); session.clear(); session["student"]=uid
    return jsonify(ok=True,student=uid,name=database.student_name(uid))

@app.post("/api/logout")
def logout(): session.clear(); return jsonify(ok=True)

@app.get("/api/me")
def me():
    sid=session.get("student")
    return jsonify(student=sid,name=database.student_name(sid) if sid else None)

@app.post("/api/chat")
@student_required
def chat(sid):
    d=request.get_json(silent=True) or {}; msg=(d.get("message") or "").strip()
    if not msg: return jsonify(error="Type a message."),400
    raw=d.get("history",[]); raw=raw if isinstance(raw,list) else []
    history=[{"role":h["role"],"content":str(h.get("content",""))[:2000]} for h in raw[-12:] if isinstance(h,dict) and h.get("role") in ("user","assistant")]
    return jsonify(run_agent(msg[:1000],sid,history,d.get("session_id","web")).model_dump())

@app.get("/api/approvals")
@student_required
def pending_approvals(sid): return jsonify(approvals.list_pending(sid))

@app.post("/api/approvals/<approval_id>/decide")
@student_required
def decide_approval(sid, approval_id):
    """The only code path that can execute a sensitive change. Called by the Approve / Reject buttons, never by the LLM."""
    d=request.get_json(silent=True) or {}; choice=str(d.get("decision","")).lower()
    if choice not in ("approve","reject"): return jsonify(error="decision must be 'approve' or 'reject'."),400
    r=approvals.decide(sid,approval_id,choice=="approve")
    return jsonify(r),(200 if r.get("ok") else 403 if "another" in r.get("error","") else 409)

@app.get("/api/audit")
@student_required
def my_audit(sid): return jsonify(audit.list_audit(sid, 50))

@app.get("/api/memory")
@student_required
def get_memory(sid): return jsonify(memory.list_memory(sid))

@app.post("/api/memory")
@student_required
def add_memory(sid):
    d=request.get_json(silent=True) or {}; key=str(d.get("key","")).strip()[:50]; val=str(d.get("value","")).strip()[:150]
    if not key or not val: return jsonify(error="Key and value are required."),400
    r=memory.save_memory(sid,key,val); return jsonify(r),(200 if r.get("ok") else 400)

@app.delete("/api/memory/<int:mid>")
@student_required
def del_memory(sid,mid): return jsonify(ok=memory.delete_memory(sid,mid))

@app.delete("/api/memory")
@student_required
def clear_all_memory(sid): memory.clear_memory(sid); return jsonify(ok=True)

if __name__ == "__main__":
    import os
    import threading
    import webbrowser

    host = "127.0.0.1"
    port = int(os.environ.get("PORT", 5000))

    main_url = f"http://{host}:{port}"
    # dashboard_url = f"http://{host}:{port}/evaluator"

    print("=" * 60)
    print(f"Student Portal : {main_url}")
    # print(f"Evaluator      : {dashboard_url}")
    print("=" * 60)

    def open_pages():
        webbrowser.open(main_url)
        # webbrowser.open_new_tab(dashboard_url)

    threading.Timer(2, open_pages).start()

    try:
        from waitress import serve

        print(f"Running Waitress on {host}:{port}")
        serve(app, host=host, port=port, threads=4)

    except ImportError:
        print(f"Running Flask on {host}:{port}")
        app.run(host=host, port=port, debug=False)