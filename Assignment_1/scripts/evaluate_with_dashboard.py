"""Run Assignment 1 evaluation and append dashboard-ready evaluation records to traces.jsonl.
Usage: python scripts/evaluate_with_dashboard.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
import evaluate
from tracing import log_run

_original_eval_agent = evaluate.eval_agent


def eval_agent_with_trace_records():
    rows = _original_eval_agent()
    cases = {c["id"]: c for c in json.loads((evaluate.DATA / "test_cases.json").read_text(encoding="utf-8"))}
    for row in rows:
        case = cases.get(row["id"], {})
        actual_tools = [] if row.get("tools_used") in (None, "", "none") else str(row["tools_used"]).split("|")
        log_run({
            "record_type": "evaluation",
            "test_id": row.get("id"),
            "category": row.get("category"),
            "passed": bool(row.get("passed")),
            "expected_tool": case.get("expect_tool"),
            "actual_tools": actual_tools,
            "tool_correct": bool(row.get("tool_correct")),
            "tools_all_ok": row.get("tools_all_ok"),
            "policy_chunks": str(row.get("policy_chunks") or "").split("|") if row.get("policy_chunks") else [],
            "memory_ids": str(row.get("memory_ids_in_context") or "").split("|") if row.get("memory_ids_in_context") else [],
            "total_s": row.get("total_s"),
            "llm_s": row.get("llm_s"),
            "in_tokens": row.get("in_tokens"),
            "out_tokens": row.get("out_tokens"),
            "notes": row.get("notes")
        })
    return rows


evaluate.eval_agent = eval_agent_with_trace_records

if __name__ == "__main__":
    evaluate.main()
