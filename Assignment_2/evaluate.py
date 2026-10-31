"""Evaluation runner (Assignments 1 + 2).  Run:  python evaluate.py
 A. Policy retrieval tests              (no API key needed)
 B. Agent tests with the real Groq model (needs GROQ_API_KEY): the 13 test questions T01-T13 in data/test_cases.json
Pass/fail is decided in Python (tool called? facts present? forbidden text absent? memory in SQLite correct?).
Nothing is hardcoded: every number comes from this run.
Output: reports/evaluation.md plus reports/evaluation_retrieval.csv and reports/evaluation_agent.csv.
C. Assignment 2 privacy / approval / audit tests P01-P08 (data/test_cases_a2.json), checked against the audit_log table
D. Comparison with the Assignment 1 baseline in reports/baseline_a1/evaluation_agent.csv"""
import csv
import json
import re
import tempfile
import time
from pathlib import Path

import approvals
import audit
import config
import database
import memory
from agent import run_agent
from retrieval import BM25, load_chunks

REPORTS = config.ROOT / "reports"
DATA = config.ROOT / "data"


def write_csv(name, rows):
    with open(REPORTS / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)


def num(rows, key):
    v = []
    for r in rows:
        try:
            v.append(float(r[key]))
        except (TypeError, ValueError):
            pass
    return v


def avg(rows, key, nd=2):
    v = num(rows, key)
    return round(sum(v) / len(v), nd) if v else "unavailable"


def cell(x):
    return str(x).replace("|", ", ")


# ---------------- A. retrieval ----------------
def eval_retrieval():
    bm25, rows = BM25(load_chunks()), []
    for c in json.loads((DATA / "retrieval_cases.json").read_text()):
        t = time.perf_counter()
        hits = bm25.search(c["q"])
        ms = round((time.perf_counter() - t) * 1000, 2)
        titles = [h["title"] for h in hits]
        ok = (not hits) if c["expect_title"] is None else c["expect_title"] in titles
        rows.append({"question": c["q"], "expected": c["expect_title"] or "(nothing relevant)", "passed": ok,
                     "chunk_ids": "|".join(h["id"] for h in hits), "titles": " | ".join(titles),
                     "scores": "|".join(str(h["score"]) for h in hits), "latency_ms": ms})
    return rows


# ---------------- B. agent with the real model ----------------
def run_case(case, db_path):
    student = case["student"]
    if case.get("db") == "broken":
        db_path = str(Path(tempfile.mkdtemp()) / "broken.db")
    r = None
    for q in case["steps"]:  # each step = new session with no chat history; only SQLite memory carries over
        r = run_agent(q, student, [], "eval", db_path=db_path)
    answer, names, problems = r.answer.lower(), [t["name"] for t in r.tools_called], []

    tool_ok = case["expect_tool"] is None or case["expect_tool"] in names
    if not tool_ok:
        problems.append(f"expected tool {case['expect_tool']} not called")
    if case.get("forbid_tool") and case["forbid_tool"] in names:
        tool_ok = False
        problems.append(f"{case['forbid_tool']} was called but must not be")
    if case.get("expect_tool_ok") is False and tool_ok and not any(
            t["name"] == case["expect_tool"] and not t["ok"] for t in r.tools_called):
        tool_ok = False
        problems.append("tool should have rejected the input but did not")
    if not any(re.search(p, answer) for p in case["expect_any"]):
        problems.append("expected facts missing from answer")
    if any(re.search(p, answer) for p in case["forbid"]):
        problems.append("forbidden text present in answer")

    broken = case.get("db") == "broken"
    mems = [] if broken else memory.list_memory(student, db_path)
    if "db_check" in case:
        chk = case["db_check"]
        if not any(m["key"] == chk["key"] and chk["contains"] in m["value"].lower() for m in mems):
            problems.append("memory was not persisted in SQLite")
    if any(bad in json.dumps(mems).lower() for bad in case.get("db_no_memory_contains", [])):
        problems.append("sensitive text found in stored memory")
    if case.get("db_memory_empty") and mems:
        problems.append("temporary statement was stored in memory")
    if r.error:
        problems.append(f"agent error: {r.error}")

    passed = not problems
    used = "|".join(names) or "none"
    return {"id": case["id"], "category": case["category"], "passed": passed, "tool_correct": tool_ok,
            "tools_used": used, "tools_all_ok": all(t["ok"] for t in r.tools_called) if names else "",
            "policy_chunks": "|".join(c["id"] for c in r.chunks), "memory_ids_in_context": "|".join(map(str, r.memory_used)),
            "total_s": r.total_seconds, "llm_s": r.llm_seconds, "in_tokens": r.input_tokens, "out_tokens": r.output_tokens,
            "notes": ("OK. Tools: " + used) if passed else "; ".join(problems)}


def eval_agent():
    cases = json.loads((DATA / "test_cases.json").read_text())
    db_path = str(Path(tempfile.mkdtemp()) / "eval.db")
    database.init_db(db_path)
    return [run_case(c, db_path) for c in cases]


# ---------------- C. Assignment 2: privacy / approval / audit ----------------
def _profile(db_path, sid):
    conn = database.connect(db_path)
    p = conn.execute("SELECT email,phone FROM student_profile WHERE student_id=?", (sid,)).fetchone()
    f = conn.execute("SELECT due_date FROM fees WHERE student_id=?", (sid,)).fetchone()
    conn.close()
    return {"email": p["email"], "phone": p["phone"], "fee_due_date": f["due_date"]}


def run_a2_case(case, db_path):
    sid, problems = case["student"], []
    before = _profile(db_path, sid)
    first_audit = audit.list_audit(None, 1, db_path)
    mark = first_audit[0]["audit_id"] if first_audit else 0
    r = run_agent(case["q"], sid, [], "eval-a2", db_path=db_path)
    names = [t["name"] for t in r.tools_called]
    answer = r.answer.lower()

    if case["expect_tool"] and case["expect_tool"] not in names:
        problems.append(f"expected tool {case['expect_tool']} not called")
    if case["expect_tool"] is None and names:
        problems.append(f"no tool should run, got {names}")
    if not any(re.search(p, answer) for p in case["expect_any"]):
        problems.append("expected text missing from answer")
    if any(re.search(p, answer) for p in case["forbid"]):
        problems.append("forbidden text present in answer")

    after_request = _profile(db_path, sid)
    if case.get("expect_pending"):
        if not r.pending_approval:
            problems.append("no approval request was created")
        if after_request != before:
            problems.append("record changed BEFORE approval")
    decision_note = ""
    if case.get("decide") and r.pending_approval:
        res = approvals.decide(sid, r.pending_approval["approval_id"], case["decide"] == "approve", db_path)
        decision_note = res.get("status", res.get("error", ""))
        final = _profile(db_path, sid)
        field, new = case["profile_field"], case["new_value"]
        if case["decide"] == "reject" and final != before:
            problems.append("rejected change was executed")
        if case["decide"] == "approve" and final[field] != new:
            problems.append("approved change was not executed")
    if case.get("memory_empty") and memory.list_memory(sid, db_path):
        problems.append("secret/temporary text stored in memory")
    for bad in case.get("forbid_in_logs", []):
        if config.LOG_PATH.exists() and bad in config.LOG_PATH.read_text(encoding="utf-8", errors="ignore"):
            problems.append(f"secret '{bad}' found in trace log")

    new_rows = [a for a in audit.list_audit(sid, 200, db_path) if a["audit_id"] > mark]
    exp = case["expect_audit"]
    hit = [a for a in new_rows if (a["action"], a["decision"], a["result"]) == (exp["action"], exp["decision"], exp["result"])]
    if not hit:
        problems.append(f"audit record {exp['action']}/{exp['decision']}/{exp['result']} missing")
    evidence = " ; ".join(f"{a['action']}:{a['decision']}:{a['result']}" for a in reversed(new_rows))
    return {"id": case["id"], "category": case["category"], "passed": not problems, "tools_used": "|".join(names) or "none",
            "approval_status": decision_note or ("pending" if r.pending_approval else "-"), "audit_evidence": evidence,
            "total_s": r.total_seconds, "llm_s": r.llm_seconds, "in_tokens": r.input_tokens, "out_tokens": r.output_tokens,
            "notes": "OK" if not problems else "; ".join(problems)}


LAST_SECURITY_DB = None


def eval_security():
    global LAST_SECURITY_DB
    cases = json.loads((DATA / "test_cases_a2.json").read_text())
    db_path = str(Path(tempfile.mkdtemp()) / "eval_a2.db")
    database.init_db(db_path)
    LAST_SECURITY_DB = db_path
    return [run_a2_case(c, db_path) for c in cases]


def read_baseline():
    p = REPORTS / "baseline_a1" / "evaluation_agent.csv"
    if not p.exists():
        return None
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def passed_count(rows):
    return sum(str(r["passed"]).lower() == "true" for r in rows)


def frac(rows):
    return f"{sum(str(r['passed']).lower() == 'true' for r in rows)}/{len(rows)}" if rows else "n/a"


# ---------------- report ----------------
def main():
    REPORTS.mkdir(exist_ok=True)
    md = [f"# Evaluation report (Assignment 2)\n\nModel: `{config.GROQ_MODEL}`. All figures were measured in this run. Sample (fictional) data. T01-T13 = Assignment 1 test set re-run with the new controls; P01-P08 = Assignment 2 privacy/approval/audit tests.\n"]

    ret = eval_retrieval()
    write_csv("evaluation_retrieval.csv", ret)
    md += ["## A. Policy retrieval (no LLM)\n", f"- Retrieval success: **{sum(r['passed'] for r in ret)}/{len(ret)}**; average latency {avg(ret, 'latency_ms')} ms\n"]
    print(f"A. Retrieval: {sum(r['passed'] for r in ret)}/{len(ret)} passed")

    md.append("\n## B. Assignment 1 test set (T01-T13) re-run with privacy controls on\n")
    if not config.GROQ_API_KEY:
        md.append("**NOT RUN.** GROQ_API_KEY is not set, so no agent results were measured. Set it in `.env` and run `python evaluate.py` again.\n")
        print("B. Agent tests skipped: GROQ_API_KEY missing.")
    else:
        rows = eval_agent()
        write_csv("evaluation_agent.csv", rows)
        md += ["### Summary\n", "| Measure | Result |", "|---|---|",
               f"| Task accuracy / success (T01-T13) | {frac(rows)} |",
               f"| Correct tool choice | {sum(r['tool_correct'] for r in rows)}/{len(rows)} |",
               f"| Avg latency (s) | {avg(rows, 'total_s')} |",
               f"| Avg input tokens | {avg(rows, 'in_tokens', 0)} |",
               f"| Avg output tokens | {avg(rows, 'out_tokens', 0)} |\n"]
        md += ["### Per-test results\n",
               "| id | category | result | tools used | policy chunks | memory ids | total s | llm s | in tok | out tok | key observation |",
               "|---|---|---|---|---|---|---|---|---|---|---|"]
        md += [f"| {r['id']} | {r['category']} | {'PASS' if r['passed'] else 'FAIL'} | {cell(r['tools_used'])} | {cell(r['policy_chunks'] or '-')} | "
               f"{cell(r['memory_ids_in_context'] or '-')} | {r['total_s']} | {r['llm_s']} | {r['in_tokens']} | {r['out_tokens']} | {cell(r['notes'])} |" for r in rows]
        failed = [r for r in rows if not r["passed"]]
        md += ["\n### Key observations (generated from this run)\n"]
        md += [f"- {r['id']} ({r['category']}) failed: {r['notes']}" for r in failed] or ["- All agent test questions passed in this run."]
        md.append(f"- Slowest test: {max(rows, key=lambda r: r['total_s'])['id']} at {max(r['total_s'] for r in rows)} s.")
        samples = [l for l in (config.LOG_PATH.read_text().splitlines()[-3:] if config.LOG_PATH.exists() else [])]
        if samples:
            md += ["\n### Sample trace lines (`logs/traces.jsonl`, last 3 runs)\n", "```"] + samples + ["```"]
        print(f"B. Agent: {frac(rows)} passed; avg latency {avg(rows, 'total_s')} s")

        sec = eval_security()
        write_csv("evaluation_security.csv", sec)
        md += ["\n## C. Assignment 2 privacy, approval and audit tests (P01-P08)\n", "| id | category | result | tools used | approval status | audit evidence (action:decision:result) | total s | in tok | out tok | notes |",
               "|---|---|---|---|---|---|---|---|---|---|"]
        md += [f"| {r['id']} | {r['category']} | {'PASS' if r['passed'] else 'FAIL'} | {cell(r['tools_used'])} | {cell(r['approval_status'])} | {cell(r['audit_evidence'])} | "
               f"{r['total_s']} | {r['in_tokens']} | {r['out_tokens']} | {cell(r['notes'])} |" for r in sec]
        priv = [r for r in sec if r["id"] in ("P03", "P04")]
        unsafe = [r for r in sec if r["id"] in ("P05", "P06", "P07")]
        base = read_baseline()
        md += ["\n## D. Final comparison with Assignment 1\n", "| Measure | Assignment 1 (baseline) | Assignment 2 (this run) |", "|---|---|---|"]
        md += [f"| Task accuracy / success (T01-T13) | {frac(base) if base else 'n/a'} | {frac(rows)} |",
               f"| Privacy tests: attempts to read another student's data blocked (P03-P04) | not implemented (T10 only checked the answer text) | {sum(r['passed'] for r in priv)}/{len(priv)} |",
               f"| Unsafe-action tests: sensitive change waited for approval / rejected change not executed (P05-P07) | not implemented | {sum(r['passed'] for r in unsafe)}/{len(unsafe)} |",
               f"| Secrets kept out of memory and logs (P08) | T09 (memory check only) | {frac([r for r in sec if r['id'] == 'P08'])} |",
               f"| Avg latency, T01-T13 (s) | {avg(base, 'total_s') if base else 'n/a'} | {avg(rows, 'total_s')} |",
               f"| Avg latency, P01-P08 (s) | n/a | {avg(sec, 'total_s')} |",
               f"| Avg input tokens, T01-T13 | {avg(base, 'in_tokens', 0) if base else 'n/a'} | {avg(rows, 'in_tokens', 0)} |",
               f"| Avg output tokens, T01-T13 | {avg(base, 'out_tokens', 0) if base else 'n/a'} | {avg(rows, 'out_tokens', 0)} |",
               f"| Audit records written during P01-P08 | none | {len(audit.list_audit(None, 10000, LAST_SECURITY_DB))} |"]
        md.append("\nNote: P03/P04 are blocked in Python before the model is called, so they use 0 tokens and respond faster than Assignment 1 answers; the extra latency of approval is only the extra tool round-trip in P05-P07.")
        print(f"C. Security tests: {frac(sec)} passed")

    md.append("\n## Limitations\n\n- Answer checks on LLM output use keyword/regex rules, so they approximate correctness; tool and database checks are exact.\n"
              "- LLM output varies between runs; run twice and compare.\n- Evaluation is separate from tracing: traces show what happened, they do not prove an answer is correct.")
    (REPORTS / "evaluation.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("Report written to reports/evaluation.md")


if __name__ == "__main__":
    main()
